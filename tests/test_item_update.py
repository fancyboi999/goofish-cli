"""验证 item update —— 元→分换算、dry-run 不发请求、只改价格时其它字段不变。"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from goofish_cli.commands.item import update as update_mod
from goofish_cli.commands.item.update import _build_edit_payload, update
from goofish_cli.core.errors import GoofishError

DETAIL = {
    "itemId": "1104168284060",
    "itemStatus": "0",
    "quantity": "1",
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
    assert "new_price" not in result and "priceInCent" not in result
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


def test_images_validation(tmp_path):
    bad = tmp_path / "not_image.txt"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(GoofishError, match="格式"):
        update("1104168284060", images=[str(bad)])  # 存在但非图片扩展名
    with pytest.raises(GoofishError, match="不存在"):
        update("1104168284060", images=[str(tmp_path / "no_such_x.png")])


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
    # 派生字段同步：desc 无标题前缀（separate 场景），只改标题时 desc 不动
    assert payload["itemTextDTO"]["desc"] == DETAIL["itemTextDTO"]["desc"]
    # 只改标题：价格、图片、类目、地址逐字节保持
    assert payload["itemPriceDTO"] == DETAIL["itemPriceDTO"]
    assert payload["imageInfoDOList"] == DETAIL["imageInfoDOList"]
    assert payload["itemCatDTO"] == DETAIL["itemCatDTO"]
    assert payload["itemAddrDTO"] == DETAIL["itemAddrDTO"]
    assert result["changed"]["title"] == {"old": "Python代做", "new": "新标题"}
    assert "price" not in result["changed"]


def test_build_edit_payload_with_all_fields():
    detail = json.loads(json.dumps(DETAIL))
    detail["itemTextDTO"]["titleDescSeparate"] = "true"
    receipts = [{"url": "https://cdn/n.png", "width": 1, "height": 1}]
    payload = _build_edit_payload(
        detail,
        item_id="1104168284060",
        price_cents="5900",
        title="T",
        desc="D",
        image_receipts=receipts,
    )
    assert payload["itemTextDTO"]["title"] == "T"
    assert payload["itemTextDTO"]["desc"] == "D"  # separate 场景：desc 不加标题前缀
    assert payload["itemTextDTO"]["richTextDesc"] is None  # 无 richTextDesc 时不动
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


def test_sync_item_text_rebuilds_derived_fields():
    rtd_orig = '{"children":[{"type":"Element","children":[{"type":"Text","text":"旧标题","properties":{}}],"properties":{}},{"type":"Element","children":[{"type":"Image","properties":{"url":"https://cdn/i.png"}},{"type":"Text","text":"第一行","properties":{}}],"properties":{}}],"version":"1.0","properties":{}}'
    text_dto = {
        "title": "旧标题",
        "desc": "旧标题\n第一行",
        "wlDescription": "旧标题旧标题\n第一行",
        "titleDescSeparate": "false",
        "richTextDesc": rtd_orig,
    }
    out = update_mod._sync_item_text(text_dto, title="新标题", desc=None)
    assert out["title"] == "新标题"
    assert out["desc"] == "新标题\n第一行"
    assert out["wlDescription"].startswith("新标题新标题")
    rtd = json.loads(out["richTextDesc"])
    # 顶层键保留：version 不丢、不新增 type: null
    assert rtd["version"] == "1.0"
    assert set(rtd) == set(json.loads(rtd_orig))
    # 图片节点无损
    assert rtd["children"][1]["children"][0]["type"] == "Image"
    assert rtd["children"][1]["children"][0]["properties"]["url"] == "https://cdn/i.png"
    # 文本节点已替换
    assert rtd["children"][0]["children"][0]["text"] == "新标题"
    assert rtd["children"][1]["children"][1]["text"] == "第一行"

    # 只改 desc（desc 不含标题前缀的场景）：标题保持，desc 不加前缀
    out_noprefix = update_mod._sync_item_text(
        {"title": "旧标题", "desc": "纯描述正文"}, title=None, desc="新描述",
    )
    assert out_noprefix["title"] == "旧标题"
    assert out_noprefix["desc"] == "新描述"


def test_sync_item_text_desc_byte_preserved():
    """内嵌标题商品只改标题：正文空行与末尾换行逐字节保留。"""
    text_dto = {
        "title": "旧标题",
        "desc": "旧标题\n\n第一行\n\n\n末行\n",
        "titleDescSeparate": "false",
    }
    out = update_mod._sync_item_text(text_dto, title="新标题", desc=None)
    assert out["desc"] == "新标题\n\n第一行\n\n\n末行\n"


def test_sync_item_text_separate_by_field_not_prefix():
    """分离式商品描述开头恰好重复标题：不得误删该文本（用 titleDescSeparate 判断）。"""
    text_dto = {
        "title": "旧标题",
        "desc": "旧标题重复出现的正文",
        "titleDescSeparate": "true",
    }
    out = update_mod._sync_item_text(text_dto, title="新标题", desc=None)
    assert out["desc"] == "旧标题重复出现的正文"
    assert out["title"] == "新标题"


def test_build_payload_with_title_keeps_desc_derived_consistent():
    # desc 含标题前缀的场景（titleDescSeparate=false）：标题改变时 desc 首行同步
    detail = json.loads(json.dumps(DETAIL))
    detail["itemTextDTO"]["titleDescSeparate"] = "false"
    detail["itemTextDTO"]["desc"] = "Python代做\n长期接单"
    payload = _build_edit_payload(detail, item_id="1104168284060", title="T2")
    assert payload["itemTextDTO"]["title"] == "T2"
    assert payload["itemTextDTO"]["desc"].startswith("T2")
    assert payload["itemTextDTO"]["desc"].endswith("长期接单")


# ---------------- 评审修复：在售闸门 / 图片上传顺序 ----------------


def test_delisted_item_rejected_no_edit_request(monkeypatch):
    """已下架商品（itemStatus=1）直接报错拒绝，不发 edit、不上传图片。"""
    calls = []
    upload_mock = MagicMock(side_effect=AssertionError("非在售商品不得上传图片"))

    def fake_call(session, api, data, **kwargs):
        calls.append(api)
        if api.endswith("editDetail"):
            detail = dict(DETAIL, itemStatus="1", quantity="0")
            return _detail_response(detail)
        return {"ret": ["SUCCESS::ok"], "data": {}}

    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(update_mod, "media_upload", upload_mock)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    with pytest.raises(GoofishError, match="上架"):
        update("1104168284060", price=59)
    # 只允许有 editDetail 读取，不允许有 edit 写请求
    assert all(api.endswith("editDetail") for api in calls)
    upload_mock.assert_not_called()


def test_delisted_item_missing_status_rejected(monkeypatch):
    def fake_call(session, api, data, **kwargs):
        detail = {k: v for k, v in DETAIL.items() if k != "itemStatus"}
        return _detail_response(detail)

    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    with pytest.raises(GoofishError, match="在售"):
        update("1104168284060", price=59)


def test_images_uploaded_after_rate_limit_check(monkeypatch, tmp_path):
    """限流/熔断拒绝时不得白传图片：上传必须发生在 write_operation 检查之后。"""
    from contextlib import contextmanager

    img = tmp_path / "g.png"
    img.write_bytes(b"x")
    uploads = []
    monkeypatch.setenv("GOOFISH_LIMITER_PATH", str(tmp_path / "limiter.json"))
    monkeypatch.setenv("GOOFISH_GUARD_PATH", str(tmp_path / "circuit.json"))

    def fake_upload(path):
        uploads.append(str(path))
        return {"url": "https://cdn/g.png", "width": 1, "height": 1}

    entered = {"ok": False}

    @contextmanager
    def fake_write_operation(session, bucket):
        entered["ok"] = True  # 模拟限流检查已通过
        yield

    def fake_call(session, api, data, **kwargs):
        if api.endswith("editDetail"):
            return _detail_response()
        return {"ret": ["SUCCESS::ok"], "data": {}}

    monkeypatch.setattr(update_mod, "media_upload", fake_upload)
    monkeypatch.setattr(update_mod, "write_operation", fake_write_operation)
    monkeypatch.setattr(update_mod, "call", fake_call)
    monkeypatch.setattr(
        update_mod, "Session", MagicMock(load=MagicMock(return_value=MagicMock(unb="u1")))
    )
    result = update("1104168284060", images=[str(img)])
    assert result["ok"] is True
    assert entered["ok"] and uploads == [str(img)]
