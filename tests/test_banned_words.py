"""违禁词门禁单测：大小写不敏感、去空白防拆词、guard 抛错、用户追加词。"""

import pytest

from goofish_cli.core.banned_words import (
    BANNED_WORDS,
    check_banned_words,
    guard,
)
from goofish_cli.core.errors import GoofishError


def test_clean_text_no_hit():
    assert check_banned_words(["机械键盘", "手感好，办公游戏两用"]) == []


def test_exact_banned_hit():
    hits = check_banned_words(["新品", "内含 ChatGPT 提示词"])
    assert "ChatGPT" in hits


def test_case_insensitive():
    assert "openai" in [h.lower() for h in check_banned_words(["openai 教程"])]
    assert "gpt" in [h.lower() for h in check_banned_words(["CHATGPT"])]


def test_squashed_anti_split():
    """去空白后命中，防 'Chat GPT' 拆词绕过。"""
    assert "ChatGPT" in check_banned_words(["Chat GPT 提示词大全"])
    assert "VPN" in check_banned_words(["v p n 科学上网工具"])


def test_offsite_and_hyperbole():
    assert "微信" in check_banned_words(["加微信发资料"])
    assert "最强" in check_banned_words(["全网最强"])


def test_extra_user_words():
    assert "小怪兽" in check_banned_words(["小怪兽周边"], extra=["小怪兽"])


def test_empty_text_returns_empty():
    assert check_banned_words(["", "   "]) == []


def test_guard_raises_on_hit():
    with pytest.raises(GoofishError, match="违禁词"):
        guard(["包过保过", "稳赚不赔"])


def test_guard_passes_clean():
    assert guard(["正常标题", "正常描述"]) == []


def test_builtin_dict_nonempty_and_grouped():
    assert len(BANNED_WORDS) >= 60
