"""browser_cookie 多浏览器 auto-detect 流程。

核心场景：
1. available_browsers 反射能枚举到已装浏览器
2. 单浏览器模式：拿到 REQUIRED_KEYS → 返回；缺失 → 抛 BrowserCookieError
3. auto 模式：第一个成功的就返回；全部失败则抛
4. 域过滤：只保留阿里系 cookie，其他站点过滤
"""
from __future__ import annotations

import http.cookiejar as cookiejar

import pytest

from goofish_cli.core import browser_cookie as bc


def _make_cookie(name: str, value: str, domain: str) -> cookiejar.Cookie:
    """造一个符合 CookieJar 迭代结果的 Cookie 对象。"""
    return cookiejar.Cookie(
        version=0, name=name, value=value,
        port=None, port_specified=False,
        domain=domain, domain_specified=True, domain_initial_dot=domain.startswith("."),
        path="/", path_specified=True, secure=False,
        expires=None, discard=False, comment=None, comment_url=None,
        rest={}, rfc2109=False,
    )


def _fake_jar(*cookies):
    jar = cookiejar.CookieJar()
    for c in cookies:
        jar.set_cookie(c)
    return jar


# ── 反射枚举 ─────────────────────────────────────────────────────────────

def test_available_browsers_has_edge_and_chrome():
    """browser_cookie3 升级时本测试可能需要刷新；
    至少要有 chrome 和 edge——我们对用户承诺过支持这两个。"""
    names = bc.available_browsers()
    assert "chrome" in names
    assert "edge" in names
    # 不应该包括 load（它会尝试所有浏览器，和我们的 auto 重复）
    assert "load" not in names


# ── 指定单浏览器 ─────────────────────────────────────────────────────────

def test_extract_single_browser_success(monkeypatch):
    """edge 里抓到 unb/_m_h5_tk → 正常返回 (browser, cookies)。"""
    jar = _fake_jar(
        _make_cookie("unb", "2214350705775", ".taobao.com"),
        _make_cookie("_m_h5_tk", "TOKEN_abc_123", ".taobao.com"),
        _make_cookie("tracknick", "xy575986", ".goofish.com"),
        # 非阿里系域的 cookie，必须被过滤
        _make_cookie("sessionid", "other", ".example.com"),
    )
    import browser_cookie3 as bc3
    monkeypatch.setattr(bc3, "edge", lambda domain_name: jar)

    used, cookies = bc.extract_goofish_cookies(browser="edge")
    assert used == "edge"
    assert cookies["unb"] == "2214350705775"
    assert cookies["_m_h5_tk"] == "TOKEN_abc_123"
    assert cookies["tracknick"] == "xy575986"
    assert "sessionid" not in cookies


def test_extract_single_browser_missing_required_raises(monkeypatch):
    """edge 里只拿到 tracknick，缺 unb/_m_h5_tk → BrowserCookieError。"""
    jar = _fake_jar(_make_cookie("tracknick", "x", ".goofish.com"))
    import browser_cookie3 as bc3
    monkeypatch.setattr(bc3, "edge", lambda domain_name: jar)

    # subprocess 也 mock 成无效，避免真启动子进程跑到用户真实浏览器
    monkeypatch.setattr(bc, "_extract_via_subprocess", lambda _: None)

    with pytest.raises(bc.BrowserCookieError) as ei:
        bc.extract_goofish_cookies(browser="edge")
    assert "edge" in str(ei.value)


def test_extract_unknown_browser_raises_distinct_error(monkeypatch):
    """未知浏览器名 vs 浏览器没登录态 —— 报错消息必须区分开，否则用户无法排障。

    - 未知浏览器：消息应含"不认识"/"支持列表"（来自 _get_loader）
    - 没登录态：消息应含"没找到有效的闲鱼登录态"
    """
    # 避免 subprocess 真跑
    monkeypatch.setattr(bc, "_extract_via_subprocess", lambda _: None)

    with pytest.raises(bc.BrowserCookieError) as ei:
        bc.extract_goofish_cookies(browser="nonexistent-browser")
    msg = str(ei.value)
    assert "不认识" in msg or "支持列表" in msg, f"未知浏览器报错消息没区分：{msg}"


def test_subprocess_and_in_process_share_allowed_hosts():
    """in-process 和 subprocess 两条路径必须共用同一个 ALLOWED_HOSTS 常量，
    避免两条路径筛出的字段集漂移——Copilot 指出过 mmstat.com 两边不一致。"""
    # 确保常量存在且非空
    assert bc.ALLOWED_HOSTS, "ALLOWED_HOSTS 不能为空"
    # subprocess 脚本通过 argv 传 hosts —— 反证两条路径没各自 hardcode 一份
    import inspect
    src = inspect.getsource(bc._extract_via_subprocess)
    assert "hosts_csv" in src, "subprocess 脚本没从 argv 读 hosts，可能又 hardcode 了"
    assert 'ALLOWED_HOSTS' in src, "subprocess 启动参数里没引用 ALLOWED_HOSTS 常量"


# ── auto 模式 ────────────────────────────────────────────────────────────

def test_extract_auto_returns_first_success(monkeypatch):
    """auto 模式：chrome 空、edge 有 → 返回 edge 的结果。"""
    valid = {"unb": "U", "_m_h5_tk": "T_xxx_1", "tracknick": "nick"}

    def fake_try(browser: str):
        if browser == "edge":
            return valid
        return None

    monkeypatch.setattr(bc, "_try_browser", fake_try)
    # 反射结果固定，避免依赖环境
    monkeypatch.setattr(bc, "available_browsers", lambda: ("chrome", "edge", "safari"))

    used, cookies = bc.extract_goofish_cookies(browser="auto")
    assert used == "edge"
    assert cookies == valid


def test_extract_auto_all_fail_raises(monkeypatch):
    monkeypatch.setattr(bc, "_try_browser", lambda _: None)
    monkeypatch.setattr(bc, "available_browsers", lambda: ("chrome", "edge"))

    with pytest.raises(bc.BrowserCookieError) as ei:
        bc.extract_goofish_cookies(browser="auto")
    # 错误信息要告诉用户具体试过哪些
    assert "chrome" in str(ei.value)
    assert "edge" in str(ei.value)


def test_extract_auto_empty_browser_list(monkeypatch):
    monkeypatch.setattr(bc, "available_browsers", lambda: ())
    with pytest.raises(bc.BrowserCookieError):
        bc.extract_goofish_cookies(browser="auto")


# ── 辅助函数 ──────────────────────────────────────────────────────────────

def test_is_valid_requires_all_keys():
    assert bc._is_valid({"unb": "U", "_m_h5_tk": "T"})
    assert not bc._is_valid({"unb": "U"})
    assert not bc._is_valid({"unb": "", "_m_h5_tk": "T"})  # 空字符串不算


def test_jars_to_dict_filters_non_alibaba():
    jar = _fake_jar(
        _make_cookie("unb", "U", ".taobao.com"),
        _make_cookie("sessionid", "bad", ".github.com"),
        _make_cookie("foo", "bar", ".tmall.com"),
    )
    out = bc._jars_to_dict([jar])
    assert out == {"unb": "U", "foo": "bar"}
