"""从本机浏览器直接读取闲鱼登录态。

参考 xiaohongshu-cli 的 auto-detect 设计——底层用 browser_cookie3 覆盖所有主流
浏览器（Chrome / Edge / Brave / Chromium / Opera / OperaGX / Vivaldi / Arc /
Firefox / LibreWolf / Safari），无需手写 Keychain / DPAPI 解密。

对应 opencli 的 Strategy.COOKIE——复用已登录的浏览器会话，让用户不用手动
从 DevTools 导出 JSON。区别在于 opencli 走 CDP 连"运行中的 Chrome"，我们走
磁盘直读（不需要浏览器处在运行状态，更适合 CLI 场景）。

双路兜底：
1. in-process：直接 import + 调 browser_cookie3 —— 最快，大部分场景够用
2. subprocess：fork 子进程跑，规避某些环境下 macOS Keychain 对主进程的限制
"""
from __future__ import annotations

import functools
import json
import subprocess
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from loguru import logger

# 闲鱼/淘系登录态涉及的域。browser_cookie3 的 domain_name 是子串匹配，
# 传 goofish.com 能覆盖 .goofish.com / www.goofish.com。为了不漏掉散落在
# 淘系其它子域的关键 cookie（unb/_m_h5_tk 历史上就跨 .taobao.com），
# 我们分别拉一遍后合并。
GOOFISH_DOMAINS = ("goofish.com", "taobao.com")

# cookie 入库前的域名白名单。in-process 和 subprocess 两条路径都用这个常量，
# 保证两条路径筛出的字段集一致（避免漂移导致同一浏览器两次抽取结果不同）。
ALLOWED_HOSTS = (
    "goofish.com", "taobao.com", "tmall.com",
    "alibaba.com", "alicdn.com", "aliyun.com", "mmstat.com",
)

# 至少要拿到这些字段才算"登录态有效"
REQUIRED_KEYS = ("unb", "_m_h5_tk")


class BrowserCookieError(Exception):
    """读取浏览器 cookie 失败的细分场景。不直接抛给最终用户——
    上层 Session.load / auth login 应捕获后再转成 AuthRequiredError。"""


# ── browser_cookie3 反射：枚举可用浏览器 ──────────────────────────────────

@functools.lru_cache(maxsize=1)
def available_browsers() -> tuple[str, ...]:
    """列出 browser_cookie3 支持、且接受 domain_name 参数的 loader 名称。

    反射方式比硬编码稳——browser_cookie3 升级加/减浏览器自动同步。
    过滤掉 `load`（它内部自己遍历所有浏览器，和我们的 auto 模式功能重叠）。
    """
    import inspect

    import browser_cookie3 as bc3

    return tuple(sorted(
        name
        for name in dir(bc3)
        if not name.startswith("_")
        and name != "load"
        and callable(getattr(bc3, name))
        and hasattr(getattr(bc3, name), "__code__")
        and "domain_name" in inspect.signature(getattr(bc3, name)).parameters
    ))


def _get_loader(browser: str):
    import browser_cookie3 as bc3
    loader = getattr(bc3, browser, None)
    if loader is None or not callable(loader):
        raise BrowserCookieError(
            f"不认识的浏览器：{browser!r}。支持列表：{', '.join(available_browsers())}"
        )
    return loader


# ── 单个浏览器的 in-process / subprocess 双路 ────────────────────────────

def _extract_in_process(browser: str) -> dict[str, str] | None:
    """直接 import browser_cookie3 调 loader。

    注意：对 `BrowserCookieError`（未知浏览器名）会直接 re-raise，让调用方
    区分"浏览器不认识"和"浏览器没登录态"两种情况——不然用户传 --browser foobar
    会得到误导性的"没找到有效登录态"。
    """
    loader = _get_loader(browser)  # 未知浏览器 → re-raise

    try:
        jars = [loader(domain_name=domain) for domain in GOOFISH_DOMAINS]
    except Exception as e:  # noqa: BLE001 — 浏览器没装/DB 锁/密钥解密失败都走这里
        logger.trace(f"{browser} in-process 抽取失败：{e}")
        return None

    return _jars_to_dict(jars)


def _extract_via_subprocess(browser: str) -> dict[str, str] | None:
    """fork 子进程跑 browser_cookie3。macOS Keychain 对主进程和子进程的
    授权作用域有时不一致，子进程兜底能救一些 Edge Case（也是 xhs-cli 的做法）。

    allowed_hosts 通过 argv 传进子进程，和 _jars_to_dict 用同一个常量，避免
    两条路径筛出的字段集漂移。
    """
    script = '''
import json, sys
try:
    import browser_cookie3 as bc3
except ImportError:
    print(json.dumps({"error": "browser-cookie3-not-installed"})); sys.exit(0)

browser, domains_csv, hosts_csv = sys.argv[1], sys.argv[2], sys.argv[3]
domains = domains_csv.split(",")
hosts = hosts_csv.split(",")
loader = getattr(bc3, browser, None)
if not loader or not callable(loader):
    print(json.dumps({"error": f"unknown-browser:{browser}"})); sys.exit(0)

out = {}
for d in domains:
    try:
        for c in loader(domain_name=d):
            host = (c.domain or "").lstrip(".")
            if any(h in host for h in hosts):
                out[c.name] = c.value
    except Exception as e:
        print(json.dumps({"error": f"extract-fail:{e}"})); sys.exit(0)
print(json.dumps({"cookies": out}))
'''
    try:
        result = subprocess.run(
            [
                sys.executable, "-c", script,
                browser,
                ",".join(GOOFISH_DOMAINS),
                ",".join(ALLOWED_HOSTS),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.trace(f"{browser} subprocess 调用失败：{e}")
        return None

    if result.returncode != 0:
        logger.trace(f"{browser} subprocess 退出非零：{result.stderr.strip()}")
        return None

    try:
        data = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError as e:
        logger.trace(f"{browser} subprocess 输出非 JSON：{e}")
        return None

    if "error" in data:
        logger.trace(f"{browser} subprocess 抽取失败：{data['error']}")
        return None

    return data.get("cookies") or None


def _jars_to_dict(jars: list[Any]) -> dict[str, str]:
    """从多个 CookieJar 合并筛出阿里系域 cookie。"""
    out: dict[str, str] = {}
    for jar in jars:
        for cookie in jar:
            host = (cookie.domain or "").lstrip(".")
            if not any(h in host for h in ALLOWED_HOSTS):
                continue
            # 同名后写覆盖前 —— 这里没法判优先级，实测取到 unb/_m_h5_tk 都 OK
            out[cookie.name] = cookie.value
    return out


def _try_browser(browser: str) -> dict[str, str] | None:
    """顺序走 in-process → subprocess。任一路径拿到 REQUIRED_KEYS 就返回。

    包住 _extract_in_process 的 BrowserCookieError —— auto 模式下反射出的
    名字肯定存在，不会触发；指定 browser 模式由 extract_goofish_cookies
    先校验，也不会到这。兜底：万一进来了就当成"该浏览器没有"。
    """
    try:
        cookies = _extract_in_process(browser)
    except BrowserCookieError:
        cookies = None
    if cookies and _is_valid(cookies):
        return cookies
    cookies = _extract_via_subprocess(browser)
    if cookies and _is_valid(cookies):
        return cookies
    return None


def _is_valid(cookies: dict[str, str]) -> bool:
    return all(k in cookies and cookies[k] for k in REQUIRED_KEYS)


# ── 对外主入口 ────────────────────────────────────────────────────────────

def extract_goofish_cookies(
    browser: str = "auto",
    *,
    max_workers: int = 4,
) -> tuple[str, dict[str, str]]:
    """抽闲鱼登录态。

    返回 (browser_name, cookies)。

    browser:
      - 'auto'：并发尝试所有已装浏览器，第一个拿到有效 cookie 的就用
      - 具体浏览器名（chrome / edge / brave / safari / firefox / ...）

    REQUIRED_KEYS 缺失 → 抛 BrowserCookieError，由上层转成 AuthRequiredError。
    未知浏览器名 → 直接抛 BrowserCookieError（不当成"没登录态"误导用户）。
    """
    if browser != "auto":
        # 先做一次名字校验，让"浏览器名不对"和"没登录态"报错分开
        _get_loader(browser)
        cookies = _try_browser(browser)
        if cookies:
            return browser, cookies
        raise BrowserCookieError(
            f"{browser} 里没找到有效的闲鱼登录态（缺 unb / _m_h5_tk）。"
            f"请先在 {browser} 里登录 https://www.goofish.com。"
        )

    browsers = available_browsers()
    if not browsers:
        raise BrowserCookieError(
            "browser_cookie3 没枚举到任何浏览器。"
            "请确认安装：`pip install browser-cookie3`。"
        )

    # 并发试所有浏览器，拿到第一个成功的立刻返回。
    # 不用 `with ThreadPoolExecutor(...) as pool` —— 退出 with 时会 shutdown(wait=True)，
    # 让 return 等所有浏览器跑完（即使 cancel 过），违背 FIRST_COMPLETED 的初衷。
    # 手动管理 + cancel_futures=True 才能真正快速返回。
    pool = ThreadPoolExecutor(max_workers=min(max_workers, len(browsers)))
    try:
        future_to_browser = {pool.submit(_try_browser, b): b for b in browsers}
        pending = set(future_to_browser)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                cookies = fut.result()
                if cookies:
                    pool.shutdown(wait=False, cancel_futures=True)
                    return future_to_browser[fut], cookies
    finally:
        # 无论成功与否，确保 pool 不会让调用者 hang 住
        pool.shutdown(wait=False, cancel_futures=True)

    tried = ", ".join(browsers)
    raise BrowserCookieError(
        f"所有浏览器都没找到闲鱼登录态（试过：{tried}）。"
        f"请在任一浏览器里登录 https://www.goofish.com 后重试。"
    )
