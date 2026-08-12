"""category recommend — AI 识别商品类目（发布前置）。

接口：mtop.taobao.idle.kgraph.property.recommend v2.0
"""

import json
from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.mtop import call


@command(
    namespace="category",
    name="recommend",
    description="AI 识别商品类目，输入标题+图片返回 catId/catName",
    strategy=Strategy.COOKIE,
    columns=["cat_id", "cat_name", "channel_cat_id", "tb_cat_id", "confidence"],
)
def recommend(
    title: str,
    images_json: str = "[]",
) -> dict[str, Any]:
    """images_json 是 JSON 字符串：[{"url":"...","width":1024,"height":1024}, ...]"""
    session = Session.load()
    images = json.loads(images_json) if images_json else []
    image_infos: list[dict[str, Any]] = []
    for img in images:
        image_infos.append({
            "extraInfo": {"isH": "false", "isT": "false", "raw": "false"},
            "isQrCode": False,
            "url": img["url"],
            "heightSize": img["height"],
            "widthSize": img["width"],
            "major": True,
            "type": 0,
            "status": "done",
        })

    raw = call(
        session,
        api="mtop.taobao.idle.kgraph.property.recommend",
        data={
            "title": title,
            "lockCpv": False,
            "multiSKU": False,
            "publishScene": "mainPublish",
            "scene": "newPublishChoice",
            "description": title,
            "imageInfos": image_infos,
            "uniqueCode": "1775905618164677",
        },
        version="2.0",
        spm_cnt="a21ybx.publish.0.0",
    )
    category = _extract_category(raw)
    if not category["cat_id"] or not category["cat_name"] or not category["channel_cat_id"]:
        raise GoofishError(
            "类目推荐接口未返回可发布的完整类目，已停止发布",
            raw=raw,
            hint="请重新获取类目推荐；不要用空类目字段调用发布接口",
        )
    category["raw"] = raw
    return category


def _extract_category(raw: dict[str, Any]) -> dict[str, Any]:
    """兼容旧 categoryPredictResult 与新版 cardList 返回结构。"""
    data = raw.get("data", {}) or {}
    predict = data.get("categoryPredictResult", {}) or {}
    if predict.get("catId") and predict.get("channelCatId"):
        return _normalize_category(predict)

    candidates: list[dict[str, Any]] = []
    for card in data.get("cardList", []) or []:
        card_data = card.get("cardData", {}) or {}
        if (
            str(card_data.get("propertyId", "")) != "-10000"
            and card_data.get("propertyName") != "分类"
        ):
            continue
        candidates.extend(card_data.get("valuesList", []) or [])

    selected = next(
        (item for item in candidates if str(item.get("isClicked", "")) == "1"),
        None,
    )
    if selected is None and candidates:
        selected = max(candidates, key=lambda item: float(item.get("score") or 0))
    return _normalize_category(selected or {})


def _normalize_category(category: dict[str, Any]) -> dict[str, Any]:
    transport = category.get("transportData", {}) or {}
    return {
        "cat_id": str(category.get("catId") or ""),
        "cat_name": (
            category.get("catName")
            or category.get("channelCatName")
            or category.get("valueName")
            or ""
        ),
        "channel_cat_id": str(
            category.get("channelCatId") or transport.get("channelCateId") or ""
        ),
        "tb_cat_id": str(category.get("tbCatId") or transport.get("tbCatId") or ""),
        "root_channel_cat_id": str(category.get("channelCat1Id") or ""),
        "level2_channel_cat_id": str(category.get("channelCat2Id") or ""),
        "level3_channel_cat_id": str(category.get("channelCat3Id") or ""),
        "confidence": category.get("confidence", category.get("score", 0)),
    }
