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
