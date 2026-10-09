"""商品业务 DTO 适配；埋点字段和默认价格标志不作为商品数据。"""
from __future__ import annotations

from typing import Any

from goofish_cli.core.errors import GoofishError


def normalize_item(raw: dict[str, Any], requested_id: str) -> dict[str, Any]:
    data = raw.get("data") or {}
    item = data.get("itemDO") or {}
    seller = data.get("sellerDO") or {}
    if not isinstance(item, dict) or not item.get("itemId"):
        raise GoofishError("商品响应缺少 itemDO/itemId，不能确认详情")
    item_id = str(item["itemId"])
    if item_id != str(requested_id):
        raise GoofishError("商品响应身份与请求不一致")
    labels = item.get("itemLabelExtList") or []
    properties = {str(label.get("propertyText")): label.get("text")
                  for label in labels if isinstance(label, dict) and label.get("propertyText")}
    amount = item.get("soldPrice")
    if isinstance(amount, bool):
        amount = None
    return {
        "item_id": item_id,
        "title": item.get("title"),
        "description": item.get("desc"),
        "price": str(amount) if amount is not None and amount != "" else None,
        "price_kind": "negotiable" if item.get("defaultPrice") is True else "fixed",
        "original_price": item.get("originalPrice"),
        "status": item.get("itemStatusStr"),
        "status_code": item.get("itemStatus"),
        "condition": properties.get("成色"),
        "brand": properties.get("品牌"),
        "category": properties.get("分类"),
        "seller_nick": seller.get("nick") or seller.get("uniqueName"),
        "seller_id": str(seller["sellerId"]) if seller.get("sellerId") is not None else None,
        "location": seller.get("publishCity") or seller.get("city"),
        "raw": raw,
    }
