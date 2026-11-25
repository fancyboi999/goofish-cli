"""验证 item update —— 元→分换算、dry-run 不发请求、只改价格时其它字段不变。"""

from pathlib import Path
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
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    result = update("1104168284060", price=59)
    assert result["ok"] is True
    assert result["changed"]["price"] == {"old": 80.0, "new": 59}

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
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    with pytest.raises(GoofishError):
        update("1104168284060", price=59)


def test_lead_item_falls_back_to_lead_edit_api(monkeypatch, tmp_path):
    """PC 链路拒绝线索宝贝时，自动回退到 mtop.idle.idleitem.edit 通用链路。"""
    monkeypatch.setenv("GOOFISH_LIMITER_PATH", str(tmp_path / "limiter.json"))
    monkeypatch.setenv("GOOFISH_GUARD_PATH", str(tmp_path / "circuit.json"))
    calls = []

    def fake_call(session, api, data, **kwargs):
        calls.append(api)
        if api.endswith("editDetail"):
            return _detail_response()
        if api == update_mod._EDIT_API:
            # 真实 mtop.call 对失败 ret 是抛异常而非返回值
            raise GoofishError(
                "[mtop.idle.pc.idleitem.edit] 调用失败："
                "FAIL_BIZ_LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH::线索宝贝类目，禁止当前链路编辑"
            )
        return {"ret": ["SUCCESS::调用成功"], "data": {}}

    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    result = update("1104168284060", price=59)
    assert update_mod._LEAD_EDIT_API in calls
    assert calls.index(update_mod._LEAD_EDIT_API) == len(calls) - 1
    assert result["ok"] is True


def test_lead_item_both_paths_rejected(monkeypatch, tmp_path):
    """两条链路都拒绝时，保留原始错误不掩盖。"""
    monkeypatch.setenv("GOOFISH_LIMITER_PATH", str(tmp_path / "limiter.json"))
    monkeypatch.setenv("GOOFISH_GUARD_PATH", str(tmp_path / "circuit.json"))

    def fake_call(session, api, data, **kwargs):
        if api.endswith("editDetail"):
            return _detail_response()
        return {
            "ret": [
                "FAIL_BIZ_LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH::线索宝贝类目，"
                "禁止当前链路编辑，请通过我发布列表-编辑进入发布器进行编辑"
            ]
        }

    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    with pytest.raises(GoofishError, match="线索宝贝"):
        update("1104168284060", price=59)


# ---------------- item update 扩展字段：title / desc / images ----------------


def test_title_too_long_rejected():
    with pytest.raises(GoofishError, match="30"):
        update("1104168284060", title="字" * 31)


def test_desc_too_long_rejected():
    with pytest.raises(GoofishError, match="1500"):
        update("1104168284060", desc="字" * 1501)


def test_desc_and_desc_file_mutually_exclusive(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("描述", encoding="utf-8")
    with pytest.raises(GoofishError, match="二选一"):
        update("1104168284060", desc="a", desc_file=str(f))


def test_desc_file_content_used(tmp_path):
    # _resolve_desc 校验在请求前完成，读文件取内容
    f = tmp_path / "d.txt"
    f.write_text("文件描述", encoding="utf-8")
    assert update_mod._resolve_desc(None, str(f)) == "文件描述"


def test_no_field_given_rejected():
    with pytest.raises(GoofishError, match="至少提供"):
        update("1104168284060")


def test_images_validation():
    with pytest.raises(GoofishError, match="格式"):
        update("1104168284060", images=["/etc/hostname"])  # 存在但非图片扩展名
    with pytest.raises(GoofishError, match="不存在"):
        update("1104168284060", images=["/no/such/x.png"])


def test_images_order_and_first_is_major(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOFISH_LIMITER_PATH", str(tmp_path / "limiter.json"))
    monkeypatch.setenv("GOOFISH_GUARD_PATH", str(tmp_path / "circuit.json"))
    img1 = tmp_path / "a.png"
    img1.write_bytes(b"x")
    img2 = tmp_path / "b.jpg"
    img2.write_bytes(b"y")
    uploads = []

    def fake_upload(path):
        uploads.append(str(path))
        return {"url": f"https://cdn/{Path(path).name}", "width": 10, "height": 20}

    calls = []

    def fake_call(session, api, data, **kwargs):
        calls.append((api, data))
        if api.endswith("editDetail"):
            return _detail_response()
        return {"ret": ["SUCCESS::ok"], "data": {}}

    monkeypatch.setattr(update_mod, "media_upload", fake_upload)
    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    result = update("1104168284060", images=[str(img1), str(img2)])
    assert result["ok"] is True
    # 上传顺序 = 传入顺序
    assert uploads == [str(img1), str(img2)]
    payload = calls[1][1]
    images = payload["imageInfoDOList"]
    assert [i["url"] for i in images] == ["https://cdn/a.png", "https://cdn/b.jpg"]
    # 第一个 = 首图
    assert images[0]["major"] is True and images[1]["major"] is False
    # 其他字段保持原值
    assert payload["itemTextDTO"] == DETAIL["itemTextDTO"]
    assert payload["itemPriceDTO"] == DETAIL["itemPriceDTO"]
    assert result["changed"]["images"]["new"] == ["https://cdn/a.png", "https://cdn/b.jpg"]


def test_title_only_change_keeps_others(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOFISH_LIMITER_PATH", str(tmp_path / "limiter.json"))
    monkeypatch.setenv("GOOFISH_GUARD_PATH", str(tmp_path / "circuit.json"))
    calls = []

    def fake_call(session, api, data, **kwargs):
        calls.append((api, data))
        if api.endswith("editDetail"):
            return _detail_response()
        return {"ret": ["SUCCESS::ok"], "data": {}}

    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    result = update("1104168284060", title="新标题")
    assert result["ok"] is True
    payload = calls[1][1]
    assert payload["itemTextDTO"]["title"] == "新标题"
    assert payload["itemTextDTO"]["desc"] == DETAIL["itemTextDTO"]["desc"]
    # 只改标题：价格、图片、类目、地址逐字节保持
    assert payload["itemPriceDTO"] == DETAIL["itemPriceDTO"]
    assert payload["imageInfoDOList"] == DETAIL["imageInfoDOList"]
    assert payload["itemCatDTO"] == DETAIL["itemCatDTO"]
    assert payload["itemAddrDTO"] == DETAIL["itemAddrDTO"]
    assert result["changed"]["title"] == {"old": "Python代做", "new": "新标题"}
    assert "price" not in result["changed"]


def test_build_edit_payload_with_all_fields():
    receipts = [{"url": "https://cdn/n.png", "width": 1, "height": 1}]
    payload = _build_edit_payload(
        DETAIL,
        item_id="1104168284060",
        price_cents="5900",
        title="T",
        desc="D",
        image_receipts=receipts,
    )
    assert payload["itemTextDTO"] == {"title": "T", "desc": "D"}
    assert payload["itemPriceDTO"]["priceInCent"] == "5900"
    assert payload["imageInfoDOList"][0]["major"] is True
    assert payload["itemCatDTO"] == DETAIL["itemCatDTO"]


def test_dry_run_covers_all_fields_no_request(monkeypatch, tmp_path):
    img = tmp_path / "v3.png"
    img.write_bytes(b"x")
    call_mock = MagicMock(side_effect=AssertionError("dry-run 不得发起任何请求"))
    load_mock = MagicMock(side_effect=AssertionError("dry-run 不得加载 session"))
    upload_mock = MagicMock(side_effect=AssertionError("dry-run 不得上传图片"))
    monkeypatch.setattr(update_mod, "call", call_mock)
    monkeypatch.setattr(update_mod, "media_upload", upload_mock)
    monkeypatch.setattr(update_mod, "Session", MagicMock(load=load_mock))
    result = update("1104168284060", price=59, title="T", desc="D", images=[str(img)], dry_run=True)
    wo = result["would_overwrite"]
    assert wo["itemTextDTO"] == {"title": "T", "desc": "D"}
    assert wo["itemPriceDTO"]["priceInCent"] == "5900"
    assert wo["imageInfoDOList"] == [{"source": str(img)}]
    assert result["ok"] is None
    call_mock.assert_not_called()
    load_mock.assert_not_called()
    upload_mock.assert_not_called()


def test_price_cent_conversion_unchanged_for_extended_fields(tmp_path, monkeypatch):
    """扩展字段加入后，元→分换算仍精确（80.01 → 8001）。"""
    monkeypatch.setenv("GOOFISH_LIMITER_PATH", str(tmp_path / "limiter.json"))
    monkeypatch.setenv("GOOFISH_GUARD_PATH", str(tmp_path / "circuit.json"))
    calls = []

    def fake_call(session, api, data, **kwargs):
        calls.append((api, data))
        if api.endswith("editDetail"):
            return _detail_response()
        return {"ret": ["SUCCESS::ok"], "data": {}}

    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    update("1104168284060", price=80.01, title="T")
    assert calls[1][1]["itemPriceDTO"]["priceInCent"] == "8001"
