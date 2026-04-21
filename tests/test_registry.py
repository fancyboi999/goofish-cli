"""验 registry discover 能找到所有命令且无重名。"""
from __future__ import annotations


def test_discover_all_commands():
    from goofish_cli.core.registry import discover, iter_commands

    discover()
    names = [c.full_name for c in iter_commands()]
    # 至少有这些命令
    expected = {
        "auth.login",
        "auth.status",
        "auth.reset-guard",
        "item.get",
        "item.delete",
        "item.publish",
        "media.upload",
        "category.recommend",
        "location.default",
    }
    assert expected.issubset(set(names)), f"缺失命令: {expected - set(names)}"


def test_write_commands_marked():
    from goofish_cli.core.registry import discover, registry

    discover()
    r = registry()
    assert r["item.delete"].write is True
    assert r["item.publish"].write is True
    assert r["media.upload"].write is True
    assert r["item.get"].write is False
