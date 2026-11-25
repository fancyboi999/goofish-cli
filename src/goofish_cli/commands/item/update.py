"""item update — 修改在售商品（价格/标题/描述/图片，一次只改传入的字段）。

流程：editDetail（读取编辑页全量）→ 回写差异字段（仅传入字段）→ edit
接口：mtop.idle.pc.idleitem.editDetail v1.0（只读）+ mtop.idle.pc.idleitem.edit v1.0（写操作）；
线索宝贝（服务类目）PC 链路被拒（LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH）时
自动回退 mtop.idle.idleitem.edit v1.0（不带 pc 段的通用编辑链路，实测可用）。

为什么不做「全量重建」：editDetail 返回的是编辑页当前可编辑数据，
原样回传再覆写传入字段，其余字段保持服务端当前值，
避免只改一个字段时意外破坏标题/图片/类目/地址。

字段约束：标题 ≤ 30 字、描述 ≤ 1500 字（超长直接报错，不静默截断）；
图片 1~9 张，png/jpg/webp，先经 media upload 拿收据再按顺序写入
imageInfoDOList（第一个 = 首图 major=true）。
--dry-run 不发任何请求（不拉详情、不上传），只展示将要覆写的差异字段。
"""

import json
import time
from pathlib import Path
from typing import Any

from goofish_cli.commands.item.publish import _money
from goofish_cli.commands.media.upload import upload as media_upload
from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.mtop import call
from goofish_cli.core.write_operation import write_operation

# edit 提交需要的场景字段；editDetail 响应不含这些键，按 PC 编辑页行为补齐。
_SCENE_FIELDS = {
    "sourceId": "pcMainPublish",
    "bizcode": "pcMainPublish",
    "publishScene": "pcMainPublish",
}

_TITLE_MAX_LEN = 30
_DESC_MAX_LEN = 1500
_IMAGES_MIN = 1
_IMAGES_MAX = 9
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# 常规商品的 PC 编辑链路（原路径，行为不变）。
_EDIT_API = "mtop.idle.pc.idleitem.edit"
# 线索宝贝（服务类目）的通用编辑链路：PC 链路会报
# LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH，此接口实测（同价 no-op）可用。
_LEAD_EDIT_API = "mtop.idle.idleitem.edit"


@command(
    namespace="item",
    name="update",
    description="修改在售商品（价格/标题/描述/图片；先拉编辑详情再回写差异字段）",
    strategy=Strategy.COOKIE,
    columns=["item_id", "changed", "ok", "message"],
    write=True,
    arguments=["item_id"],
)
def update(
    item_id: str,
    *,
    price: float | None = None,
    title: str | None = None,
    desc: str | None = None,
    desc_file: str | None = None,
    images: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    desc_text = _resolve_desc(desc, desc_file)
    image_paths = _validate_images(images or [])
    if price is None and title is None and desc_text is None and image_paths is None:
        raise GoofishError("必须至少提供 --price / --title / --desc(--desc-file) / --images 之一")
    if title is not None and len(title) > _TITLE_MAX_LEN:
        raise GoofishError(f"标题最长 {_TITLE_MAX_LEN} 字（当前 {len(title)} 字），不做静默截断")
    if desc_text is not None and len(desc_text) > _DESC_MAX_LEN:
        raise GoofishError(f"描述最长 {_DESC_MAX_LEN} 字（当前 {len(desc_text)} 字），不做静默截断")
    if price is not None and price <= 0:
        raise GoofishError("价格必须大于 0（单位元，最多两位小数）")

    cents = _money(price) if price is not None else None
    if dry_run:
        # dry-run 不发任何请求（不拉 editDetail、不上传图片）：
        # would_overwrite 只展示「将覆写的差异字段」及新值，
        # 全量回写体在真实执行时由 editDetail 的当前返回决定。
        would: dict[str, Any] = {}
        if title is not None or desc_text is not None:
            text_overwrite: dict[str, Any] = {}
            if title is not None:
                text_overwrite["title"] = title
            if desc_text is not None:
                text_overwrite["desc"] = desc_text
            would["itemTextDTO"] = text_overwrite
        if cents is not None:
            would["itemPriceDTO"] = {"priceInCent": cents}
        if image_paths is not None:
            would["imageInfoDOList"] = [
                {"source": str(p)} for p in image_paths
            ]
        return {
            "item_id": str(item_id),
            "dry_run": True,
            "new_price": price,
            "priceInCent": cents,
            "would_overwrite": would,
            "changed": {},
            "ok": None,
            "message": "dry-run：未发送任何请求；old 值在真实执行时由 editDetail 决定",
        }
    session = Session.load()
    detail_raw = call(
        session,
        api="mtop.idle.pc.idleitem.editDetail",
        data={"itemId": str(item_id)},
        version="1.0",
        spm_cnt="a21ybx.item.0.0",
    )
    detail = detail_raw.get("data") if isinstance(detail_raw, dict) else None
    if not isinstance(detail, dict) or not detail:
        raise GoofishError("editDetail 返回为空，无法构造编辑 payload")
    receipts = [media_upload(str(p)) for p in image_paths] if image_paths is not None else None
    payload = _build_edit_payload(
        detail,
        item_id=str(item_id),
        price_cents=cents,
        title=title,
        desc=desc_text,
        image_receipts=receipts,
    )
    with write_operation(session, "item.write"):
        try:
            raw = call(
                session,
                api=_EDIT_API,
                data=payload,
                version="1.0",
                spm_cnt="a21ybx.publish.0.0",
            )
        except GoofishError as exc:
            # call() 对非 SUCCESS ret 会抛错；仅线索宝贝拒绝码才触发回退，
            # 其他错误（风控/参数/网络）原样抛出。
            if "LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH" not in str(exc):
                raise
            raw = {"ret": [str(exc)]}
        ret = raw.get("ret") or []
        joined = " | ".join(ret)
        if "LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH" in joined:
            # 线索宝贝（服务类目）禁止 PC 链路编辑，但平台允许走通用编辑链路：
            # mtop.idle.idleitem.edit（不带 pc 段）对线索宝贝实测可用（同价 no-op 探测
            # 返回 SUCCESS），普通商品不触发此回退、保持原 PC 路径不变。
            try:
                raw = call(
                    session,
                    api=_LEAD_EDIT_API,
                    data=payload,
                    version="1.0",
                    spm_cnt="a21ybx.publish.0.0",
                )
            except GoofishError as exc:
                if "LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH" not in str(exc):
                    raise
                raise GoofishError("该商品是线索宝贝（服务类目），PC 与通用编辑链路均被平台拒绝；"
                                   "请在闲鱼 App 内修改，或下架后重新发布。原始错误：" + str(exc)) from exc
            ret = raw.get("ret") or []
            joined = " | ".join(ret)
            if "LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH" in joined:
                raise GoofishError("该商品是线索宝贝（服务类目），PC 与通用编辑链路均被平台拒绝；"
                                   "请在闲鱼 App 内修改，或下架后重新发布。原始错误：" + joined)
    old_text = detail.get("itemTextDTO") or {}
    old_images = detail.get("imageInfoDOList") or []
    changed: dict[str, Any] = {}
    if title is not None:
        changed["title"] = {"old": old_text.get("title"), "new": title}
    if desc_text is not None:
        changed["desc"] = {"old": old_text.get("desc"), "new": desc_text}
    if cents is not None:
        old_cents = str((detail.get("itemPriceDTO") or {}).get("priceInCent", ""))
        changed["price"] = {
            "old": int(old_cents) / 100 if old_cents.isdigit() else old_cents,
            "new": price,
        }
    if receipts is not None:
        changed["images"] = {
            "old": [img.get("url") for img in old_images],
            "new": [r["url"] for r in receipts],
        }
    return {
        "item_id": str(item_id),
        "changed": changed,
        "ok": any("SUCCESS" in r for r in ret),
        "message": joined,
    }


def _resolve_desc(desc: str | None, desc_file: str | None) -> str | None:
    if desc is not None and desc_file is not None:
        raise GoofishError("--desc 与 --desc-file 只能二选一")
    if desc_file is not None:
        path = Path(desc_file).expanduser()
        if not path.is_file():
            raise GoofishError(f"描述文件不存在：{desc_file}")
        return path.read_text(encoding="utf-8")
    return desc


def _validate_images(paths: list[str]) -> list[Path] | None:
    if not paths:
        return None
    if len(paths) < _IMAGES_MIN or len(paths) > _IMAGES_MAX:
        raise GoofishError(f"图片数量必须在 {_IMAGES_MIN}~{_IMAGES_MAX} 张之间")
    resolved: list[Path] = []
    for raw in paths:
        source = Path(raw).expanduser()
        if not source.is_file() or source.stat().st_size == 0:
            raise GoofishError(f"图片文件不存在或为空：{raw}")
        if source.suffix.lower() not in _IMAGE_EXTS:
            raise GoofishError(f"不支持的图片格式：{raw}（仅支持 png/jpg/webp）")
        resolved.append(source)
    return resolved


def _build_edit_payload(
    detail: dict[str, Any],
    *,
    item_id: str,
    price_cents: str | None = None,
    title: str | None = None,
    desc: str | None = None,
    image_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """从 editDetail 全量构造 edit 请求体：除传入字段外逐字段保持原值。"""
    data = json.loads(json.dumps(detail))
    data["itemId"] = str(item_id)
    text_dto = dict(data.get("itemTextDTO") or {})
    if title is not None:
        text_dto["title"] = title
    if desc is not None:
        text_dto["desc"] = desc
    if title is not None or desc is not None:
        data["itemTextDTO"] = text_dto
    if price_cents is not None:
        price_dto = dict(data.get("itemPriceDTO") or {})
        price_dto["priceInCent"] = str(price_cents)
        data["itemPriceDTO"] = price_dto
    if image_receipts is not None:
        data["imageInfoDOList"] = [
            {
                "extraInfo": {"isH": "false", "isT": "false", "raw": "false"},
                "isQrCode": False,
                "url": img["url"],
                "heightSize": img["height"],
                "widthSize": img["width"],
                "major": index == 0,
                "type": 0,
                "status": "done",
            }
            for index, img in enumerate(image_receipts)
        ]
    data.setdefault("simpleItem", "true")
    data.setdefault("uniqueCode", str(time.time_ns() // 1000))
    data.update(_SCENE_FIELDS)
    return data
