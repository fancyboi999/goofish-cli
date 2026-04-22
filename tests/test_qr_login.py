"""测 qr_login 模块。Playwright 走真浏览器不进单测，mock 掉 asyncio.run。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from goofish_cli.core import qr_login


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


def test_login_via_qr_success_writes_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(tmp_path / "cookies.json"))
    fake = {"_m_h5_tk": "t", "unb": "u", "cookie2": "c", "sgcookie": "s"}
    with patch.object(qr_login, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run(fake)
        out = qr_login.login_via_qr(timeout=10, persist=True)

    assert out == fake
    assert (tmp_path / "cookies.json").exists()


def test_login_via_qr_success_no_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(tmp_path / "cookies.json"))
    fake = {"_m_h5_tk": "t", "unb": "u", "cookie2": "c"}
    with patch.object(qr_login, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run(fake)
        out = qr_login.login_via_qr(timeout=10, persist=False)

    assert out == fake
    assert not (tmp_path / "cookies.json").exists()


def test_login_via_qr_timeout_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(tmp_path / "cookies.json"))
    with patch.object(qr_login, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run({})  # 模拟超时没拿到 cookies
        out = qr_login.login_via_qr(timeout=5, persist=True)

    assert out == {}
    # 空结果不应写盘
    assert not (tmp_path / "cookies.json").exists()


def test_login_via_qr_swallows_playwright_exception():
    with patch.object(qr_login, "asyncio") as mock_async:
        mock_async.run.side_effect = _fake_run_raises(RuntimeError("chrome not installed"))
        out = qr_login.login_via_qr(timeout=5, persist=False)
    assert out == {}


def test_login_via_qr_respects_env_timeout(monkeypatch):
    """timeout=None 时读 GOOFISH_QR_TIMEOUT，传给 _login_via_qr_async。"""
    monkeypatch.setenv("GOOFISH_QR_TIMEOUT", "30")
    captured: list[int] = []

    async def _record(t):
        captured.append(t)
        return {}

    monkeypatch.setattr(qr_login, "_login_via_qr_async", _record)
    out = qr_login.login_via_qr(persist=False)

    assert captured == [30]
    assert out == {}


def test_login_via_qr_env_invalid_falls_back(monkeypatch):
    """Copilot review：env 非整数不能让命令崩，要 warn + 回退默认。"""
    monkeypatch.setenv("GOOFISH_QR_TIMEOUT", "not-a-number")
    captured: list[int] = []

    async def _record(t):
        captured.append(t)
        return {}

    monkeypatch.setattr(qr_login, "_login_via_qr_async", _record)
    # 不应抛 ValueError
    out = qr_login.login_via_qr(persist=False)

    assert captured == [qr_login._DEFAULT_QR_TIMEOUT]
    assert out == {}


def test_login_via_qr_explicit_timeout_wins_over_env(monkeypatch):
    """显式传 timeout 时不读 env。"""
    monkeypatch.setenv("GOOFISH_QR_TIMEOUT", "999")
    captured: list[int] = []

    async def _record(t):
        captured.append(t)
        return {}

    monkeypatch.setattr(qr_login, "_login_via_qr_async", _record)
    qr_login.login_via_qr(timeout=42, persist=False)

    assert captured == [42]


@pytest.mark.parametrize(
    "cookies,expected",
    [
        ([{"name": "_m_h5_tk", "value": "a"},
          {"name": "unb", "value": "b"},
          {"name": "cookie2", "value": "c"}], True),
        ([{"name": "_m_h5_tk", "value": "a"},
          {"name": "unb", "value": "b"}], False),  # 缺 cookie2
        ([{"name": "_m_h5_tk", "value": "a"},
          {"name": "unb", "value": ""},  # unb 为空等于没有
          {"name": "cookie2", "value": "c"}], False),
        ([], False),
    ],
)
def test_has_all_login_cookies(cookies, expected):
    assert qr_login._has_all_login_cookies(cookies) is expected
