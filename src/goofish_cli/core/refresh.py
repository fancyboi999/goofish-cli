"""遇 token/session 层失效时用 Playwright 自动刷新 cookie。

`_m_h5_tk` 只有 10 分钟有效期，服务端在浏览器**活跃访问**闲鱼页面时通过
`Set-Cookie` 续期；浏览器静默几分钟就会过期。mcp/cli 用 `browser_cookie3`
从磁盘抓快照，命中"抓的时候还没过期、用的时候已过"的窗口很常见。

进一步：系统 Chrome 里被 `browser_cookie3` 抓走的 cookie 注入到 Playwright
tmp profile 后，服务端因为指纹不对会把这份 cookie 视为"半失效 session"，
首页访问会弹 passport 登录框 —— 弹窗里有 `快速进入`（免密记忆登录）按钮，
我们自动点一下就能让服务端重新下发完整 session cookie，整个过程用户无感。

流程（v0.2.3）：
1. goto 首页 → 可能弹 `#alibaba-login-box` 登录 iframe
2. iframe 里定位 `快速进入` 按钮并点击（免密记忆登录）
3. 等 modal 消失 → goto `/bought` 触发强鉴权页下发完整 session
4. 抓 Playwright context.cookies() 作为新快照

开关：`GOOFISH_AUTO_REFRESH_TOKEN=0` 可关闭（CI 或想自定义刷新策略时）。

注意：闲鱼后端返回的错误码是 `FAIL_SYS_TOKEN_EXOIRED`（是 EXOIRED 不是 EXPIRED，
拼写没写错），和 `_AUTH_KEYWORDS` / `_is_recoverable_auth_error` 匹配一致。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger

from goofish_cli.core.session import Session, resolve_cookie_path, write_cookies_json

HOME_URL = "https://www.goofish.com"
# 强鉴权页，goto 后服务端必须下发完整 session cookie（cookie2/sgcookie/_tb_token_）
AUTH_PROBE_URL = "https://www.goofish.com/bought"

# 刷新成功的必需字段：`_m_h5_tk`（h5 签名）和 `unb`（用户 id）是任何请求都要的；
# `cookie2` 是真正的 session token —— 光有 _m_h5_tk/unb 没有 cookie2 仍会被
# 服务端判定 SESSION_EXPIRED。所以"刷新成功"必须见到 cookie2 被下发。
_REQUIRED_FRESH_COOKIES = ("_m_h5_tk", "unb", "cookie2")


async def _try_quick_enter(page: Any) -> bool:
    """闲鱼首页若弹 passport 登录框，点'快速进入'走免密记忆登录。

    无弹窗 → 当作已登录返回 True。
    有弹窗但按钮不存在或点击失败 → 返回 False（浏览器里可能连免密记忆都清空了，
    这种情况需要扫码，不在本函数职责内，由调用方决定降级路径）。
    """
    iframe_el = await page.query_selector("#alibaba-login-box")
    if not iframe_el:
        return True
    frame = await iframe_el.content_frame()
    if not frame:
        logger.debug("[refresh] alibaba-login-box iframe content_frame 未就绪")
        return False
    try:
        # 显式 timeout：Playwright 默认 30s 太长，会让整个 refresh 流程卡住
        await frame.wait_for_load_state("domcontentloaded", timeout=5000)
        # 给 iframe 里的 Vue/React 组件一点时间 mount
        await page.wait_for_timeout(800)
        await frame.get_by_text("快速进入", exact=True).first.click(timeout=5000)
        logger.info("[refresh] 点击 passport '快速进入' 免密登录")
        await page.wait_for_selector("#alibaba-login-box", state="hidden", timeout=10000)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[refresh] '快速进入'不可用（浏览器免密记忆可能已失效）：{e}")
        return False


async def _refresh_async(cookies: dict[str, str]) -> dict[str, str]:
    # 延迟 import：测试环境没装 playwright 也能 import refresh 模块
    from goofish_cli.core.browser import goofish_page

    # 显式传 cookies——让 Playwright context 注入**调用方当前 session** 的登录态，
    # 而不是让 goofish_page 再走一次 Session.load() 从磁盘拉（内存里可能已被改）。
    async with goofish_page(cookies=cookies) as page:
        await page.goto(HOME_URL, wait_until="domcontentloaded")
        # 给弹窗 + mtop h5 sign 一些时间渲染
        await page.wait_for_timeout(1500)

        # 有弹窗但"快速进入"不可用 → 浏览器免密记忆彻底失效，后续 goto /bought
        # 也只会被跳登录页。直接返回空 dict 让上层报原始 AuthRequiredError，
        # 避免返回"只更新了 _m_h5_tk 但 session 仍失效"的假成功 cookies。
        if not await _try_quick_enter(page):
            return {}

        # 访问强鉴权页，触发服务端下发完整 session cookies（cookie2 / sgcookie /
        # _tb_token_ 会被 Set-Cookie 刷新）。
        try:
            await page.goto(AUTH_PROBE_URL, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1500)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[refresh] goto {AUTH_PROBE_URL} 异常（忽略）：{e}")

        pw_cookies = await page.context.cookies()

    return {c["name"]: c["value"] for c in pw_cookies if c.get("name") and c.get("value")}


def is_enabled() -> bool:
    return os.environ.get("GOOFISH_AUTO_REFRESH_TOKEN") != "0"


def refresh_cookies_via_browser(session: Session, *, persist: bool = True) -> bool:
    """用 Playwright 刷一次闲鱼 cookie 合并回 session。

    流程见模块 docstring。成功返回 True，否则 False（调用方按 False 走原始
    AuthRequiredError 让上层报给用户）。
    """
    current = {name: value for name, value in session.http.cookies.items() if value}
    try:
        fresh = asyncio.run(_refresh_async(current))
    except Exception as e:  # noqa: BLE001 — Playwright 起不来、Chrome 未装、超时等都走这里
        logger.warning(f"用 Playwright 刷 cookie 失败：{e}")
        return False

    missing = [k for k in _REQUIRED_FRESH_COOKIES if k not in fresh]
    if missing:
        logger.warning(
            f"刷 cookie 后仍缺关键字段 {missing}（可能'快速进入'未成功或 session 未下发），"
            f"跳过合并（拿到 {len(fresh)} 个 cookie）"
        )
        return False

    # 关键：直接 `update(fresh)` 会造成跨 domain 同名 cookie 并存（如 .goofish.com 下
    # 一份旧 _m_h5_tk + Playwright 又写入一份新的），后续 `cookies.get(name)` 会抛
    # "There are multiple cookies with name"。所以先删掉所有将被更新的 name 的旧条目。
    names_to_refresh = set(fresh.keys())
    for cookie in list(session.http.cookies):
        if cookie.name in names_to_refresh:
            session.http.cookies.clear(domain=cookie.domain, path=cookie.path, name=cookie.name)
    session.http.cookies.update(fresh)

    if persist:
        # 尊重 GOOFISH_COOKIES_PATH —— 用户配置了自定义路径时不能写默认路径后再下次
        # Session.load 又去读自定义路径，造成"刷新了但下次启动又回到旧的"。
        path = resolve_cookie_path()
        # 此时 session.http.cookies 已没有同名冲突，安全转 dict
        merged = {**dict(session.http.cookies), **fresh}
        try:
            write_cookies_json(path, merged)
            logger.info(f"cookie 已刷新并写回 {path}")
        except OSError as e:
            logger.debug(f"写回 cookies.json 失败（内存里仍生效）：{e}")
    return True
