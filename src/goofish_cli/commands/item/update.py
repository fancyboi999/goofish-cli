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
from typing import Annotated, Any

import typer

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
    images: Annotated[list[str] | None, typer.Option()] = None,
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
    # 在售闸门：edit 提交带发布语义，「editDetail 原样回传」不能保留上下架状态
    # （作者实测：已下架商品编辑一次后 itemStatus 1→0、quantity 0→1，重新变成在售）。
    # 实测语义：在售 itemStatus="0"，已下架 itemStatus="1"。
    item_status = str(detail.get("itemStatus") or "").strip()
    if item_status != "0":
        raise GoofishError(
            f"商品 {item_id} 当前不是在售状态（itemStatus={item_status or '缺失'}），"
            "编辑会把已下架商品重新上架；请先上架或在 App 内修改。"
        )
    with write_operation(session, "item.write"):
        # 图片上传放在限流检查之后：被限流/熔断拒绝时不白传。
        receipts = [media_upload(str(p)) for p in image_paths] if image_paths is not None else None
        payload = _build_edit_payload(
            detail,
            item_id=str(item_id),
            price_cents=cents,
            title=title,
            desc=desc_text,
            image_receipts=receipts,
        )
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
    if desc_text is not None or (title is not None and str((detail.get("itemTextDTO") or {}).get("titleDescSeparate") or "").strip().lower() == "false"):
        # 口径一致：old/new 都用平台最终格式（内嵌标题商品 desc 含标题前缀）
        changed["desc"] = {
            "old": old_text.get("desc"),
            "new": payload["itemTextDTO"]["desc"],
        }
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


def _sync_item_text(text_dto: dict[str, Any], *, title: str | None, desc: str | None) -> dict[str, Any]:
    """改 title/desc 时同步派生字段（richTextDesc / desc / wlDescription）。

    是否内嵌标题由 editDetail 的 itemTextDTO.titleDescSeparate 决定（实测 "false"），
    不用 desc.startswith(title) 前缀猜测——描述开头恰好重复标题的分离式商品会被误删。
    内嵌时 desc = 标题 + 恰好一个 "\\n" + 描述正文：拆分只去掉这一个 "\\n"，不做
    lstrip/rstrip（空行与末尾换行逐字节保留）；wlDescription = 标题 + desc。
    richTextDesc：深拷贝原结构，只替换 Text 节点的 text，顶层键（version/type/
    properties）与图片、格式等非文本节点原样保留，不重建。
    """
    old_title = str(text_dto.get("title") or "")
    old_desc = str(text_dto.get("desc") or "")
    embedded = str(text_dto.get("titleDescSeparate") or "").strip().lower() == "false"
    if embedded and old_title and old_desc.startswith(old_title):
        after = old_desc[len(old_title):]
        body = after[1:] if after.startswith("\n") else after
    else:
        embedded = False
        body = old_desc
    new_title = title if title is not None else old_title
    new_body = desc if desc is not None else body
    out = dict(text_dto)
    out["title"] = new_title
    out["desc"] = f"{new_title}\n{new_body}" if embedded else new_body
    out["wlDescription"] = new_title + out["desc"]
    out["richTextDesc"] = _rewrite_rich_text(out.get("richTextDesc"), embedded=embedded,
                                             new_title=new_title, new_body=new_body,
                                             body_changed=desc is not None)
    return out


def _rewrite_rich_text(raw_rtd: Any, *, embedded: bool, new_title: str, new_body: str,
                       body_changed: bool) -> Any:
    """只替换 richTextDesc 里的文本节点，结构与顶层键原样保留。

    内嵌标题商品：第一个 Element 的文本 = 新标题，其余 Element 依次对应描述行。
    分离式商品：只在描述本身变化时按顺序替换文本节点；只改标题则 richTextDesc
    原样返回（其内不含标题）。行数多于元素时克隆最后一个纯文本元素追加，
    少于元素时多余纯文本元素清空文本（含图片/格式节点的元素不动）。
    """
    if isinstance(raw_rtd, str) and raw_rtd.strip():
        try:
            rtd = json.loads(raw_rtd)
        except (ValueError, TypeError):
            rtd = None
    else:
        rtd = raw_rtd if isinstance(raw_rtd, dict) else None
    if not isinstance(rtd, dict):
        return raw_rtd
    out = json.loads(json.dumps(rtd))  # 深拷贝：version/properties 等顶层键原样保留
    children = out.get("children")
    if not isinstance(children, list) or not children:
        return out
    elements = [c for c in children if isinstance(c, dict)]
    if embedded:
        lines = [new_title, *new_body.split("\n")]
    elif not body_changed:
        return out
    else:
        lines = new_body.split("\n")
    for el, line in zip(elements, lines, strict=False):
        _set_element_text(el, line)
    if len(lines) > len(elements):
        template = None
        for el in reversed(elements):
            if _pure_text_element(el):
                template = el
                break
        if template is not None:
            extra = [json.loads(json.dumps(template)) for _ in lines[len(elements):]]
            for el, line in zip(extra, lines[len(elements):], strict=False):
                _set_element_text(el, line)
            out["children"] = children + extra
    elif len(lines) < len(elements):
        for el in elements[len(lines):]:
            if _pure_text_element(el):
                _set_element_text(el, "")
    if isinstance(raw_rtd, str):
        return json.dumps(out, ensure_ascii=False)
    return out


def _set_element_text(element: dict[str, Any], text: str) -> None:
    for child in element.get("children") or []:
        if isinstance(child, dict) and child.get("type") == "Text":
            child["text"] = text
            return


def _pure_text_element(element: dict[str, Any]) -> bool:
    children = element.get("children")
    if not isinstance(children, list) or not children:
        return False
    return all(
        isinstance(c, dict) and c.get("type") == "Text" for c in children
    )


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
    if title is not None or desc is not None:
        data["itemTextDTO"] = _sync_item_text(
            data.get("itemTextDTO") or {}, title=title, desc=desc,
        )
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
