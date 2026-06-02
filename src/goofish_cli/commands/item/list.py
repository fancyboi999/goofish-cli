"""item list — 查看当前账号的在售商品。

调 mtop.idle.web.xyh.item.list v1.0，返回结构化数据。
"""
from __future__ import annotations

from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.mtop import call

MAX_LIMIT = 100
DEFAULT_PAGE_SIZE = 20
MAX_PAGES = 50  # 翻页硬上限，配合"本页无新增即退出"防止 nextPage 恒真时死循环


def _normalize_limit(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return min(MAX_LIMIT, max(1, n))


STATUS_MAP = {"0": "在售", "1": "已下架"}


def _extract_item(card_data: dict[str, Any]) -> dict[str, Any]:
    """从 cardData 提取商品关键字段。"""
    item_id = str(card_data.get("id", ""))
    title = card_data.get("title", "")
    # priceInfo: {"preText": "¥", "price": "1999"}
    price_info = card_data.get("priceInfo") or {}
    price = (price_info.get("preText") or "") + str(price_info.get("price") or "")
    status_code = str(card_data.get("itemStatus", ""))
    status = STATUS_MAP.get(status_code, status_code)
    # picInfo: {"picUrl": "https://..."}
    pic_info = card_data.get("picInfo") or {}
    image_url = pic_info.get("picUrl", "")
    # itemLabelDataVO 标签：labelData → r3/r2/... → tagList → data.content
    # 只取 type=="text" 的文案标签；type=="img" 的 content 是图标 key
    #（如 freeShippingIcon）而非给人看的文案，跳过。
    labels = []
    label_vo = card_data.get("itemLabelDataVO") or {}
    if isinstance(label_vo, dict):
        label_data = label_vo.get("labelData") or {}
        for _region, region_data in label_data.items():
            for tag in (region_data.get("tagList") if isinstance(region_data, dict) else []) or []:
                tag_data = tag.get("data") if isinstance(tag, dict) else None
                if not isinstance(tag_data, dict) or tag_data.get("type") == "img":
                    continue
                content = tag_data.get("content")
                if content:
                    labels.append(content)
    return {
        "item_id": item_id,
        "title": title,
        "price": price,
        "status": status,
        "image_url": image_url,
        "tags": labels,
    }


@command(
    namespace="item",
    name="list",
    description="查看当前账号的在售商品（API 直签）",
    strategy=Strategy.COOKIE,
    columns=["rank", "item_id", "title", "price", "status"],
)
def list_items(limit: int = 50) -> dict[str, Any]:
    session = Session.load()
    n = _normalize_limit(limit)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_number = 1

    def _add(card_data: dict[str, Any]) -> None:
        item = _extract_item(card_data)
        if item["item_id"] and item["item_id"] not in seen:
            seen.add(item["item_id"])
            items.append(item)

    while len(items) < n and page_number <= MAX_PAGES:
        raw = call(
            session,
            api="mtop.idle.web.xyh.item.list",
            data={
                "needGroupInfo": True,
                "pageNumber": page_number,
                "userId": session.unb,
                "pageSize": DEFAULT_PAGE_SIZE,
            },
            version="1.0",
            spm_cnt="a21ybx.item.0.0",
        )
        data = raw.get("data", {}) or {}
        before = len(items)

        # 置顶商品（仅首页；可能与 cardList 重复，靠 seen 去重）
        if page_number == 1:
            top = data.get("topItem")
            if isinstance(top, dict) and top:
                _add(top.get("cardData") or top)

        # 普通列表
        for card in data.get("cardList") or []:
            _add(card.get("cardData") or card)

        # 本页没新增任何商品 → 防御性退出，避免 nextPage 恒真时死循环
        if len(items) == before or not data.get("nextPage"):
            break
        page_number += 1

    items = items[:n]

    for i, it in enumerate(items):
        it["rank"] = i + 1

    return {"items": items, "total": len(items)}


__test__ = {
    "_normalize_limit": _normalize_limit,
    "_extract_item": _extract_item,
}
