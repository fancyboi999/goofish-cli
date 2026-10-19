"""浏览器回写必须保留另一个进程已经保存的新登录。"""

import json
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from goofish_cli.core import sandbox_browser as sb
from goofish_cli.core import session as sm
from goofish_cli.core.crypto import decrypt_cookies


def records(user):
    return [
        {"name": key, "value": value, "domain": ".goofish.com", "path": "/"}
        for key, value in {
            "unb": user,
            "cookie2": "synthetic-" + user,
            "_m_h5_tk": "synthetic_token",
        }.items()
    ]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    source = tmp_path / "cookies.json"
    old, new = records("synthetic-A"), records("synthetic-B")
    sm.write_cookies_json(source, old)
    monkeypatch.setenv("GOOFISH_COOKIES_PATH", str(source))
    monkeypatch.setattr(sb, "ROOT", tmp_path)
    monkeypatch.setattr(sb, "STATE_PATH", tmp_path / "desktop-session.enc")
    monkeypatch.setattr(sb, "_generation", lambda: "synthetic-daemon")
    monkeypatch.setattr(sm, "_load_or_mint_device_id", lambda _: "synthetic-device")

    async def noop():
        pass

    async def cookies():
        return old

    context = SimpleNamespace(cookies=cookies, pages=[SimpleNamespace(bring_to_front=noop)])

    async def connect(_):
        return SimpleNamespace(contexts=[context])

    @asynccontextmanager
    async def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))

    monkeypatch.setattr(sb, "async_playwright", playwright)
    return source, old, new


def saved_user(source):
    return sm._records_to_flat(decrypt_cookies(source.read_bytes()))["unb"]


def concurrent_login(source, new):
    # 独立进程通过生产写入函数和真实文件锁提交合成登录，不操作真实凭证。
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from pathlib import Path; "
            "from goofish_cli.core.session import write_cookies_json; "
            "write_cookies_json(Path(sys.argv[1]), json.loads(sys.argv[2]))",
            str(source),
            json.dumps(new),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


async def test_login_during_snapshot_decode_survives_browser_exit(sandbox, monkeypatch):
    source, _, new = sandbox
    original_decode = sm.decrypt_cookies
    injected = False

    def decode_then_login(raw):
        nonlocal injected
        decoded = original_decode(raw)
        if not injected:
            injected = True
            concurrent_login(source, new)
        return decoded

    monkeypatch.setattr(sm, "decrypt_cookies", decode_then_login)
    async with sb.sandbox_page():
        assert injected
        assert saved_user(source) == "synthetic-B"
    assert saved_user(source) == "synthetic-B"


async def test_explicit_cookies_cannot_overwrite_an_unrelated_saved_login(sandbox):
    source, old, new = sandbox
    concurrent_login(source, new)
    async with sb.sandbox_page(cookies=old):
        assert saved_user(source) == "synthetic-B"
    assert saved_user(source) == "synthetic-B"


async def test_login_after_browser_entry_survives_exit(sandbox):
    source, _, new = sandbox
    async with sb.sandbox_page():
        concurrent_login(source, new)
    assert saved_user(source) == "synthetic-B"


async def test_unchanged_login_accepts_browser_cookie_refresh(sandbox):
    source, old, _ = sandbox
    async with sb.sandbox_page():
        old.append(
            {
                "name": "refreshed",
                "value": "synthetic-refresh",
                "domain": ".goofish.com",
                "path": "/",
            }
        )
    assert (
        sm._records_to_flat(decrypt_cookies(source.read_bytes()))["refreshed"]
        == "synthetic-refresh"
    )
