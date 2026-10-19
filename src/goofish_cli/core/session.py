"""cookie 加载 + requests.Session 管理 + token 提取。

登录态解析顺序（从低认知负荷到高）：
1. cookies.json 存在且有效 → 直接用
2. cookies.json 不存在 → 从本机浏览器自动导入（auto-detect Chrome/Edge/
   Brave/Firefox/Safari 等，并发探测，哪个先成功用哪个）
3. 浏览器也抓不到 → 抛 AuthRequiredError，附带明确的手动兜底提示

环境变量 GOOFISH_NO_CHROME_BOOTSTRAP=1 可关闭自动探测（CI 场景）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import requests
from filelock import FileLock, Timeout
from loguru import logger

from goofish_cli.core.cookie_types import CookieRecord
from goofish_cli.core.crypto import decrypt_cookies, encrypt_cookies
from goofish_cli.core.errors import AuthRequiredError
from goofish_cli.core.sign import generate_device_id

DEFAULT_COOKIE_PATH = Path.home() / ".goofish-cli" / "cookies.json"


def resolve_cookie_path(cookie_path: Path | str | None = None) -> Path:
    """解析实际 cookie 文件路径。优先级：显式入参 > GOOFISH_COOKIES_PATH > 默认。

    `Session.load()` 和自动刷新写回逻辑必须走同一套解析，避免"读一个路径、写另一个"。
    """
    return Path(os.path.expanduser(
        cookie_path or os.environ.get("GOOFISH_COOKIES_PATH") or DEFAULT_COOKIE_PATH
    ))
DEVICE_CACHE_PATH = Path.home() / ".goofish-cli" / "device.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def _records_to_flat(records: list[CookieRecord]) -> dict[str, str]:
    """提取 records 中 {name, value} 为 flat dict，供 requests jar 使用。"""
    return {r["name"]: r["value"] for r in records if r.get("value")}


def _coerce_records(cookies: dict[str, str] | list[CookieRecord]) -> list[CookieRecord]:
    """dict | list → list[CookieRecord]。dict 时填充 domain='' path=''（legacy）。"""
    if isinstance(cookies, list):
        return [
            {
                "name": r["name"],
                "value": r["value"],
                "domain": r.get("domain", ""),
                "path": r.get("path", ""),
            }
            for r in cookies
            if r.get("value")
        ]
    return [
        {"name": k, "value": v, "domain": "", "path": ""}
        for k, v in cookies.items()
        if v
    ]


@dataclass
class Session:
    http: requests.Session
    unb: str
    tracknick: str
    device_id: str
    cookie_records: list[CookieRecord] = field(default_factory=list)

    @classmethod
    def load(cls, cookie_path: Path | str | None = None) -> Session:
        path = resolve_cookie_path(cookie_path)

        records = _load_or_bootstrap_cookies(path)  # now list[Record]
        flat = _records_to_flat(records)

        if "unb" not in flat or "_m_h5_tk" not in flat:
            raise AuthRequiredError(
                f"cookie 缺失 unb / _m_h5_tk，检查 {path} 是否完整（建议先在浏览器登录 "
                f"https://www.goofish.com 后再试 `goofish auth login`）"
            )
        http = requests.Session()
        http.cookies.update(flat)
        return cls(
            http=http,
            unb=flat["unb"],
            tracknick=flat.get("tracknick", ""),
            device_id=_load_or_mint_device_id(flat["unb"]),
            cookie_records=records,
        )

    @property
    def h5_token(self) -> str:
        raw = self.http.cookies.get("_m_h5_tk", "")
        return raw.split("_")[0] if raw else ""


def _load_or_bootstrap_cookies(path: Path) -> list[CookieRecord]:
    """先查本地 cookies.json；没有就从本机浏览器自动导入一次写盘。"""
    if path.exists():
        cookies = _load_cookies(path)
        # 明文旧文件 → 自动加密覆盖
        _maybe_migrate_to_encrypted(path, cookies)
        return cookies

    # 本地不存在，走自动 bootstrap（除非用户显式关闭）
    if os.environ.get("GOOFISH_NO_CHROME_BOOTSTRAP") == "1":
        raise AuthRequiredError(
            f"cookie 文件不存在：{path}。\n"
            f"请执行 `goofish auth login` 从本机浏览器自动导入，"
            f"或 `goofish auth login <path>` 手动指定。"
        )

    try:
        browser, cookies = _bootstrap_from_browser()
    except Exception as e:  # noqa: BLE001 — 浏览器抽取失败就走友好兜底
        logger.debug(f"浏览器自动导入失败：{e}")
        raise AuthRequiredError(
            f"cookie 文件不存在：{path}。\n"
            f"自动从浏览器导入也失败了（{e}）。\n"
            f"请在 Chrome / Edge / Brave 等任一浏览器里登录 https://www.goofish.com 后重试，"
            f"或手动导出 JSON：`goofish auth login <path>`。"
        ) from e

    # coerce：browser_cookie.py 已改为返回 list[Record]，但保留对 flat dict 的兼容
    records = _coerce_records(cookies)

    # 写盘前最后一道校验：bootstrap 回来的 cookies 必须含 REQUIRED_KEYS，
    # 否则坚决不落盘——避免半残 cookie 污染后续每次 Session.load。
    flat = _records_to_flat(records)
    if "unb" not in flat or "_m_h5_tk" not in flat:
        raise AuthRequiredError(
            f"已从 {browser} 拿到 cookie，但缺 unb / _m_h5_tk 关键字段，"
            f"未写入 {path}。请在 {browser} 里重新登录 https://www.goofish.com 后重试。"
        )

    write_cookies_json(path, records)
    logger.info(f"已从 {browser} 自动导入登录态 → {path}")
    return records


def _bootstrap_from_browser() -> tuple[str, list[CookieRecord]]:
    """单独封装一层，方便测试时 monkeypatch。"""
    from goofish_cli.core.browser_cookie import extract_goofish_cookies
    return extract_goofish_cookies(browser="auto")


def write_cookies_json(path: Path, cookies) -> None:
    """cookies 可为 {name: value} dict 或 list[Record]。"""
    _replace_cookies(path, cookies)


def save_cookies_if_unchanged(path: Path, cookies, expected_digest: str) -> bool:
    """浏览器回写时拒绝覆盖期间被另一次登录替换的快照。"""
    return _replace_cookies(path, cookies, expected_digest)


def _replace_cookies(path: Path, cookies, expected_digest: str | None = None) -> bool:
    from .local_state import atomic_write_bytes

    records = _coerce_records(cookies) if isinstance(cookies, dict) else cookies
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(path) + ".lock", timeout=5, mode=0o600):
            if expected_digest is not None and (
                not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest
            ):
                return False
            atomic_write_bytes(path, encrypt_cookies(records))
    except Timeout as exc:
        raise OSError("登录态写入锁超时；原文件保留") from exc
    return True


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


def _load_cookies(path: Path) -> list[CookieRecord]:
    raw_bytes = path.read_bytes()
    # 优先尝试解密（加密格式或明文 JSON）
    data: dict | list | None = None
    with contextlib.suppress(Exception):
        data = decrypt_cookies(raw_bytes)
    if data is None:
        try:
            data = json.loads(raw_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise AuthRequiredError(f"cookie 文件格式不识别：{path}") from e
    return _coerce_records(data)


def _maybe_migrate_to_encrypted(path: Path, cookies: list[CookieRecord]) -> None:
    """如果文件是明文 JSON，自动加密覆盖。"""
    try:
        raw = path.read_bytes()
        json.loads(raw)  # 能 parse 说明是明文
    except (json.JSONDecodeError, UnicodeDecodeError):
        return  # 已经是加密格式，无需迁移
    try:
        write_cookies_json(path, cookies)
        logger.info(f"已将明文 cookie 自动加密 → {path}")
    except OSError as e:
        logger.debug(f"自动加密迁移失败（不影响使用）：{e}")
