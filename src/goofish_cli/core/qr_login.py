"""扫码登录——浏览器免密记忆失效时的 auth fallback。

与 v0.2.3 `core/refresh.py` 的分工：
- refresh：遇 mtop SESSION_EXPIRED 时**自动**点"快速进入"免密登录，无需用户交互。
- qr_login：用户免密记忆彻底清空（换机 / 长期不登 / 清 cookie）时，走**扫码**
  拿一份全新 session。必须显式触发（`auth login --qr`），因为需要用户拿手机。

不把 QR 塞进 refresh 自动路径的原因：refresh 的合约是"无感续命"，扫码要用户
参与，时间不可控，违反合约。所以两条路并存，根据"浏览器是否还认识你"自动/手动选。

passport 页面（`passport.goofish.com/mini_login.htm?...&styleType=vertical`）的
vertical 布局里扫码区和密码区并排，`.qrcode-login` 容器首屏就在 DOM 里——不用切 tab。

流程：
1. 本机用 `goofish_page(cookies={})` 开干净临时 profile；沙箱复用常驻页面，
   等待新 cookie 或平台账号响应确认，不能把旧 cookie 当作新登录成功
2. goto `/login` 登录页触发 passport iframe（首页改版后不再自动弹登录框）
3. 按 URL 轮询 `page.frames` 找 passport frame，等 `.qrcode-login` 渲染 → QR 就绪
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

from goofish_cli.core.cookie_types import CookieRecord
from goofish_cli.core.session import resolve_cookie_path, write_cookies_json

HOME_URL = "https://www.goofish.com/login"

# 扫码 + 手机确认后，passport 会下发完整 session cookie。这三个齐了才算真的登上：
# _m_h5_tk 是 h5 签名、unb 是用户 id、cookie2 是 session token。
_REQUIRED_LOGIN_COOKIES = ("_m_h5_tk", "unb", "cookie2")

_DEFAULT_QR_TIMEOUT = 120


async def _find_passport_frame(page: Any, timeout_ms: int = 20000) -> Any:
    """按 URL 轮询 page.frames 找 passport iframe。

    不用 element_handle.content_frame()：iframe 加载中会先 about:blank 再跳到
    passport 域，期间句柄跨文档失效，报 "Unable to adopt element handle from a
    different document"。直接轮询 page.frames 按 URL 匹配没有这个问题。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for frame in page.frames:
            if "passport" in (frame.url or ""):
                return frame
        await asyncio.sleep(0.5)
    return None


async def _wait_for_qr(page: Any, timeout_ms: int = 15000) -> bool:
    """等 passport iframe 里扫码区渲染出来（说明可扫）。

    QR 码容器是 `.qrcode-login`（内嵌 `.qrcode-img` 图片）。注意不是 canvas——
    passport 页改版后 QR 用 <img> 渲染，老选择器 `.qrcode-login canvas` 永远等不到。
    """
    frame = await _find_passport_frame(page)
    if not frame:
        logger.warning("[qr] 未检测到 passport iframe（登录页结构可能又变了）")
        return False
    try:
        await frame.wait_for_selector(".qrcode-login", timeout=timeout_ms)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[qr] QR 扫码区未渲染：{e}")
        return False


def _has_all_login_cookies(cookies_list: list[dict[str, Any]]) -> bool:
    names = {c.get("name") for c in cookies_list if c.get("value")}
    return all(k in names for k in _REQUIRED_LOGIN_COOKIES)


async def _login_via_qr_async(timeout: int) -> list[CookieRecord]:
    # 延迟 import——单测环境没装 playwright 也能 import 本模块
    from goofish_cli.core.browser import goofish_page

    # 本机用空 cookie 打开扫码页；沙箱保留常驻会话，允许平台提供快速进入。
    sandbox = os.environ.get("GOOFISH_DESKTOP_SANDBOX") == "1"
    async with goofish_page(cookies={}, persist_session=False) as page:
        initial = {c["name"]: c["value"] for c in await page.context.cookies()} if sandbox else {}
        authenticated = asyncio.Event()
        tasks = set()

        async def observe(response):
            from urllib.parse import urlsplit

            if urlsplit(response.url).path != "/h5/mtop.taobao.idlemessage.pc.loginuser.get/1.0/":
                return
            try:
                raw = await response.json()
                if any(
                    str(value).partition("::")[0] == "SUCCESS" for value in raw.get("ret") or []
                ):
                    authenticated.set()
            except Exception:
                pass

        def schedule(response):
            task = asyncio.create_task(observe(response))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        if sandbox:
            page.on("response", schedule)
        # 轮询 cookies：扫码 → 手机确认 → passport 下发完整 session 一般 < 5s
        deadline = time.monotonic() + timeout
        try:
            await page.goto(HOME_URL, wait_until="domcontentloaded")
            if not sandbox:
                await page.wait_for_timeout(1500)
                if not await _wait_for_qr(page):
                    return []

            logger.info(f"[qr] 请用手机闲鱼 App 扫码登录（{timeout}s 超时）")

            while time.monotonic() < deadline:
                cookies_list = await page.context.cookies()
                flat = {c["name"]: c["value"] for c in cookies_list}
                confirmed = (
                    not sandbox
                    or authenticated.is_set()
                    or flat.get("cookie2") != initial.get("cookie2")
                )
                if _has_all_login_cookies(cookies_list) and confirmed:
                    logger.info("[qr] 登录已确认，session cookies 已下发")
                    return [
                        {
                            "name": c["name"],
                            "value": c["value"],
                            "domain": c.get("domain", ""),
                            "path": c.get("path", "/"),
                        }
                        for c in cookies_list
                        if c.get("name") and c.get("value")
                    ]
                await asyncio.sleep(1.0)
        finally:
            if sandbox:
                page.remove_listener("response", schedule)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        logger.warning(f"[qr] {timeout}s 超时未登录成功")
        return []


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
        logger.warning(f"GOOFISH_QR_TIMEOUT={raw!r} 不是整数，回退默认 {_DEFAULT_QR_TIMEOUT}s")
        return _DEFAULT_QR_TIMEOUT


def login_via_qr(*, timeout: int | None = None, persist: bool = True) -> list[CookieRecord]:
    """阻塞：起 Playwright 让用户扫码，成功返回 CookieRecord 列表（保留 domain/path）并可选写回磁盘。

    空列表表示超时或 Playwright 异常（Chrome 未装等）。
    """
    timeout = _resolve_timeout(timeout)
    try:
        records = asyncio.run(_login_via_qr_async(timeout))
    except Exception as e:  # noqa: BLE001 — Playwright 起不来、Chrome 未装等都走这里
        logger.warning(f"QR 扫码登录失败：{e}")
        return []

    if not records:
        return []

    if persist:
        path = resolve_cookie_path()
        try:
            write_cookies_json(path, records)
            logger.info(f"cookie 已写回 {path}")
        except OSError as e:
            logger.warning(f"写回 cookies.json 失败（内存里仍生效）：{e}")

    return records
