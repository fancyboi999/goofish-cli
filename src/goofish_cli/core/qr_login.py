"""扫码登录——浏览器免密记忆失效时的 auth fallback。

与 v0.2.3 `core/refresh.py` 的分工：
- refresh：遇 mtop SESSION_EXPIRED 时**自动**点"快速进入"免密登录，无需用户交互。
- qr_login：用户免密记忆彻底清空（换机 / 长期不登 / 清 cookie）时，走**扫码**
  拿一份全新 session。必须显式触发（`auth login --qr`），因为需要用户拿手机。

不把 QR 塞进 refresh 自动路径的原因：refresh 的合约是"无感续命"，扫码要用户
参与，时间不可控，违反合约。所以两条路并存，根据"浏览器是否还认识你"自动/手动选。

passport 页面（`passport.goofish.com/mini_login.htm?...&styleType=vertical`）的
vertical 布局里扫码区和密码区并排，canvas 首屏就在 DOM 里——不用切 tab。

流程：
1. `goofish_page(cookies={})` 开**干净 tmp profile**（否则 passport 会优先走"快速
   进入"跳过 QR）
2. goto 首页触发 `#alibaba-login-box` iframe
3. 等 `.qrcode-login canvas` 渲染 → QR 就绪
4. 轮询 `context.cookies()`：看见 `_m_h5_tk / unb / cookie2` 全到位说明扫码 +
   手机端确认都过了，抓快照返回
5. 超时（默认 120s，`GOOFISH_QR_TIMEOUT` 可调）→ 空 dict，上层报 AuthRequiredError
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from loguru import logger

from goofish_cli.core.session import resolve_cookie_path, write_cookies_json

HOME_URL = "https://www.goofish.com"

# 扫码 + 手机确认后，passport 会下发完整 session cookie。这三个齐了才算真的登上：
# _m_h5_tk 是 h5 签名、unb 是用户 id、cookie2 是 session token。
_REQUIRED_LOGIN_COOKIES = ("_m_h5_tk", "unb", "cookie2")

_DEFAULT_QR_TIMEOUT = 120


async def _wait_for_qr(page: Any, timeout_ms: int = 15000) -> bool:
    """等 passport iframe 里 QR canvas 渲染出来（说明可扫）。"""
    try:
        iframe_el = await page.wait_for_selector("#alibaba-login-box", timeout=timeout_ms)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[qr] 未检测到 passport iframe：{e}（首页或许已登录？）")
        return False
    frame = await iframe_el.content_frame()
    if not frame:
        logger.warning("[qr] passport iframe content_frame 未就绪")
        return False
    try:
        await frame.wait_for_load_state("domcontentloaded", timeout=5000)
        await frame.wait_for_selector(".qrcode-login canvas", timeout=timeout_ms)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[qr] QR canvas 未渲染：{e}")
        return False


def _has_all_login_cookies(cookies_list: list[dict[str, Any]]) -> bool:
    names = {c.get("name") for c in cookies_list if c.get("value")}
    return all(k in names for k in _REQUIRED_LOGIN_COOKIES)


async def _login_via_qr_async(timeout: int) -> dict[str, str]:
    # 延迟 import——单测环境没装 playwright 也能 import 本模块
    from goofish_cli.core.browser import goofish_page

    # cookies={} 是关键：不传空 dict 会走 Session.load 把现有登录态灌进去，
    # passport 就优先走"快速进入"跳过 QR，用户看不到扫码界面。
    async with goofish_page(cookies={}) as page:
        await page.goto(HOME_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)

        if not await _wait_for_qr(page):
            return {}

        logger.info(f"[qr] 请用手机闲鱼 App 扫码登录（{timeout}s 超时）")

        # 轮询 cookies：扫码 → 手机确认 → passport 下发完整 session 一般 < 5s
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cookies_list = await page.context.cookies()
            if _has_all_login_cookies(cookies_list):
                logger.info("[qr] 扫码成功，session cookies 已下发")
                return {
                    c["name"]: c["value"]
                    for c in cookies_list
                    if c.get("name") and c.get("value")
                }
            await asyncio.sleep(1.0)

        logger.warning(f"[qr] {timeout}s 超时未登录成功")
        return {}


def _resolve_timeout(timeout: int | None) -> int:
    """timeout=None 时读 env；env 未设或非整数时回退默认值（不让 CLI 崩）。"""
    if timeout is not None:
        return timeout
    raw = os.environ.get("GOOFISH_QR_TIMEOUT")
    if not raw:
        return _DEFAULT_QR_TIMEOUT
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            f"GOOFISH_QR_TIMEOUT={raw!r} 不是整数，回退默认 {_DEFAULT_QR_TIMEOUT}s"
        )
        return _DEFAULT_QR_TIMEOUT


def login_via_qr(*, timeout: int | None = None, persist: bool = True) -> dict[str, str]:
    """阻塞：起 Playwright 让用户扫码，成功返回 cookies 并可选写回磁盘。

    空 dict 表示超时或 Playwright 异常（Chrome 未装等）。
    """
    timeout = _resolve_timeout(timeout)
    try:
        cookies = asyncio.run(_login_via_qr_async(timeout))
    except Exception as e:  # noqa: BLE001 — Playwright 起不来、Chrome 未装等都走这里
        logger.warning(f"QR 扫码登录失败：{e}")
        return {}

    if not cookies:
        return {}

    if persist:
        path = resolve_cookie_path()
        try:
            write_cookies_json(path, cookies)
            logger.info(f"cookie 已写回 {path}")
        except OSError as e:
            logger.warning(f"写回 cookies.json 失败（内存里仍生效）：{e}")

    return cookies
