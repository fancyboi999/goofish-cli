"""category recommend — AI 识别商品类目（发布前置）。

接口：mtop.taobao.idle.kgraph.property.recommend v2.0
"""

import json
import math
import time
from typing import Any

from goofish_cli.commands.media.upload import validate_image_receipt
from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.mtop import call


def _finite(value: Any) -> float | None:
    if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _clicked_candidate(data: dict) -> dict:
    """分类卡片（propertyId -10000）里被选中的候选。

    网页发布页以它为准，categoryPredictResult 只作兜底；虚拟类目（如「电子资料」）
    的 categoryPredictResult 不带类目字段，选中身份只在候选里。
    """
    for card in data.get("cardList") or []:
        body = card.get("cardData") or {}
        if str(body.get("propertyId")) == "-10000":
            values = body.get("valuesList") or []
            return next((v for v in values if str(v.get("isClicked")) == "1"), {})
    return {}


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
    if not title.strip():
        raise GoofishError("类目推荐标题不能为空")
    try:
        images = json.loads(images_json) if images_json else []
    except ValueError:
        raise GoofishError("images-json 必须是有效 JSON 图片收据数组") from None
    if not isinstance(images, list) or len(images) > 9:
        raise GoofishError("images-json 必须是至多 9 张图片收据的数组")
    images = [validate_image_receipt(value) for value in images]
    session = Session.load()
    unique_code = str(time.time_ns() // 1000)
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
            "uniqueCode": unique_code,
        },
        version="2.0",
        spm_cnt="a21ybx.publish.0.0",
    )
    data = raw.get("data", {}) or {}
    predict = data.get("categoryPredictResult", {}) or {}
    clicked = _clicked_candidate(data)
    selected = {
        key: clicked.get(key) or predict.get(key)
        for key in ("catId", "catName", "channelCatId", "tbCatId")
    }
    # tbCatId 可以为空：虚拟/服务类目没有淘宝类目映射，网页端照常以空值发布。
    if not selected["catId"] or not selected["catName"] or not selected["channelCatId"]:
        raise GoofishError("类目推荐响应缺少选中分类身份，不能继续自动发布", raw=raw)
    explicit = _finite(predict.get("confidence"))
    clicked_score = _finite(clicked.get("score"))
    if explicit is not None:
        score, source = explicit, "categoryPredictResult.confidence"
    elif clicked_score is not None:
        score, source = clicked_score, "classification_card.score"
    else:
        score, source = None, None
    return {
        "cat_id": str(selected["catId"]),
        "cat_name": selected["catName"],
        "channel_cat_id": str(selected["channelCatId"]),
        "tb_cat_id": str(selected["tbCatId"] or ""),
        "confidence": score,
        "confidence_source": source,
        "confidence_kind": "model_score_not_calibrated_probability",
        "unique_code": unique_code,
        "raw": raw,
    }
