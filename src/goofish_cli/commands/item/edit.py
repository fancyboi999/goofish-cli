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

import json
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.mtop import call
from goofish_cli.core.write_operation import write_operation
from goofish_cli.commands.media.upload import upload, validate_image_path
from goofish_cli.commands.item.edit_detail import _rich_text_plain


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


def _upload_local(paths: list[str]) -> list[dict[str, Any]]:
    receipts = []
    for index, path in enumerate(paths):
        receipt = upload(path)
        receipts.append(_receipt(receipt["url"], receipt["width"], receipt["height"], index == 0))
    return receipts


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
    existing_plain = _rich_text_plain(text.get("richTextDesc"))
    paragraphs = [p for p in existing_plain.split("\n") if p]
    existing_title = (text.get("title") or "").strip()
    existing_desc = (text.get("desc") or "").strip()
    if not existing_title and paragraphs:
        existing_title = paragraphs[0]
    if not existing_desc:
        existing_desc = "\n".join(paragraphs[1:]) if len(paragraphs) > 1 else existing_plain

    new_title = (title or "").strip() or existing_title
    new_desc = (desc or "").strip() or existing_desc
    if not new_title or not new_desc:
        raise GoofishError("标题和描述不能为空")

    price_dto = dict(draft.get("itemPriceDTO") or {})
    if price is not None:
        price_dto["priceInCent"] = _cents(price)
    price_yuan = None
    if price_dto.get("priceInCent"):
        try:
            price_yuan = f"{int(price_dto['priceInCent']) / 100:.2f}"
        except (TypeError, ValueError):
            price_yuan = None

    # 2. 图片：替换 / 追加 / 沿用草稿
    # dry-run 阶段只校验本地路径并占位，不实际上传；上传放到 --confirm 提交前。
    local_paths = images or add_images or []
    for path in local_paths:
        validate_image_path(path)

    if not confirm:
        existing = [] if images else _draft_images(draft)
        image_list = existing + [{"pending_upload": p} for p in local_paths]
    elif images:
        image_list = _upload_local(images)
    elif add_images:
        image_list = _draft_images(draft) + _upload_local(add_images)
    else:
        image_list = _draft_images(draft)
    if not 1 <= len(image_list) <= 9:
        raise GoofishError("商品必须有 1–9 张图片")

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
        "itemGroupDTO": {"groupId": ""},
        "userRightsProtocols": [{"enable": False, "serviceCode": "SKILL_PLAY_NO_MIND"}],
        "defaultPrice": draft.get("defaultPrice", False),
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
