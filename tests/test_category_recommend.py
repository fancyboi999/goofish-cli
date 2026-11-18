"""category recommend 选中类目身份的解析（离线，mock mtop）。"""

import pytest

from goofish_cli.commands.category import recommend as rec_mod
from goofish_cli.core.errors import GoofishError


def _card(values: list[dict]) -> dict:
    return {"cardType": "20401", "cardData": {"propertyId": "-10000", "valuesList": values}}


# 结构取自真实响应：虚拟类目时 categoryPredictResult 不带类目字段，候选的 tbCatId 为 null。
VIRTUAL = {
    "categoryPredictResult": {"sugShow": "1"},
    "cardList": [_card([
        {"catName": "电子资料", "catId": "50023914", "channelCatId": "202036301",
         "tbCatId": None, "score": 0.92, "isClicked": "1"},
        {"catName": "其他服务", "catId": None, "channelCatId": "202297103",
         "tbCatId": None, "score": 0.04, "isClicked": "0"},
    ])],
}
PHYSICAL = {
    "categoryPredictResult": {"catId": 50025387, "catName": "键盘", "channelCatId": 126856263,
                              "tbCatId": 110210, "sugShow": "1"},
    "cardList": [_card([
        {"catName": "键盘", "catId": "50025387", "channelCatId": "126856263",
         "tbCatId": "110210", "score": 0.97, "isClicked": "1"},
        {"catName": "键鼠套装", "catId": "50025387", "channelCatId": "126856264",
         "tbCatId": "50002415", "score": 0.01, "isClicked": "0"},
    ])],
}


@pytest.fixture
def respond(monkeypatch):
    def install(data: dict):
        monkeypatch.setattr(rec_mod.Session, "load", staticmethod(lambda: object()))
        monkeypatch.setattr(rec_mod, "call", lambda *a, **k: {"data": data})
    return install


def test_virtual_category_uses_clicked_candidate_with_empty_tb_cat_id(respond):
    respond(VIRTUAL)
    out = rec_mod.recommend("PDF电子资料")
    assert (out["cat_id"], out["cat_name"], out["channel_cat_id"], out["tb_cat_id"]) == (
        "50023914", "电子资料", "202036301", "")
    assert out["confidence"] == 0.92
    assert out["confidence_source"] == "classification_card.score"


def test_physical_category_keeps_tb_cat_id(respond):
    respond(PHYSICAL)
    out = rec_mod.recommend("机械键盘")
    assert (out["cat_id"], out["channel_cat_id"], out["tb_cat_id"]) == ("50025387", "126856263", "110210")
    assert out["confidence"] == 0.97


def test_clicked_candidate_wins_over_predict_result(respond):
    data = {**PHYSICAL, "cardList": [_card([
        {**PHYSICAL["cardList"][0]["cardData"]["valuesList"][0], "isClicked": "0"},
        {**PHYSICAL["cardList"][0]["cardData"]["valuesList"][1], "isClicked": "1"},
    ])]}
    respond(data)
    out = rec_mod.recommend("键鼠")
    assert (out["cat_name"], out["channel_cat_id"], out["tb_cat_id"]) == ("键鼠套装", "126856264", "50002415")


def test_falls_back_to_predict_result_without_clicked_candidate(respond):
    respond({**PHYSICAL, "cardList": []})
    out = rec_mod.recommend("机械键盘")
    assert (out["cat_id"], out["tb_cat_id"]) == ("50025387", "110210")
    assert out["confidence"] is None


def test_explicit_confidence_preferred(respond):
    data = {**PHYSICAL, "categoryPredictResult": {**PHYSICAL["categoryPredictResult"], "confidence": 0.5}}
    respond(data)
    out = rec_mod.recommend("机械键盘")
    assert (out["confidence"], out["confidence_source"]) == (0.5, "categoryPredictResult.confidence")


@pytest.mark.parametrize("missing", ["catId", "catName", "channelCatId"])
def test_missing_required_identity_raises(respond, missing):
    value = {**VIRTUAL["cardList"][0]["cardData"]["valuesList"][0], missing: None}
    respond({"categoryPredictResult": {"sugShow": "1"}, "cardList": [_card([value])]})
    with pytest.raises(GoofishError, match="缺少选中分类身份"):
        rec_mod.recommend("PDF电子资料")


def test_no_category_at_all_raises(respond):
    respond({"categoryPredictResult": {}, "cardList": []})
    with pytest.raises(GoofishError, match="缺少选中分类身份"):
        rec_mod.recommend("x")
