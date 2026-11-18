"""item edit — 编辑已有商品（改标题/描述/价格/图片）。

接口：mtop.idle.pc.idleitem.edit v1.0（写操作，受限流和风控护栏保护）

安全约定：
- 默认 dry-run：只拉草稿、组装提交报文并返回预览，不真正提交。
- 必须显式传 --confirm 才会调用写接口；不传的任何改动都不会落到线上。
- 以 editDetail 回显草稿为基底，只覆盖用户显式传入的字段；未传的沿用草稿。

图片两种模式：
- --images a.jpg b.jpg：全量替换为这些本地图（先上传）。
- --add-images c.jpg：在现有草稿图片后追加（先上传）。
- 都不传：保留草稿现有图片。
"""
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any

from goofish_cli.commands.item.edit_detail import _rich_text_plain
from goofish_cli.commands.media.upload import upload, validate_image_path
from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.mtop import call
from goofish_cli.core.write_operation import write_operation


def _cents(value: float) -> str:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise GoofishError("价格必须是有效数字") from None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise GoofishError("价格必须非负且最多两位小数")
    return str(int(amount * 100))


def _num(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _receipt(url: str, width: Any, height: Any, major: bool) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "extraInfo": {"isH": "false", "isT": "false", "raw": "false"},
        "isQrCode": False,
        "url": url,
        "major": major,
        "type": 0,
        "status": "done",
    }
    w, h = _num(width), _num(height)
    if w is not None:
        receipt["widthSize"] = w
    if h is not None:
        receipt["heightSize"] = h
    return receipt


def _draft_images(draft: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for index, img in enumerate(draft.get("imageInfoDOList") or []):
        if not isinstance(img, dict) or not img.get("url"):
            continue
        out.append(_receipt(
            img["url"],
            img.get("widthSize") or img.get("width"),
            img.get("heightSize") or img.get("height"),
            index == 0,
        ))
    return out


def _resolve_text(
    text: dict[str, Any], override_title: str | None, override_desc: str | None
) -> tuple[str, str]:
    """从草稿解析标题/描述，叠加用户显式传入的覆盖值；为空则报错。"""
    plain = _rich_text_plain(text.get("richTextDesc"))
    paragraphs = [p for p in plain.split("\n") if p]
    title = (text.get("title") or "").strip()
    desc = (text.get("desc") or "").strip()
    if not title and paragraphs:
        title = paragraphs[0]
    if not desc:
        desc = "\n".join(paragraphs[1:]) if len(paragraphs) > 1 else plain
    new_title = (override_title or "").strip() or title
    new_desc = (override_desc or "").strip() or desc
    if not new_title or not new_desc:
        raise GoofishError("标题和描述不能为空")
    return new_title, new_desc


def _upload_local(paths: list[str]) -> list[dict[str, Any]]:
    receipts = []
    for path in paths:
        receipt = upload(path)
        receipts.append(_receipt(receipt["url"], receipt["width"], receipt["height"], False))
    return receipts


def _mark_single_major(receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并后只允许一张主图：第一张标 major=True，其余一律 False。"""
    for index, receipt in enumerate(receipts):
        receipt["major"] = index == 0
    return receipts


def _image_mode(
    images: list[str] | None, add_images: list[str] | None
) -> tuple[bool, list[str]]:
    """解析图片模式：返回 (是否全量替换, 待上传的本地图)。

    两种模式互斥——同时传 --images 与 --add-images 时，追加的那批会被替换逻辑吞掉，
    编辑却报成功，属于静默丢参数，故直接报错而不是二选一。
    """
    if images and add_images:
        raise GoofishError("--images（全量替换）与 --add-images（追加）不能同时使用")
    if images:
        return True, list(images)
    return False, list(add_images or [])


def _resolve_default_price(price: float | None, draft: dict[str, Any]) -> bool:
    """显式给出一口价时切到一口价(False)；不传价则沿用草稿的议价/一口价模式。"""
    explicit = price is not None and price > 0
    return False if explicit else bool(draft.get("defaultPrice", False))


def _resolve_group_dto(draft: dict[str, Any]) -> dict[str, Any]:
    """沿用草稿的分组设置；草稿没有分组时回退空结构，绝不在提交时清空已有分组。"""
    group = draft.get("itemGroupDTO")
    return dict(group) if isinstance(group, dict) else {"groupId": ""}


def _resolve_protocols(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """原样带过草稿勾选的服务协议，不重写成固定关闭某一项。"""
    protocols = draft.get("userRightsProtocols")
    return list(protocols) if isinstance(protocols, list) else []


@command(
    namespace="item",
    name="edit",
    description="编辑已有商品（改标题/描述/价格/图片）；默认 dry-run，--confirm 才提交",
    strategy=Strategy.COOKIE,
    columns=["item_id", "ok", "title", "price", "image_count"],
    write=True,
    arguments=["item_id"],
)
def edit(
    item_id: str,
    *,
    title: str | None = None,
    desc: str | None = None,
    price: float | None = None,
    images: list[str] | None = None,
    add_images: list[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    if not str(item_id).isdigit():
        raise GoofishError("商品 ID 必须为数字")
    session = Session.load()

    # 1. 拉可编辑草稿
    draft_raw = call(
        session,
        api="mtop.idle.pc.idleitem.editdetail",
        data={"itemId": str(item_id)},
        version="1.0",
        spm_cnt="a21ybx.publish.0.0",
    )
    draft = draft_raw.get("data") if isinstance(draft_raw, dict) else None
    if not isinstance(draft, dict):
        raise GoofishError("编辑草稿响应结构异常，未提交")

    text = draft.get("itemTextDTO") or {}
    new_title, new_desc = _resolve_text(text, title, desc)

    price_dto = dict(draft.get("itemPriceDTO") or {})
    # 先校验所有显式给出的价格：负数 / NaN / 非法精度在此直接报错，
    # 不能在"是否一口价"的过滤阶段被当成没传价，导致编辑报成功而价格没变。
    price_cents = _cents(price) if price is not None else None
    explicit_price = price_cents is not None and int(price_cents) > 0
    if explicit_price:
        price_dto["priceInCent"] = price_cents
    # 定价模式与金额联动：显式给出一口价时，defaultPrice 必须切到一口价(False)，
    # 否则草稿是议价(True) 时提交仍按议价走，金额被忽略；不传价则沿用草稿模式。
    default_price = _resolve_default_price(price, draft)
    price_yuan = None
    if price_dto.get("priceInCent"):
        try:
            price_yuan = f"{int(price_dto['priceInCent']) / 100:.2f}"
        except (TypeError, ValueError):
            price_yuan = None

    # 2. 图片：替换 / 追加 / 沿用草稿
    # dry-run 阶段只校验本地路径并占位，不实际上传；上传放到 --confirm 提交前。
    replace, local_paths = _image_mode(images, add_images)
    existing = [] if replace else _draft_images(draft)
    for path in local_paths:
        validate_image_path(path)

    # 先按最终张数校验，避免超限的图片先白耗上传额度。
    if not 1 <= len(existing) + len(local_paths) <= 9:
        raise GoofishError("商品必须有 1–9 张图片")

    if not confirm:
        image_list = existing + [{"pending_upload": p} for p in local_paths]
    elif images:
        image_list = _mark_single_major(_upload_local(images))
    elif add_images:
        image_list = _mark_single_major(existing + _upload_local(add_images))
    else:
        image_list = existing

    cat = draft.get("itemCatDTO") or {}
    addr = draft.get("itemAddrDTO") or {}
    post = draft.get("itemPostFeeDTO") or {}

    # 3. 组装提交报文（字段对齐前端 build：publish/edit 同构）
    data: dict[str, Any] = {
        "itemId": str(item_id),
        "itemTypeStr": draft.get("itemTypeStr", "b"),
        "quantity": draft.get("quantity", "1"),
        "simpleItem": draft.get("simpleItem", "true"),
        "freebies": draft.get("freebies", False),
        "editorVersion": "",
        "uniqueCode": str(time.time_ns() // 1000),
        "sourceId": "pcMainPublish",
        "bizcode": "pcMainPublish",
        "publishScene": "pcMainPublish",
        "itemTextDTO": {"title": new_title, "desc": new_desc, "titleDescSeparate": True},
        "imageInfoDOList": image_list,
        "itemPriceDTO": price_dto,
        "itemCatDTO": {
            "catId": cat.get("catId", ""), "catName": cat.get("catName", ""),
            "channelCatId": cat.get("channelCatId", ""), "tbCatId": cat.get("tbCatId", ""),
        },
        "itemAddrDTO": {
            "area": addr.get("area", ""), "city": addr.get("city", ""),
            "divisionId": addr.get("divisionId", ""), "gps": addr.get("gps", ""),
            "poiId": addr.get("poiId", ""), "poiName": addr.get("poiName", ""),
            "prov": addr.get("prov", ""),
        },
        "itemPostFeeDTO": post,
        "itemLabelExtList": draft.get("itemLabelExtList") or [],
        "itemGroupDTO": _resolve_group_dto(draft),
        "userRightsProtocols": _resolve_protocols(draft),
        "defaultPrice": default_price,
    }

    if not confirm:
        return {
            "item_id": str(item_id),
            "ok": True,
            "dry_run": True,
            "title": new_title,
            "description": new_desc,
            "price": price_yuan,
            "image_count": len(image_list),
            "category": cat.get("catName"),
            "submit_payload": data,
            "message": "dry-run：报文已组装，未提交；加 --confirm 才真正保存",
        }

    with write_operation(session, "item.write"):
        raw = call(
            session,
            api="mtop.idle.pc.idleitem.edit",
            data=data,
            version="1.0",
            spm_cnt="a21ybx.publish.0.0",
        )
    result = raw.get("data") if isinstance(raw, dict) else None
    ret = raw.get("ret") if isinstance(raw, dict) else []
    ok = isinstance(result, dict) and (result.get("itemId") or result.get("success"))
    return {
        "item_id": str(item_id),
        "ok": bool(ok),
        "title": new_title,
        "price": price_yuan,
        "image_count": len(image_list),
        "status": "accepted" if ok else "rejected",
        "ret": ret,
        "raw": result,
    }
