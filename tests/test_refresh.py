"""测 refresh 模块。Playwright 走真浏览器不进单测，mock 掉 asyncio.run。"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from goofish_cli.core import refresh
from goofish_cli.core.session import Session


def _make_session(cookies: dict[str, str]) -> Session:
    http = requests.Session()
    http.cookies.update(cookies)
    return Session(http=http, unb=cookies.get("unb", ""), tracknick="", device_id="dev")


def _fake_run(result):
    """模拟 asyncio.run：close 掉传入的 coroutine（避免 unawaited warning）后返回结果。"""
    def _inner(coro):
        coro.close()
        return result
    return _inner


def _fake_run_raises(exc):
    def _inner(coro):
        coro.close()
        raise exc
    return _inner


def test_refresh_merges_new_cookies_and_dedupes_same_name(tmp_path, monkeypatch):
    """关键回归：刷新后不能出现跨 domain 同名 cookie（`.cookies.get(...)` 会抛）。"""
    # 预埋一份旧 _m_h5_tk（默认 domain）
    session = _make_session({"_m_h5_tk": "old_1", "unb": "u1", "cookie2": "c2"})

    # 通过 GOOFISH_COOKIES_PATH 让 resolve_cookie_path 指到测试临时路径
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(tmp_path / "cookies.json"))

    fresh = {"_m_h5_tk": "new_2", "unb": "u1", "cookie2": "c3", "x5sec": "x"}
    with patch.object(refresh, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run(fresh)
        ok = refresh.refresh_cookies_via_browser(session)

    assert ok is True
    # 去重后能正常 get —— 不会抛 "multiple cookies with name"
    assert session.http.cookies.get("_m_h5_tk") == "new_2"
    assert session.http.cookies.get("cookie2") == "c3"
    assert session.http.cookies.get("x5sec") == "x"
    # 磁盘也写了
    assert (tmp_path / "cookies.json").exists()


def test_refresh_fails_when_required_keys_missing(tmp_path, monkeypatch):
    session = _make_session({"_m_h5_tk": "old", "unb": "u1"})
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(tmp_path / "cookies.json"))

    with patch.object(refresh, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run({"foo": "bar"})  # 没 _m_h5_tk / unb
        ok = refresh.refresh_cookies_via_browser(session)

    assert ok is False
    # 不应覆盖旧 session
    assert session.http.cookies.get("_m_h5_tk") == "old"
    # 也不应写盘
    assert not (tmp_path / "cookies.json").exists()


def test_refresh_respects_custom_cookie_path(tmp_path, monkeypatch):
    """GOOFISH_COOKIES_PATH 自定义路径必须被尊重（Copilot review feedback）。"""
    custom = tmp_path / "nested" / "my.json"
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(custom))

    session = _make_session({"_m_h5_tk": "old", "unb": "u1"})
    fresh = {"_m_h5_tk": "new", "unb": "u1", "cookie2": "c"}
    with patch.object(refresh, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run(fresh)
        ok = refresh.refresh_cookies_via_browser(session)

    assert ok is True
    assert custom.exists()
    # 默认路径不应被写
    assert not (tmp_path / "cookies.json").exists()


def test_refresh_fails_when_cookie2_missing(tmp_path, monkeypatch):
    """cookie2 是真正的 session token，缺它必须判失败（v0.2.3 Copilot review）。"""
    session = _make_session({"_m_h5_tk": "old", "unb": "u1", "cookie2": "old_c"})
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(tmp_path / "cookies.json"))

    # fresh 有 _m_h5_tk / unb 但无 cookie2 —— 过去会误判成功，现在必须 False
    fresh = {"_m_h5_tk": "new", "unb": "u1"}
    with patch.object(refresh, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run(fresh)
        ok = refresh.refresh_cookies_via_browser(session)

    assert ok is False
    # 旧 cookie 不能被覆盖
    assert session.http.cookies.get("_m_h5_tk") == "old"
    assert not (tmp_path / "cookies.json").exists()


def test_refresh_swallows_playwright_exception():
    session = _make_session({"_m_h5_tk": "old", "unb": "u1"})
    with patch.object(refresh, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run_raises(RuntimeError("chrome not installed"))
        ok = refresh.refresh_cookies_via_browser(session, persist=False)
    assert ok is False


@pytest.mark.parametrize(
    "env,expected",
    [(None, True), ("0", False), ("1", True), ("", True)],
)
def test_is_enabled_honors_env(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("GOOFISH_AUTO_REFRESH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GOOFISH_AUTO_REFRESH_TOKEN", env)
    assert refresh.is_enabled() is expected
