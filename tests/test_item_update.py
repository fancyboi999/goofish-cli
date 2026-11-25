"""验证 item update —— 元→分换算、dry-run 不发请求、只改价格时其它字段不变。"""

from unittest.mock import MagicMock

import pytest

from goofish_cli.commands.item import update as update_mod
from goofish_cli.commands.item.update import _build_edit_payload, update
from goofish_cli.core.errors import GoofishError

DETAIL = {
    "itemId": "1104168284060",
    "itemStatus": "1",
    "simpleItem": "true",
    "itemTextDTO": {"title": "Python代做", "desc": "长期接单"},
    "itemPriceDTO": {"priceInCent": "8000", "origPriceInCent": "0"},
    "itemPostFeeDTO": {"templateId": "0"},
    "itemCatDTO": {"catId": "1", "catName": "服务", "channelCatId": "2"},
    "itemAddrDTO": {"prov": "北京", "city": "北京"},
    "imageInfoDOList": [{"url": "https://cdn/x.png", "major": True}],
    "canBargain": "true",
}


def _detail_response(detail=DETAIL):
    return {"ret": ["SUCCESS::调用成功"], "data": dict(detail)}


def test_money_yuan_to_cent():
    assert update_mod._money(59) == "5900"
    assert update_mod._money(59.5) == "5950"
    assert update_mod._money(80.01) == "8001"
    with pytest.raises(GoofishError):
        update_mod._money(59.999)


def test_price_must_be_positive():
    with pytest.raises(GoofishError):
        update("1104168284060", price=0)
    with pytest.raises(GoofishError):
        update("1104168284060", price=-3)


def test_dry_run_sends_no_request(monkeypatch):
    call_mock = MagicMock(side_effect=AssertionError("dry-run 不得发起任何请求"))
    load_mock = MagicMock(side_effect=AssertionError("dry-run 不得加载 session"))
    monkeypatch.setattr(update_mod, "call", call_mock)
    monkeypatch.setattr(update_mod, "Session", MagicMock(load=load_mock))
    result = update("1104168284060", price=59, dry_run=True)
    assert result["dry_run"] is True
    assert result["priceInCent"] == "5900"
    assert result["would_overwrite"]["itemPriceDTO"]["priceInCent"] == "5900"
    call_mock.assert_not_called()
    load_mock.assert_not_called()


def test_only_price_changes_other_fields_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOFISH_LIMITER_PATH", str(tmp_path / "limiter.json"))
    monkeypatch.setenv("GOOFISH_GUARD_PATH", str(tmp_path / "circuit.json"))
    calls = []

    def fake_call(session, api, data, **kwargs):
        calls.append((api, data))
        if api.endswith("editDetail"):
            return _detail_response()
        return {"ret": ["SUCCESS::ok"], "data": {"itemId": data["itemId"]}}

    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1"))))
    result = update("1104168284060", price=59)
    assert result["ok"] is True
    assert result["old_price"] == 80.0
    assert result["new_price"] == 59

    assert len(calls) == 2
    detail_api, edit_api = calls[0][0], calls[1][0]
    assert detail_api == "mtop.idle.pc.idleitem.editDetail"
    assert edit_api == "mtop.idle.pc.idleitem.edit"

    payload = calls[1][1]
    # 请求体里的 priceInCent 必须是换算后的分
    assert payload["itemPriceDTO"]["priceInCent"] == "5900"
    # 其它字段与 editDetail 原值一致
    for key in ("itemTextDTO", "itemPostFeeDTO", "itemCatDTO", "itemAddrDTO", "imageInfoDOList"):
        assert payload[key] == DETAIL[key]
    assert payload["itemPriceDTO"]["origPriceInCent"] == "0"
    assert payload["itemId"] == "1104168284060"
    assert payload["publishScene"] == "pcMainPublish"


def test_build_edit_payload_preserves_everything_but_price():
    payload = _build_edit_payload(DETAIL, item_id="1104168284060", price_cents="5900")
    for key, value in DETAIL.items():
        if key == "itemPriceDTO":
            continue
        assert payload[key] == value
    assert payload["itemPriceDTO"] == {"priceInCent": "5900", "origPriceInCent": "0"}
    # 深拷贝：不得污染传入的 detail
    assert DETAIL["itemPriceDTO"]["priceInCent"] == "8000"


def test_edit_detail_empty_rejected(monkeypatch):
    monkeypatch.setattr(update_mod, "call", lambda *a, **k: {"ret": ["SUCCESS::ok"], "data": {}})
    monkeypatch.setattr(update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1"))))
    with pytest.raises(GoofishError):
        update("1104168284060", price=59)
