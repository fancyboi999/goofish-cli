"""auth login 命令的参数组合与报错语义。"""
from __future__ import annotations

import json

import pytest

from goofish_cli.commands.auth import login as login_mod
from goofish_cli.core import session as session_mod


@pytest.fixture
def fake_target(tmp_path, monkeypatch):
    """把写盘目标指到 tmp_path，避免踩到用户真实 ~/.goofish-cli/cookies.json。"""
    target = tmp_path / "cookies.json"
    monkeypatch.setattr(login_mod, "DEFAULT_COOKIE_PATH", target)
    monkeypatch.setattr(session_mod, "DEFAULT_COOKIE_PATH", target)
    monkeypatch.setattr(session_mod, "DEVICE_CACHE_PATH", tmp_path / "device.json")
    return target


def test_raw_without_source_raises(fake_target, monkeypatch):
    """goofish auth login --raw（没传 cookie 字符串）→ 必须报参数错，
    不能静默走浏览器 auto——否则 --raw 标志被吞，用户会困惑为什么没生效。"""
    # bootstrap 被调就失败（证明没走 auto 分支）
    def boom(*_args, **_kwargs):
        raise AssertionError("不该触发浏览器 auto")
    monkeypatch.setattr(login_mod, "_pull_from_browser", boom)

    with pytest.raises(ValueError) as ei:
        login_mod.login(source=None, raw=True)
    assert "--raw" in str(ei.value)


def test_no_args_goes_to_browser_auto(fake_target, monkeypatch):
    """goofish auth login 无参数 → 走浏览器 auto-detect。"""
    fake = {"unb": "U", "_m_h5_tk": "T_xxx_1", "tracknick": "n"}
    monkeypatch.setattr(login_mod, "_pull_from_browser", lambda b: (fake, f"browser:{b}"))

    out = login_mod.login()
    assert out["source"] == "browser:auto"
    assert out["unb"] == "U"
    assert fake_target.exists()


def test_raw_with_source_parses(fake_target, monkeypatch):
    """--raw 有 cookie 字符串 → 正确解析，不走浏览器。"""
    def boom(*_args, **_kwargs):
        raise AssertionError("不该触发浏览器 auto")
    monkeypatch.setattr(login_mod, "_pull_from_browser", boom)

    out = login_mod.login(
        source="unb=U; _m_h5_tk=T_x_1; tracknick=n",
        raw=True,
    )
    assert out["source"] == "raw"
    assert out["unb"] == "U"


def test_file_path_import(fake_target, tmp_path, monkeypatch):
    """位置参数 <path> → 从 JSON 文件导入。"""
    src = tmp_path / "src.json"
    src.write_text(json.dumps([
        {"name": "unb", "value": "U"},
        {"name": "_m_h5_tk", "value": "T_x_1"},
    ]))

    def boom(*_args, **_kwargs):
        raise AssertionError("不该触发浏览器 auto")
    monkeypatch.setattr(login_mod, "_pull_from_browser", boom)

    out = login_mod.login(source=str(src))
    assert out["source"].startswith("file:")
    assert out["unb"] == "U"
