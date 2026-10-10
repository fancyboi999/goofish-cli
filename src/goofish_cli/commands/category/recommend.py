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


def _selected_score(data: dict, predict: dict) -> tuple[float | None, str | None]:
    explicit = predict.get("confidence")
    if isinstance(explicit, (float, int)) and not isinstance(explicit, bool) and math.isfinite(explicit):
        return float(explicit), "categoryPredictResult.confidence"
    values = []
    for card in data.get("cardList") or []:
        body = card.get("cardData") or {}
        if str(body.get("propertyId")) != "-10000":
            continue
        for candidate in body.get("valuesList") or []:
            keys = ("channelCatId", "tbCatId", "catId")
            if all(str(candidate.get(key)) == str(predict[key]) for key in keys if predict.get(key) is not None):
                score = candidate.get("score")
                if isinstance(score, (float, int)) and not isinstance(score, bool) and math.isfinite(score):
                    values.append(float(score))
    return (values[0], "classification_card.score") if len(values) == 1 else (None, None)


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
    predict = (raw.get("data", {}) or {}).get("categoryPredictResult", {}) or {}
    if not predict.get("catId") or not predict.get("channelCatId") or not predict.get("tbCatId"):
        raise GoofishError("类目推荐响应缺少选中分类身份，不能继续自动发布", raw=raw)
    score, source = _selected_score(raw.get("data") or {}, predict)
    return {
        "cat_id": str(predict.get("catId", "")),
        "cat_name": predict.get("catName", ""),
        "channel_cat_id": str(predict.get("channelCatId", "")),
        "tb_cat_id": str(predict.get("tbCatId", "")),
        "confidence": score,
        "confidence_source": source,
        "confidence_kind": "model_score_not_calibrated_probability",
        "unique_code": unique_code,
        "raw": raw,
    }
