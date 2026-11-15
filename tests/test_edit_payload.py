"""验证 item edit / edit-detail 的纯逻辑 —— 价格、图片收据、文本解析防回归。"""

import json

import pytest

from goofish_cli.commands.item.edit import (
    _cents,
    _draft_images,
    _mark_single_major,
    _receipt,
    _resolve_default_price,
    _resolve_group_dto,
    _resolve_protocols,
    _resolve_text,
)
from goofish_cli.commands.item.edit_detail import _images, _rich_text_plain
from goofish_cli.core.errors import GoofishError

# --- 价格 ---

def test_cents_yuan_to_fen():
    assert _cents(19.99) == "1999"
    assert _cents(0) == "0"
    assert _cents(1999.0) == "199900"


def test_cents_rejects_negative_and_extra_precision():
    with pytest.raises(GoofishError):
        _cents(-1)
    with pytest.raises(GoofishError):
        _cents(1.234)
    with pytest.raises(GoofishError):
        _cents("not-a-number")  # type: ignore[arg-type]


def test_cents_rejects_nan_and_infinite():
    with pytest.raises(GoofishError):
        _cents(float("nan"))
    with pytest.raises(GoofishError):
        _cents(float("inf"))


# --- 分组 / 服务协议沿用草稿 ---

def test_group_dto_keeps_draft_group():
    draft = {"itemGroupDTO": {"groupId": "880123456", "groupName": "数码配件"}}
    assert _resolve_group_dto(draft) == {"groupId": "880123456", "groupName": "数码配件"}


def test_group_dto_falls_back_when_absent():
    assert _resolve_group_dto({"itemGroupDTO": None}) == {"groupId": ""}
    assert _resolve_group_dto({}) == {"groupId": ""}


def test_protocols_keep_draft_listing():
    draft = {"userRightsProtocols": [
        {"serviceCode": "NONCONFORMITY_FREE_REFUND", "enable": "false"},
        {"serviceCode": "FAST_DELIVERY_24_HOUR", "enable": "true"},
    ]}
    assert _resolve_protocols(draft) == draft["userRightsProtocols"]


def test_protocols_empty_when_absent():
    assert _resolve_protocols({"userRightsProtocols": None}) == []
    assert _resolve_protocols({}) == []


# --- 定价模式（一口价 / 议价）---

def test_default_price_switches_to_fixed_when_price_given():
    # 草稿是议价(defaultPrice=True)，显式给价后必须切到一口价(False)
    assert _resolve_default_price(25.0, {"defaultPrice": True}) is False
    assert _resolve_default_price(9.9, {"defaultPrice": False}) is False


def test_default_price_keeps_draft_mode_when_no_price():
    assert _resolve_default_price(None, {"defaultPrice": True}) is True
    assert _resolve_default_price(None, {"defaultPrice": False}) is False
    # 价格为 0 视为不更新定价，沿用草稿
    assert _resolve_default_price(0, {"defaultPrice": True}) is True


# --- 图片收据 ---

def test_receipt_keeps_dimensions():
    r = _receipt("https://cdn/a.jpg", 1024, 1024, True)
    assert r["widthSize"] == 1024
    assert r["heightSize"] == 1024
    assert r["major"] is True
    assert r["status"] == "done"


def test_receipt_tolerates_missing_dimensions():
    r = _receipt("https://cdn/a.jpg", None, None, False)
    assert "widthSize" not in r
    assert "heightSize" not in r
    assert r["url"] == "https://cdn/a.jpg"


def test_draft_images_skips_invalid_and_marks_major():
    draft = {"imageInfoDOList": [
        {"url": "https://cdn/1.jpg", "widthSize": 800, "heightSize": 600},
        {"url": "https://cdn/2.jpg"},
        {"no_url": True},
    ]}
    receipts = _draft_images(draft)
    assert len(receipts) == 2
    assert receipts[0]["major"] is True
    assert receipts[1]["major"] is False
    assert "heightSize" not in receipts[1]


def test_merge_receipts_keeps_only_one_major():
    # 草稿图和新上传图各标了一张主图，合并后只能保留第一张为主图
    receipts = [
        _receipt("https://cdn/old-1.jpg", 800, 600, True),
        _receipt("https://cdn/old-2.jpg", 800, 600, False),
        _receipt("https://cdn/new-1.jpg", 800, 600, True),
        _receipt("https://cdn/new-2.jpg", 800, 600, False),
    ]
    merged = _mark_single_major(receipts)
    assert [r["major"] for r in merged] == [True, False, False, False]


def test_images_extracts_public_fields():
    imgs = _images([{"url": "https://cdn/a.jpg", "width": 1024, "height": 768, "major": "true"}])
    assert imgs == [{"url": "https://cdn/a.jpg", "width": 1024, "height": 768, "major": True}]


# --- 标题 / 描述解析 ---

def test_resolve_text_prefers_separate_fields():
    title, desc = _resolve_text({"title": "标题", "desc": "描述"}, None, None)
    assert title == "标题"
    assert desc == "描述"


def test_resolve_text_falls_back_to_rich_text():
    rich = json.dumps([{"type": "Text", "text": "标题行"}, {"type": "Text", "text": "描述行"}])
    title, desc = _resolve_text({"richTextDesc": rich}, None, None)
    assert title == "标题行"
    assert desc == "描述行"


def test_resolve_text_override_wins():
    title, desc = _resolve_text({"title": "旧标题", "desc": "旧描述"}, "新标题", None)
    assert title == "新标题"
    assert desc == "旧描述"


def test_resolve_text_raises_when_empty():
    with pytest.raises(GoofishError):
        _resolve_text({}, None, None)


# --- 富文本提取 ---

def test_rich_text_plain_none_is_empty():
    assert _rich_text_plain(None) == ""
    assert _rich_text_plain("") == ""


def test_rich_text_plain_plain_string_passthrough():
    assert _rich_text_plain("普通文本") == "普通文本"


def test_rich_text_plain_nested_elements():
    node = {"children": [{"type": "Text", "text": "第一段"},
                          {"elements": [{"type": "Text", "text": "第二段"}]}]}
    assert _rich_text_plain(node) == "第一段\n第二段"
