"""cookie 加载 + requests.Session 管理 + token 提取。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import requests

from goofish_cli.core.errors import AuthRequiredError
from goofish_cli.core.sign import generate_device_id

DEFAULT_COOKIE_PATH = Path.home() / ".goofish-cli" / "cookies.json"
DEVICE_CACHE_PATH = Path.home() / ".goofish-cli" / "device.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


@dataclass
class Session:
    http: requests.Session
    unb: str
    tracknick: str
    device_id: str

    @classmethod
    def load(cls, cookie_path: Path | str | None = None) -> Session:
        path = Path(os.path.expanduser(
            cookie_path or os.environ.get("GOOFISH_COOKIES_PATH") or DEFAULT_COOKIE_PATH
        ))
        if not path.exists():
            raise AuthRequiredError(
                f"cookie 文件不存在：{path}。请先 `goofish auth login --from <path>` 导入。"
            )
        cookies = _load_cookies(path)
        if "unb" not in cookies or "_m_h5_tk" not in cookies:
            raise AuthRequiredError(
                f"cookie 缺失 unb / _m_h5_tk，检查 {path} 是否完整（建议从 goofish.com 登录后再导一次）"
            )
        http = requests.Session()
        http.cookies.update(cookies)
        return cls(
            http=http,
            unb=cookies["unb"],
            tracknick=cookies.get("tracknick", ""),
            device_id=_load_or_mint_device_id(cookies["unb"]),
        )

    @property
    def h5_token(self) -> str:
        raw = self.http.cookies.get("_m_h5_tk", "")
        return raw.split("_")[0] if raw else ""


def _load_or_mint_device_id(unb: str) -> str:
    """device_id 必须在 unb 维度稳定。

    IM WebSocket 的 accessToken 会绑定 (appKey, deviceId)。若每次 Session.load 调用
    JS 重新随机生成 device_id，token 签发时用 A，/reg 时用 B，会返回 401
    "device id or appkey is not equal"。
    """
    if DEVICE_CACHE_PATH.exists():
        try:
            raw = json.loads(DEVICE_CACHE_PATH.read_text())
            if raw.get("unb") == unb and raw.get("device_id"):
                return raw["device_id"]
        except (json.JSONDecodeError, OSError):
            pass
    device_id = generate_device_id(unb)
    DEVICE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_CACHE_PATH.write_text(json.dumps({"unb": unb, "device_id": device_id}))
    DEVICE_CACHE_PATH.chmod(0o600)
    return device_id


def _load_cookies(path: Path) -> dict[str, str]:
    text = path.read_text()
    raw = json.loads(text)
    # 兼容两种格式：Chrome 扩展导出的 list[{name,value,...}] / 纯 dict
    if isinstance(raw, list):
        return {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    raise AuthRequiredError(f"cookies.json 格式不识别：{path}")
