"""auth login — 导入闲鱼登录态到 ~/.goofish-cli/cookies.json。

默认行为（零参数）：从本机所有已装浏览器中自动探测 → 最低认知负荷。
支持的浏览器：Chrome / Edge / Brave / Chromium / Opera / OperaGX / Vivaldi
            / Arc / Firefox / LibreWolf / Safari（由 browser_cookie3 提供）。

降级路径：

- `auth login`                     自动 auto-detect（推荐）
- `auth login --browser edge`      指定单个浏览器
- `auth login <path>`              从 JSON 文件导入
- `auth login <cookie_str> --raw`  粘贴 "k=v; k=v" 字符串
- `auth login --qr`                扫码登录（兜底：浏览器免密记忆失效 / 换机 / 首次用）

触发条件：
1. 所有浏览器都没拿到 → 报错里列出手动兜底方案
2. 环境变量 GOOFISH_NO_CHROME_BOOTSTRAP=1 只影响其它命令启动时的
   Session.load 自动 bootstrap，不影响本命令。
"""
from __future__ import annotations

import json
from pathlib import Path

from goofish_cli.core import Strategy, command
from goofish_cli.core.errors import AuthRequiredError
from goofish_cli.core.session import DEFAULT_COOKIE_PATH, write_cookies_json


@command(
    namespace="auth",
    name="login",
    description="导入登录态（默认从本机浏览器 auto-detect；支持 Chrome/Edge/Brave/Safari/Firefox 等）",
    strategy=Strategy.PUBLIC,
    columns=["source", "path", "unb", "tracknick", "cookies_count"],
)
def login(
    source: str | None = None,
    *,
    raw: bool = False,
    browser: str = "auto",
    qr: bool = False,
    qr_timeout: int | None = None,
) -> dict[str, object]:
    target = DEFAULT_COOKIE_PATH

    if qr:
        # QR 和其它来源互斥：QR 会起独立 Playwright 浏览器，source / --raw / 指定
        # --browser 没意义还会让用户困惑（"我传的 cookie 哪去了？"）
        if source is not None or raw or browser != "auto":
            raise ValueError(
                "--qr 不能与 <source> / --raw / --browser 同时使用"
                "（QR 走独立的 Playwright 浏览器）"
            )
        # qr_timeout=None 让 core.qr_login 走统一的 env → 默认值 兜底逻辑；
        # 这里若写 int 默认（例如 120）会把 env 覆盖路径挡掉（CLI 总是显式传值）。
        from goofish_cli.core.qr_login import login_via_qr
        cookies = login_via_qr(timeout=qr_timeout, persist=False)
        if not cookies:
            # 空 dict 可能来自两种失败：超时未扫码，或 Playwright 起不来（Chrome
            # 未装、端口占用等）。文案同时覆盖，让用户知道去翻日志。
            raise AuthRequiredError(
                "QR 扫码登录未完成——可能是超时内未扫码 / 手机未确认，"
                "也可能是 Playwright 浏览器启动失败（Chrome 未装、端口占用等，"
                "详见前面的 warning 日志）。可重试并延长超时："
                "goofish auth login --qr --qr-timeout 180"
            )
        source_label = "qr"
    elif source is None:
        if raw:
            # --raw 要求紧跟 cookie 字符串；如果没传 source，说明用户漏了参数——
            # 不能静默走浏览器 auto-detect，否则 --raw 被吞，用户会困惑。
            raise ValueError(
                "--raw 需要配合 cookie 字符串使用，如："
                "goofish auth login 'unb=...; _m_h5_tk=...' --raw"
            )
        cookies, source_label = _pull_from_browser(browser)
    elif raw:
        cookies = _parse_raw(source)
        source_label = "raw"
    else:
        p = Path(source).expanduser()
        cookies = _parse_json(p.read_text())
        source_label = f"file:{p}"

    if "unb" not in cookies or "_m_h5_tk" not in cookies:
        raise AuthRequiredError(
            "cookie 缺失关键字段 unb / _m_h5_tk。"
            "请先在浏览器里登录 https://www.goofish.com 再试。"
        )

    write_cookies_json(target, cookies)

    return {
        "source": source_label,
        "path": str(target),
        "unb": cookies.get("unb", ""),
        "tracknick": cookies.get("tracknick", ""),
        "cookies_count": len(cookies),
    }


def _pull_from_browser(browser: str) -> tuple[dict[str, str], str]:
    from goofish_cli.core.browser_cookie import (
        BrowserCookieError,
        available_browsers,
        extract_goofish_cookies,
    )
    try:
        used, cookies = extract_goofish_cookies(browser=browser)
        return cookies, f"browser:{used}"
    except BrowserCookieError as e:
        supported = ", ".join(available_browsers())
        raise AuthRequiredError(
            f"浏览器登录态导入失败：{e}\n"
            f"兜底方案：\n"
            f"  1. 确认已在任一浏览器里登录 https://www.goofish.com 后重试\n"
            f"  2. 指定具体浏览器：`goofish auth login --browser edge`（支持：{supported}）\n"
            f"  3. 手动导出 JSON：`goofish auth login ~/Downloads/cookies.json`\n"
            f"  4. 粘 cookie 字符串：`goofish auth login 'unb=...; _m_h5_tk=...' --raw`"
        ) from e


def _parse_raw(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        out[k.strip()] = v.strip()
    return out


def _parse_json(text: str) -> dict[str, str]:
    data = json.loads(text)
    if isinstance(data, list):
        return {c["name"]: c["value"] for c in data if "name" in c and "value" in c}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    raise AuthRequiredError("cookie JSON 格式不识别（需 list 或 dict）")
