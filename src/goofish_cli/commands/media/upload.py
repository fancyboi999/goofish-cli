"""media upload — 上传图片到闲鱼 CDN。"""

import os

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.session import USER_AGENT

UPLOAD_URL = "https://stream-upload.goofish.com/api/upload.api"


@command(
    namespace="media",
    name="upload",
    description="上传图片到闲鱼 CDN，返回图片 URL + 尺寸",
    strategy=Strategy.COOKIE,
    columns=["url", "width", "height", "size"],
    write=True,
)
def upload(path: str) -> dict[str, object]:
    session = Session.load()
    abs_path = os.path.expanduser(path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"图片不存在：{abs_path}")

    headers = {
        "accept": "*/*",
        "origin": "https://www.goofish.com",
        "referer": "https://www.goofish.com/",
        "user-agent": USER_AGENT,
    }
    params = {"floderId": "0", "appkey": "xy_chat", "_input_charset": "utf-8"}

    with open(abs_path, "rb") as f:
        resp = session.http.post(
            UPLOAD_URL,
            headers=headers,
            params=params,
            files={"file": (os.path.basename(abs_path), f, "image/png")},
            timeout=60,
        )
    raw = resp.json()
    obj = raw.get("object") or {}
    pix = str(obj.get("pix", "0x0"))
    try:
        width, height = map(int, pix.split("x"))
    except ValueError:
        width = height = 0
    return {
        "url": obj.get("url", ""),
        "width": width,
        "height": height,
        "size": obj.get("size", 0),
    }
