"""验证 item edit / edit-detail 的纯逻辑 —— 价格、图片收据、文本解析防回归。"""

import json

import pytest

from goofish_cli.commands.item.edit import _cents, _draft_images, _receipt, _resolve_text
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
