"""Session.load 自动 bootstrap 行为。

目标：验证零认知负荷路径——cookies.json 不存在时，自动从 Chrome 抓。
所有真 Chrome 调用都 monkeypatch 掉。
"""
from __future__ import annotations

import json

import pytest

from goofish_cli.core import session as session_mod
from goofish_cli.core.errors import AuthRequiredError


@pytest.fixture
def fake_cookies_path(tmp_path, monkeypatch):
    """把 DEFAULT_COOKIE_PATH / DEVICE_CACHE_PATH 指到 tmp_path，
    避免测试互相干扰、也避免踩到用户真实的 ~/.goofish-cli。"""
    cookies = tmp_path / "cookies.json"
    device = tmp_path / "device.json"
    monkeypatch.setattr(session_mod, "DEFAULT_COOKIE_PATH", cookies)
    monkeypatch.setattr(session_mod, "DEVICE_CACHE_PATH", device)
    monkeypatch.delenv("GOOFISH_COOKIES_PATH", raising=False)
    monkeypatch.delenv("GOOFISH_NO_CHROME_BOOTSTRAP", raising=False)
    return cookies


def test_load_uses_existing_cookies_json(fake_cookies_path, monkeypatch):
    """cookies.json 已存在 → 不该触发 Chrome bootstrap。"""
    fake_cookies_path.write_text(json.dumps([
        {"name": "unb", "value": "U1"},
        {"name": "_m_h5_tk", "value": "T_xxx_1"},
        {"name": "tracknick", "value": "nick1"},
    ]))

    # bootstrap 被调用就失败
    def fail(*_args, **_kwargs):
        raise AssertionError("bootstrap 不该被触发")
    monkeypatch.setattr(session_mod, "_bootstrap_from_browser", fail)

    s = session_mod.Session.load()
    assert s.unb == "U1"
    assert s.tracknick == "nick1"
    assert s.h5_token == "T"  # _m_h5_tk 取下划线前那一段


def test_load_bootstraps_when_missing(fake_cookies_path, monkeypatch):
    """cookies.json 不存在 → 自动从浏览器抓 → 写盘，下次直接读。"""
    fake = {"unb": "U2", "_m_h5_tk": "T_99_1", "tracknick": "nick2"}
    called = {"n": 0}

    def fake_bootstrap():
        called["n"] += 1
        return "edge", fake
    monkeypatch.setattr(session_mod, "_bootstrap_from_browser", fake_bootstrap)

    s = session_mod.Session.load()
    assert s.unb == "U2"
    assert called["n"] == 1
    # 写盘了
    assert fake_cookies_path.exists()
    data = json.loads(fake_cookies_path.read_text())
    assert {"name": "unb", "value": "U2"} in data
    # 文件权限 0o600
    assert (fake_cookies_path.stat().st_mode & 0o777) == 0o600

    # 第二次 load 应命中缓存，不再调 bootstrap
    s2 = session_mod.Session.load()
    assert s2.unb == "U2"
    assert called["n"] == 1, "第二次不该再调 bootstrap"


def test_load_falls_back_to_auth_error_when_bootstrap_fails(fake_cookies_path, monkeypatch):
    """浏览器抓失败 → AuthRequiredError 并给出手动兜底提示。"""
    def boom():
        raise RuntimeError("all browsers failed")
    monkeypatch.setattr(session_mod, "_bootstrap_from_browser", boom)

    with pytest.raises(AuthRequiredError) as ei:
        session_mod.Session.load()
    msg = str(ei.value)
    # 错误必须指向手动兜底路径
    assert "auth login" in msg
    assert "all browsers failed" in msg


def test_load_skips_bootstrap_when_env_disabled(fake_cookies_path, monkeypatch):
    """GOOFISH_NO_CHROME_BOOTSTRAP=1 → 不自动探测浏览器，直接报错。CI 场景需要这个开关。"""
    monkeypatch.setenv("GOOFISH_NO_CHROME_BOOTSTRAP", "1")

    def fail(*_a, **_k):
        raise AssertionError("bootstrap 被触发了")
    monkeypatch.setattr(session_mod, "_bootstrap_from_browser", fail)

    with pytest.raises(AuthRequiredError) as ei:
        session_mod.Session.load()
    assert "cookie 文件不存在" in str(ei.value)


def test_load_raises_when_bootstrapped_cookies_missing_keys(fake_cookies_path, monkeypatch):
    """bootstrap 回来的 cookie 不带 unb/_m_h5_tk → 依旧报错，
    避免把半残 cookie 落盘造成后续命令反复失败。"""
    monkeypatch.setattr(
        session_mod, "_bootstrap_from_browser",
        lambda: ("edge", {"tracknick": "nick_only"}),
    )

    with pytest.raises(AuthRequiredError):
        session_mod.Session.load()


def test_write_cookies_json_format(tmp_path):
    """write_cookies_json 应写 Chrome 扩展风格的 list。auth login 和 Session 都用同一个。"""
    target = tmp_path / "out.json"
    session_mod.write_cookies_json(target, {"a": "1", "b": "2"})
    data = json.loads(target.read_text())
    assert data == [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]
    assert (target.stat().st_mode & 0o777) == 0o600
