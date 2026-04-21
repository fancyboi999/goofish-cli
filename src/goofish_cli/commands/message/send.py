"""message send — 向指定会话发送一条消息（文本/图片）。

写操作，走限流 + 熔断。未知 cid 时可传 --item-id 自动创建单聊。
"""

import asyncio
from typing import Any, Literal

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.guard import watch
from goofish_cli.core.limiter import acquire
from goofish_cli.core.token import get_access_token
from goofish_cli.core.ws import (
    connect,
    create_chat,
    heartbeat_loop,
    register,
    send_image,
    send_text,
)


@command(
    namespace="message",
    name="send",
    description="向会话发送消息（text/image）。text 必填，image 走 url+wh",
    strategy=Strategy.COOKIE,
    columns=["cid", "toid", "kind", "ok", "mid"],
    write=True,
)
def send(
    cid: str,
    toid: str,
    text: str = "",
    *,
    kind: Literal["text", "image"] = "text",
    image_url: str = "",
    image_width: int = 0,
    image_height: int = 0,
    item_id: str = "",
) -> dict[str, Any]:
    session = Session.load()
    with acquire("message.write"), watch():
        return asyncio.run(_send(
            session,
            cid=cid,
            toid=toid,
            text=text,
            kind=kind,
            image_url=image_url,
            image_width=image_width,
            image_height=image_height,
            item_id=item_id,
        ))


async def _send(
    session: Session,
    *,
    cid: str,
    toid: str,
    text: str,
    kind: str,
    image_url: str,
    image_width: int,
    image_height: int,
    item_id: str,
) -> dict[str, Any]:
    token = get_access_token(session)
    async with connect(session) as ws:
        await register(ws, session, token)
        hb = asyncio.create_task(heartbeat_loop(ws))
        try:
            if item_id:
                await create_chat(ws, myid=session.unb, toid=toid, item_id=item_id)
                await asyncio.sleep(0.5)

            if kind == "text":
                if not text:
                    raise ValueError("kind=text 需要 --text")
                mid = await send_text(
                    ws, myid=session.unb, cid=cid, toid=toid, text=text
                )
            elif kind == "image":
                if not (image_url and image_width and image_height):
                    raise ValueError("kind=image 需要 --image-url/--image-width/--image-height")
                mid = await send_image(
                    ws,
                    myid=session.unb,
                    cid=cid,
                    toid=toid,
                    url=image_url,
                    width=image_width,
                    height=image_height,
                )
            else:
                raise ValueError(f"不支持的 kind: {kind}")
            # 等一轮 ack 回包，避免 WS 提前关
            await asyncio.sleep(1.0)
        finally:
            hb.cancel()
    return {"cid": cid, "toid": toid, "kind": kind, "ok": True, "mid": mid}
