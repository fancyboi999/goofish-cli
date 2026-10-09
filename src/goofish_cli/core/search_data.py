"""浏览器实际搜索响应的语义适配，保留标签，未知属性不按位置猜。"""
from __future__ import annotations

import re
from typing import Any


def _price(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    return text if re.fullmatch(r"(?:¥|￥)?\s*\d+(?:\.\d{1,2})?", text) else None


def normalize_search(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("data") or {}
    info = data.get("resultInfo") or {}
    control = info.get("searchResControlFields") if isinstance(info, dict) else None
    if not isinstance(control, dict) or not isinstance(data.get("resultList"), list):
        return {"items": [], "schema_unknown": True, "result_kind": "unknown"}
    empty = control.get("hasItems") is False or control.get("srpFeedsItemsDataEmpty") is True or control.get("numFound") == 0
    if not empty and control.get("hasItems") is not True:
        return {"items": [], "schema_unknown": True, "result_kind": "unknown"}
    kind = "empty" if empty else "related_search" if control.get("similar") is True else "search"
    items = []
    for row in data.get("resultList") or []:
        main = (row.get("data") or {}).get("item", {}).get("main", {})
        ex = main.get("exContent") or {}
        if not ex.get("itemId") or not ex.get("title"):
            continue
        tags = []
        attributes = {}
        original = _price(ex.get("originalPrice"))
        badge = None
        for group, values in (ex.get("fishTags") or {}).items():
            for entry in values.get("tagList") or []:
                td = entry.get("data") or {}
                text = td.get("content")
                if not isinstance(text, str) or td.get("type") == "img":
                    continue
                tags.append({"group": group, "type": td.get("type"), "text": text})
                name = td.get("propertyText") or td.get("propertyName")
                if name:
                    attributes[str(name)] = text
                if td.get("type") in ("strikethroughText", "strikeThroughText", "lineThroughText") or td.get("strikethrough") is True:
                    original = _price(text) or original
                if group == "r4" and badge is None:
                    badge = text
        detail = ex.get("detailParams") or {}
        amount = _price(detail.get("soldPrice"))
        if amount is None:
            parts = ex.get("price") or []
            amount = _price("".join(str(p.get("text") or "") for p in parts
                                    if p.get("type") in ("sign", "integer", "decimal")))
        items.append({
            "item_id": str(ex["itemId"]), "title": ex["title"],
            "url": f"https://www.goofish.com/item?id={ex['itemId']}",
            "price": amount if amount is None or amount.startswith(("¥", "￥")) else "¥" + amount,
            "original_price": original,
            "condition": attributes.get("成色"), "brand": attributes.get("品牌"),
            "attributes": attributes, "labels": tags,
            "location": ex.get("area") or None,
            "seller_nick": ex.get("userNickName") or detail.get("userNick") or None,
            "badge": badge, "extra": " | ".join(t["text"] for t in tags),
            "source": "browser_search_response", "result_kind": kind,
        })
    return {"items": [] if empty else items, "recommendations": items if empty else [], "empty": empty, "result_kind": kind,
            "reported_match_count": control.get("numFound"), "requiresAuth": False, "blocked": False}
