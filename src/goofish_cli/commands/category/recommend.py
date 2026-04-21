"""category recommend — AI 识别商品类目（发布前置）。

接口：mtop.taobao.idle.kgraph.property.recommend v2.0
"""

import json
from typing import Any

from goofish_cli.core import Session, Strategy, command
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
    predict = (raw.get("data", {}) or {}).get("categoryPredictResult", {}) or {}
    return {
        "cat_id": str(predict.get("catId", "")),
        "cat_name": predict.get("catName", ""),
        "channel_cat_id": str(predict.get("channelCatId", "")),
        "tb_cat_id": str(predict.get("tbCatId", "")),
        "confidence": predict.get("confidence", 0),
        "raw": raw,
    }
