"""Playwright 浏览器上下文 —— 吸纳 OpenCLI 的浏览器自动化路线。

设计要点（用户明确要求）：
1. **用系统 Chrome**（`channel="chrome"`），不用 playwright 自带的 bundled chromium——
   bundled chromium 的 UA / CDP 指纹太"裸"，是风控高危目标；系统 Chrome 是真实用户
   每天在用的可执行，配上真实 cookies 后基本等同正常浏览。
2. **每次调用独立 profile**（`~/.goofish-cli/profiles/chrome-<tmp>/`）：Chrome 一个
   `user_data_dir` 同时只能被一个进程打开（`SingletonLock`），固定路径会让并发调用
   （MCP 同时跑多个 tool / 用户手动并发）直接 ProfileInUse 起不来。所以每次 tmp 一个
   profile，退出清理——代价是首次启动多几百 ms，收益是天然支持并发。登录态不需要靠
   profile 持久化，我们每次用 `add_cookies` 从 `Session.load()` 灌。cookie 来源复用
   `Session.load()` 的三级兜底 —— `cookies.json` → `browser_cookie3` 自动从本机
   Chrome 抓 → `AuthRequiredError`，不在这里重复实现。
3. **默认 headful**：实测 headless chrome 的指纹（即便 channel=chrome）仍会被闲鱼判
   「非法访问」，返回"请使用正常浏览器访问"。要通过就必须以窗口模式启动。CI / 无桌面
   场景可 `GOOFISH_HEADLESS=1` 切回 headless（代价是可能被风控）。

同步命令怎么用：用 `asyncio.run(...)` 驱动本模块的 async 上下文（参考 list_chats
`--watch-secs` 的 `asyncio.run(collect_session_cids(...))` 模式）。
"""
from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from loguru import logger

from goofish_cli.core.session import Session

PROFILES_PARENT = Path.home() / ".goofish-cli" / "profiles"

# 需要种的域。goofish.com 下的 cookie 只在 .goofish.com 生效，
# 但淘系签名链路依赖的 _m_h5_tk / x5sec / sgcookie 历史上会跨 .taobao.com。
# playwright 的 add_cookies 要求显式 domain，所以我们按 cookie 名分发。
_TAOBAO_COOKIE_NAMES = {"_m_h5_tk", "_m_h5_tk_enc", "x5sec", "sgcookie", "cookie2", "_tb_token_"}


def _split_cookie_domain(name: str) -> str:
    """按 cookie 名字反推它归属哪个域。

    名字明显是淘系签名链（_m_h5_tk / x5sec / cookie2 / sgcookie）的 → `.taobao.com`，
    其余一律当 goofish 下：`.goofish.com`。实际浏览器里这些 cookie 是从
    `api.m.taobao.com` 和 `www.goofish.com` 分头写入的，所以灌的时候也要分头。
    """
    return ".taobao.com" if name in _TAOBAO_COOKIE_NAMES else ".goofish.com"


def _cookies_to_playwright(cookies: dict[str, str]) -> list[dict[str, Any]]:
    """把 `{name: value}` 转成 playwright `add_cookies` 需要的列表形态。"""
    now = int(__import__("time").time())
    # 7 天后过期——cookies.json 自身会被 Session 层更新，这里只要够跑完当前命令就行
    expires = now + 7 * 24 * 3600
    out: list[dict[str, Any]] = []
    for name, value in cookies.items():
        if not value:
            continue
        out.append({
            "name": name,
            "value": value,
            "domain": _split_cookie_domain(name),
            "path": "/",
            "expires": expires,
            "httpOnly": False,
            "secure": True,
            "sameSite": "None",
        })
    return out


def _load_cookies_from_session() -> dict[str, str]:
    """直接走 Session.load —— 三级兜底 (cookies.json → 本机 Chrome 自动抓 → AuthRequiredError)
    全在 Session 层已经实现，不重复造轮子。拿到 http.cookies 之后展平成 {name: value}。
    """
    session = Session.load()
    return {name: value for name, value in session.http.cookies.items() if value}


@asynccontextmanager
async def goofish_page(
    *,
    headless: bool | None = None,
    viewport: tuple[int, int] = (1440, 900),
) -> AsyncIterator[Any]:
    """启动系统 Chrome（独立 tmp profile）+ 灌 cookie，yield 出一个 `Page`。

    用法：
        async with goofish_page() as page:
            await page.goto("https://www.goofish.com/search?q=foo")
            ...
    """
    from playwright.async_api import async_playwright

    if headless is None:
        # 默认 headful。CI 用户显式 GOOFISH_HEADLESS=1 切回（可能触发风控）。
        headless = os.environ.get("GOOFISH_HEADLESS") == "1"

    PROFILES_PARENT.mkdir(parents=True, exist_ok=True)
    # 每次调用独立 profile 目录，避开 Chrome SingletonLock 并发冲突
    profile_dir = Path(tempfile.mkdtemp(prefix="chrome-", dir=str(PROFILES_PARENT)))
    cookies = _load_cookies_from_session()
    pw_cookies = _cookies_to_playwright(cookies)

    try:
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel="chrome",
                headless=headless,
                viewport={"width": viewport[0], "height": viewport[1]},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                    "--no-first-run",
                ],
            )
            try:
                await context.add_cookies(pw_cookies)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"注入 cookie 失败：{e}")

            page = context.pages[0] if context.pages else await context.new_page()
            # 隐藏 webdriver 特征（CDP 检测 cookie 外的最后一道门）
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            try:
                yield page
            finally:
                await context.close()
    finally:
        # 清理 tmp profile。忽略错误（进程被 kill 时残留目录由用户手动清 ~/.goofish-cli/profiles/）
        shutil.rmtree(profile_dir, ignore_errors=True)


async def auto_scroll(page: Any, times: int = 2, pause_ms: int = 800) -> None:
    """模拟 OpenCLI 的 `page.autoScroll({times})`：滚到底 N 次触发懒加载。"""
    for _ in range(times):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(pause_ms)
    await page.evaluate("window.scrollTo(0, 0)")
