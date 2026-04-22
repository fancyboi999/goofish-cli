"""统一 mtop 调用模板。抽出 headers/params/sign 流程。

要点：
- `t` 取真实毫秒：`int(time.time() * 1000)`，而不是 `int(time.time()) * 1000`（后者末三位恒为 0）
- 自动识别风控关键字抛 RiskControlError
- 自动识别令牌过期抛 AuthRequiredError
"""
from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

from goofish_cli.core.errors import (
    AuthRequiredError,
    GoofishError,
    NotFoundError,
    RiskControlError,
    SignError,
)
from goofish_cli.core.session import USER_AGENT, Session
from goofish_cli.core.sign import generate_sign

APP_KEY = "34839810"
MTOP_HOST = "https://h5api.m.goofish.com"

_RISK_KEYWORDS = (
    "RGV587_ERROR",
    "FAIL_SYS_USER_VALIDATE",
    "哎哟喂",
    "/punish",
)
_AUTH_KEYWORDS = (
    "FAIL_SYS_SESSION_EXPIRED",
    "FAIL_SYS_TOKEN_EXOIRED",
    "FAIL_SYS_TOKEN_EMPTY",
    "令牌过期",
    "FAIL_SYS_ILLEGAL_ACCESS",
)


def default_headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "accept-language": "en,zh-CN;q=0.9,zh;q=0.8,zh-TW;q=0.7,ja;q=0.6",
        "cache-control": "no-cache",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.goofish.com",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": "https://www.goofish.com/",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": USER_AGENT,
    }


def call(
    session: Session,
    api: str,
    data: dict[str, Any] | list[Any] | str,
    *,
    version: str = "1.0",
    spm_cnt: str = "a21ybx.home.0.0",
    extra_params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    _auto_refresh: bool = True,
) -> dict[str, Any]:
    """调用 mtop 接口。返回原始 JSON。失败抛 GoofishError 子类。

    `_auto_refresh=True`：遇到 token 层（`FAIL_SYS_TOKEN_EXOIRED`）或 session 层
    （`FAIL_SYS_SESSION_EXPIRED`）失效时，自动用 Playwright 访问闲鱼首页 + 点
    passport 弹窗的"快速进入"免密登录刷新 cookie 后重试一次。递归调用时置 False
    避免死循环。
    """
    url = f"{MTOP_HOST}/h5/{api}/{version}/"
    t_ms = str(int(time.time() * 1000))
    data_val = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))

    token = session.h5_token
    if not token:
        raise AuthRequiredError("_m_h5_tk 缺失，请重新登录并导出 cookie")
    sign = generate_sign(t_ms, token, data_val)

    params = {
        "jsv": "2.7.2",
        "appKey": APP_KEY,
        "t": t_ms,
        "sign": sign,
        "v": version,
        "type": "originaljson",
        "accountSite": "xianyu",
        "dataType": "json",
        "timeout": "20000",
        "api": api,
        "sessionOption": "AutoLoginOnly",
        "spm_cnt": spm_cnt,
    }
    if extra_params:
        params.update(extra_params)

    resp = session.http.post(
        url,
        params=params,
        headers=headers or default_headers(),
        data={"data": data_val},
        timeout=30,
    )
    raw = resp.json()
    try:
        _classify_error(raw, api)
    except AuthRequiredError as e:
        # token 层（_m_h5_tk 过期）和 session 层（cookie2/sgcookie 失效）都可以通过
        # Playwright goto 闲鱼首页 → 点 passport 弹窗的"快速进入"免密记忆登录恢复。
        # v0.2.3 起统一由 refresh_cookies_via_browser 处理；`ILLEGAL_ACCESS` 是风控
        # 层面问题，刷 cookie 也救不了，不在可恢复列表内。
        if not (_auto_refresh and _is_recoverable_auth_error(e)):
            raise
        from goofish_cli.core.refresh import is_enabled, refresh_cookies_via_browser
        if not is_enabled():
            raise
        logger.info(f"[{api}] 检测到登录态失效，尝试 Playwright 免密登录刷新 cookie…")
        if not refresh_cookies_via_browser(session):
            raise
        # 刷新成功：重试一次，禁用递归自动刷新
        return call(
            session, api, data,
            version=version, spm_cnt=spm_cnt,
            extra_params=extra_params, headers=headers,
            _auto_refresh=False,
        )
    return raw


def _is_recoverable_auth_error(e: AuthRequiredError) -> bool:
    """可通过 Playwright 自动刷新恢复的登录态失效错误码。

    - TOKEN_EXOIRED / TOKEN_EMPTY / 令牌过期 → h5_tk 层，goto 首页即续
    - SESSION_EXPIRED → session 层，点'快速进入'免密记忆登录恢复
    - ILLEGAL_ACCESS → 风控层，不在此列（救不了）
    """
    msg = str(e)
    return any(kw in msg for kw in (
        "FAIL_SYS_TOKEN_EXOIRED",
        "FAIL_SYS_TOKEN_EMPTY",
        "FAIL_SYS_SESSION_EXPIRED",
        "令牌过期",
    ))


def _classify_error(raw: dict[str, Any], api: str) -> None:
    """根据 ret 字段分类抛异常。成功则不抛。"""
    ret = raw.get("ret") or []
    ret_str = " | ".join(ret) if isinstance(ret, list) else str(ret)
    if not ret_str or "SUCCESS" in ret_str:
        return

    for kw in _RISK_KEYWORDS:
        if kw in ret_str:
            raise RiskControlError(
                f"[{api}] 触发风控：{ret_str}",
                raw=raw,
            )
    for kw in _AUTH_KEYWORDS:
        if kw in ret_str:
            raise AuthRequiredError(f"[{api}] 登录态失效：{ret_str}", raw=raw)
    if "ILLEGAL_REQUEST" in ret_str or "sign" in ret_str.lower():
        raise SignError(f"[{api}] 签名错误：{ret_str}", raw=raw)
    if "NOT_FOUND" in ret_str or "不存在" in ret_str:
        raise NotFoundError(f"[{api}] 未找到：{ret_str}", raw=raw)
    raise GoofishError(f"[{api}] 调用失败：{ret_str}", raw=raw)
