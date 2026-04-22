"""遇 FAIL_SYS_TOKEN_EXOIRED 时用 Playwright goto 闲鱼首页刷新 cookie。

`_m_h5_tk` 只有 10 分钟有效期，服务端在浏览器**活跃访问**闲鱼页面时通过
`Set-Cookie` 续期；浏览器静默几分钟就会过期。mcp/cli 用 `browser_cookie3`
从磁盘抓快照，命中"抓的时候还没过期、用的时候已过"的窗口很常见。

与其让用户手动去浏览器刷新，不如我们自己用 Playwright `goto` 一次首页——
反正 search/item view 的浏览器基础设施已经搭好了，直接复用。

开关：`GOOFISH_AUTO_REFRESH_TOKEN=0` 可关闭（CI 或想自定义刷新策略时）。

注意：闲鱼后端返回的错误码是 `FAIL_SYS_TOKEN_EXOIRED`（是 EXOIRED 不是 EXPIRED，
拼写没写错），和 `_AUTH_KEYWORDS` / `_is_token_expired_error` 匹配一致。
"""
from __future__ import annotations

import asyncio
import os

from loguru import logger

from goofish_cli.core.session import Session, resolve_cookie_path, write_cookies_json


async def _refresh_async(url: str, cookies: dict[str, str]) -> dict[str, str]:
    # 延迟 import：测试环境没装 playwright 也能 import refresh 模块
    from goofish_cli.core.browser import goofish_page

    # 显式传 cookies——让 Playwright context 注入**调用方当前 session** 的登录态，
    # 而不是让 goofish_page 再走一次 Session.load() 从磁盘拉（内存里可能已被改）。
    async with goofish_page(cookies=cookies) as page:
        await page.goto(url, wait_until="domcontentloaded")
        # 给 mtop h5 sign 一些时间跑完并让服务端 Set-Cookie 新 _m_h5_tk
        await page.wait_for_timeout(1500)
        pw_cookies = await page.context.cookies()

    return {c["name"]: c["value"] for c in pw_cookies if c.get("name") and c.get("value")}


def is_enabled() -> bool:
    return os.environ.get("GOOFISH_AUTO_REFRESH_TOKEN") != "0"


def refresh_cookies_via_browser(session: Session, *, persist: bool = True) -> bool:
    """用 Playwright goto 一次闲鱼首页拿新 cookie 并合并回 session。

    成功返回 True，否则 False（调用方按 False 走原始 AuthRequiredError）。
    """
    current = {name: value for name, value in session.http.cookies.items() if value}
    try:
        fresh = asyncio.run(_refresh_async("https://www.goofish.com", current))
    except Exception as e:  # noqa: BLE001 — Playwright 起不来、Chrome 未装、超时等都走这里
        logger.warning(f"用 Playwright 刷 cookie 失败：{e}")
        return False

    if "_m_h5_tk" not in fresh or "unb" not in fresh:
        logger.warning(f"刷 cookie 后仍缺关键字段，跳过合并（拿到 {len(fresh)} 个 cookie）")
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
