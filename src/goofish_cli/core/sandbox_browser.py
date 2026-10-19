"""串行使用沙箱内常驻浏览器，保存真实会话而不重建已验证窗口。"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from filelock import FileLock, Timeout
from loguru import logger
from playwright.async_api import async_playwright

from .browser_cookie import ALLOWED_HOSTS
from .crypto import decrypt_cookies, encrypt_cookies
from .errors import AuthRequiredError, GoofishError
from .local_state import atomic_write_bytes
from .session import (
    Session,
    _coerce_records,
    _records_to_flat,
    resolve_cookie_path,
    save_cookies_if_unchanged,
)

ENDPOINT = "http://127.0.0.1:9222"
ROOT = Path.home() / ".goofish-cli"
STATE_PATH = ROOT / "desktop-session.enc"


def _allowed(cookie: dict) -> bool:
    host = cookie.get("domain", "").lstrip(".")
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _missing_cookies(saved: list[dict], current: list[dict]) -> list[dict]:
    # Chrome 自己已持久化的 cookie 优先，不能用旧快照回滚新 token。
    keys = {(c["name"], c["domain"], c["path"]) for c in current}
    return [c for c in saved if _allowed(c) and (c["name"], c["domain"], c["path"]) not in keys]


def _read_state() -> dict | None:
    if not STATE_PATH.exists():
        return None
    try:
        state = decrypt_cookies(STATE_PATH.read_bytes())
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
            raise ValueError("invalid session state")
        for cookie in state["cookies"]:
            if not isinstance(cookie, dict) or not all(
                isinstance(cookie.get(k), str) for k in ("name", "value", "domain", "path")
            ):
                raise ValueError("invalid cookie record")
        return state
    except (OSError, ValueError, TypeError) as exc:
        raise GoofishError("沙箱会话快照不可读取；原文件保留，请检查后再继续") from exc


def _generation() -> str:
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(ENDPOINT + "/json/version", timeout=3) as response:
            value = json.load(response)["webSocketDebuggerUrl"]
        return hashlib.sha256(value.encode()).hexdigest()
    except (OSError, ValueError, KeyError) as exc:
        raise GoofishError("沙箱浏览器未就绪；请检查沙箱状态，不会启动本机浏览器") from exc


@asynccontextmanager
async def sandbox_page(*, cookies=None, persist_session: bool = True):
    from .browser import _cookies_to_playwright

    records = Session.load().cookie_records if cookies is None else _coerce_records(cookies)
    expected_user = _records_to_flat(records).get("unb")
    source = resolve_cookie_path()
    original_digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = FileLock(ROOT / "desktop-browser.lock", timeout=0, mode=0o600)
    try:
        lock.acquire()
    except Timeout as exc:
        raise GoofishError("沙箱浏览器正在处理另一个任务或等待人工验证；请完成后再试") from exc
    try:
        generation = _generation()
        state = _read_state()
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.connect_over_cdp(ENDPOINT)
            except Exception as exc:
                raise GoofishError("无法连接沙箱浏览器；不会回退到本机浏览器") from exc
            context = browser.contexts[0]
            current_cookies = await context.cookies()
            current = _records_to_flat(current_cookies)
            if expected_user and current.get("unb") not in (None, expected_user):
                raise AuthRequiredError("沙箱浏览器账号与 CLI 登录态不同，请在沙箱内重新登录")
            if state and state.get("generation") != generation:
                saved = _records_to_flat(state["cookies"])
                if expected_user and saved.get("unb") == expected_user:
                    await context.add_cookies(_missing_cookies(state["cookies"], current_cookies))
            elif state is None and records and not current.get("unb"):
                await context.add_cookies(_cookies_to_playwright(records))
            page = context.pages[0] if context.pages else await context.new_page()
            await page.bring_to_front()
            failed = False
            try:
                yield page
            except BaseException:
                failed = True
                raise
            finally:
                try:
                    native = [c for c in await context.cookies() if _allowed(c)]
                    flat = _records_to_flat(native)
                    if (
                        persist_session
                        and original_digest
                        and expected_user == flat.get("unb")
                        and all(flat.get(k) for k in ("unb", "_m_h5_tk", "cookie2"))
                    ):
                        save_cookies_if_unchanged(source, _coerce_records(native), original_digest)
                    atomic_write_bytes(
                        STATE_PATH, encrypt_cookies({"generation": generation, "cookies": native})
                    )
                except Exception as exc:
                    if failed:
                        logger.warning("沙箱会话保存失败，已保留原登录态；请检查沙箱浏览器状态")
                    else:
                        raise GoofishError("沙箱会话保存失败；请保留窗口并检查状态目录") from exc
            # 只断开本次 Playwright 连接；浏览器、页面和 sessionStorage 保持运行。
    finally:
        lock.release()
