"""IM accessToken 获取/刷新。对应 mtop.taobao.idlemessage.pc.login.token。

用于 WebSocket 鉴权（/reg 阶段）。不同于 HTTP 的 _m_h5_tk，这个 token 是给 IM 长连用的。

accessToken 会被缓存到 ~/.goofish-cli/im_token.json（TTL 由 GOOFISH_TOKEN_TTL 控制，默认 30 分钟）。
闲鱼风控对 `mtop.taobao.idlemessage.pc.login.token` 比较敏感，高频调用会 RGV587。
"""

import json
import os
import time
from pathlib import Path
from typing import Any

from goofish_cli.core.errors import AuthRequiredError
from goofish_cli.core.mtop import call
from goofish_cli.core.session import Session

IM_APP_KEY = "444e9908a51d1cb236a27862abc769c9"
TOKEN_CACHE = Path.home() / ".goofish-cli" / "im_token.json"
DEFAULT_TTL = 30 * 60  # 30 分钟，远低于真实 token 过期（观察约 2h）


def _ttl() -> int:
    try:
        return max(60, int(os.environ.get("GOOFISH_TOKEN_TTL", DEFAULT_TTL)))
    except ValueError:
        return DEFAULT_TTL


def _load_cache(unb: str) -> str | None:
    if not TOKEN_CACHE.exists():
        return None
    try:
        raw = json.loads(TOKEN_CACHE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if raw.get("unb") != unb:
        return None
    if time.time() - float(raw.get("t", 0)) > _ttl():
        return None
    return raw.get("token") or None


def _save_cache(unb: str, token: str) -> None:
    TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE.write_text(json.dumps({"unb": unb, "token": token, "t": time.time()}))
    TOKEN_CACHE.chmod(0o600)


def get_access_token(session: Session, *, force_refresh: bool = False) -> str:
    """取 WebSocket 用的 accessToken。

    优先级：环境变量 GOOFISH_IM_TOKEN > 文件缓存 > 调用 mtop 接口。
    支持注入原因：`mtop.taobao.idlemessage.pc.login.token` 风控非常敏感，
    完成滑块后 web 端自己持有的 token 可以直接拷出来塞给 CLI 用。
    """
    env_token = os.environ.get("GOOFISH_IM_TOKEN", "").strip()
    if env_token:
        return env_token
    if not force_refresh:
        cached = _load_cache(session.unb)
        if cached:
            return cached
    data = {"appKey": IM_APP_KEY, "deviceId": session.device_id}
    raw = call(
        session,
        api="mtop.taobao.idlemessage.pc.login.token",
        data=data,
        version="1.0",
        spm_cnt="a21ybx.im.0.0",
    )
    token = (raw.get("data") or {}).get("accessToken", "")
    if not token:
        raise AuthRequiredError(f"accessToken 获取失败：{raw.get('ret')}")
    _save_cache(session.unb, token)
    return token


def refresh_login(session: Session) -> dict[str, Any]:
    """刷新登录态（轻量 ping），长连常驻时 10 分钟调一次避免掉线。"""
    return call(
        session,
        api="mtop.taobao.idlemessage.pc.loginuser.get",
        data={},
        version="1.0",
        spm_cnt="a21ybx.im.0.0",
    )
