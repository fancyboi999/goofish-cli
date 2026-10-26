"""纯函数测 item view 的参数校验 + URL。"""
from __future__ import annotations

import pytest

from goofish_cli.commands.item.view import __test__ as t
from goofish_cli.core.errors import GoofishError


def test_normalize_item_id_accepts_digits():
    f = t["_normalize_item_id"]
    assert f("123456") == "123456"
    assert f(987654321) == "987654321"
    assert f("  42  ") == "42"


@pytest.mark.parametrize("bad", ["", "abc", "123abc", " ", None, "12 34"])
def test_normalize_item_id_rejects_non_digit(bad):
    with pytest.raises(GoofishError):
        t["_normalize_item_id"](bad)


def test_build_item_url():
    assert t["_build_item_url"]("12345") == "https://www.goofish.com/item?id=12345"


def test_is_navigation_race_matches_playwright_context_destroyed():
    f = t["_is_navigation_race"]
    assert f(RuntimeError(
        "Page.evaluate: Execution context was destroyed, most likely because of a navigation"
    ))
    assert f(RuntimeError("Cannot find context with specified id"))
    assert not f(RuntimeError("net::ERR_TIMED_OUT"))
    assert not f(RuntimeError("mtop 调用失败 [FAIL_BIZ_ITEM_NOT_FOUND]"))
