"""验证类目推荐的新旧响应结构兼容与空类目保护。"""

import importlib
from unittest.mock import patch

import pytest

from goofish_cli.core.errors import GoofishError

category_module = importlib.import_module("goofish_cli.commands.category.recommend")


def test_extracts_legacy_category_predict_result():
    category = category_module._extract_category({
        "data": {
            "categoryPredictResult": {
                "catId": "1",
                "catName": "示例类目",
                "channelCatId": "2",
                "tbCatId": "3",
                "confidence": 0.9,
            }
        }
    })

    assert category["cat_id"] == "1"
    assert category["channel_cat_id"] == "2"
    assert category["tb_cat_id"] == "3"


def test_extracts_selected_category_and_channel_path_from_card_list():
    category = category_module._extract_category({
        "data": {
            "categoryPredictResult": {"sugShow": "1"},
            "cardList": [{
                "cardData": {
                    "propertyId": "-10000",
                    "propertyName": "分类",
                    "valuesList": [{
                        "catId": "50023914",
                        "catName": "视频工具/服务",
                        "channelCat1Id": "201450801",
                        "channelCat2Id": "202160517",
                        "channelCat3Id": "202147745",
                        "channelCatId": "202158122",
                        "tbCatId": None,
                        "score": 0.99,
                        "isClicked": "1",
                    }],
                }
            }],
        }
    })

    assert category["cat_id"] == "50023914"
    assert category["channel_cat_id"] == "202158122"
    assert category["root_channel_cat_id"] == "201450801"
    assert category["level2_channel_cat_id"] == "202160517"
    assert category["level3_channel_cat_id"] == "202147745"


def test_recommend_rejects_empty_category_before_publish():
    with (
        patch.object(category_module.Session, "load", return_value=object()),
        patch.object(
            category_module,
            "call",
            return_value={"ret": ["SUCCESS::调用成功"], "data": {"categoryPredictResult": {}}},
        ),
        pytest.raises(GoofishError, match="未返回可发布的完整类目"),
    ):
        category_module.recommend("示例标题")
