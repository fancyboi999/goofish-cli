"""图片上传入口拥有独立媒体预算，只有服务端确认的完整图片收据才返回。"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError, RiskControlError
from goofish_cli.core.session import USER_AGENT
from goofish_cli.core.write_operation import write_operation

UPLOAD_URL = "https://stream-upload.goofish.com/api/upload.api"


def validate_image_path(path: str) -> Path:
    source = Path(path).expanduser()
    if not source.is_file() or source.stat().st_size == 0:
        raise GoofishError("图片文件不存在或为空")
    mime = mimetypes.guess_type(str(source))[0]
    if not mime or not mime.startswith("image/"):
        raise GoofishError("无法识别图片格式，请使用有正确扩展名的图片")
    return source


def validate_image_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoofishError("已上传图片必须包含 url、width、height")
    url = value.get("url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    host = parsed.hostname if parsed else ""
    if not parsed or parsed.scheme != "https" or parsed.username or not host or not (
        host == "alicdn.com" or host.endswith(".alicdn.com")
        or host == "goofish.com" or host.endswith(".goofish.com")
    ):
        raise GoofishError("图片 URL 必须是闲鱼上传返回的 HTTPS CDN 地址")
    dimensions = []
    for key in ("width", "height"):
        v = value.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).isdigit() or int(v) <= 0:
            raise GoofishError("图片宽高必须是正整数")
        dimensions.append(int(v))
    return {"url": url, "width": dimensions[0], "height": dimensions[1]}


@command(namespace="media", name="upload", description="上传图片，独立媒体预算，返回可复用图片收据",
         strategy=Strategy.COOKIE, columns=["url", "width", "height", "size"], write=True)
def upload(path: str) -> dict[str, Any]:
    source = validate_image_path(path)
    session = Session.load()
    headers = {"accept": "*/*", "origin": "https://www.goofish.com", "referer": "https://www.goofish.com/", "user-agent": USER_AGENT}
    params = {"floderId": "0", "appkey": "xy_chat", "_input_charset": "utf-8"}
    try:
        with source.open("rb") as stream, write_operation(session, "media.write"):
            resp = session.http.post(UPLOAD_URL, headers=headers, params=params,
                                     files={"file": (source.name, stream, mimetypes.guess_type(str(source))[0])}, timeout=60)
            resp.raise_for_status()
            raw = resp.json()
            if not isinstance(raw, dict):
                raise GoofishError("上传响应结构无效；未确认成功")
            if raw.get("success") is not True:
                marker = str(raw.get("status", ""))
                if any(k in marker for k in ("RGV587", "USER_VALIDATE", "ILLEGAL_ACCESS")):
                    raise RiskControlError("图片上传被平台风控拒绝")
                raise GoofishError("图片上传未被服务端确认成功")
            obj = raw.get("object") or {}
            if not isinstance(obj, dict):
                raise GoofishError("上传响应缺少图片对象")
            try:
                width, height = map(int, str(obj.get("pix", "")).split("x"))
            except (ValueError, TypeError):
                raise GoofishError("上传响应缺少有效图片尺寸") from None
            receipt = validate_image_receipt({"url": obj.get("url"), "width": width, "height": height})
    except (OSError, ValueError):
        raise GoofishError("图片上传连接或响应失败；未确认成功，不自动重传") from None
    return {**receipt, "size": obj.get("size")}
