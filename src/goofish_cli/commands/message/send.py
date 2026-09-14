"""message send — 向指定会话发送一条消息（文本/图片）。

写操作，走限流 + 熔断。未知 cid 时可传 --item-id 自动创建单聊。

发送前必须等 `/s/vulcan`（见 `wait_ready`），并校验握手与发送回包。

`ok` 的含义被严格限定为「服务端已接受该发送请求」（发送 ack `code=200`），
**不等同于**消息最终落库或对方已收到；后两者只能由 `message history`
回读或对端确认。拿不到 200 一律报错，不返回假成功。
"""

import asyncio
from typing import Any, Literal

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.guard import watch
from goofish_cli.core.limiter import acquire
from goofish_cli.core.token import get_access_token
from goofish_cli.core.ws import (
    connect,
    create_chat,
    heartbeat_loop,
    recv_ack,
    register,
    send_image,
    send_text,
    wait_ready,
)


@command(
    namespace="message",
    name="send",
    description="向会话发送消息（text/image）。text 必填，image 走 url+wh",
    strategy=Strategy.COOKIE,
    columns=["cid", "toid", "kind", "ok", "mid", "message_id"],
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
        handshake_mids = await register(ws, session, token)
        hb = asyncio.create_task(heartbeat_loop(ws))
        try:
            # `/r/` 请求必须等 `/s/vulcan` 之后才发，否则服务端回 code 400。
            # 顺带校验握手回包：/reg 非 200 抛错，ackDiff 非 200 只记警告。
            if not await wait_ready(ws, mids=handshake_mids):
                raise GoofishError("IM 连接未就绪（等待 /s/vulcan 超时），未发送")

            if item_id:
                create_mid = await create_chat(
                    ws, myid=session.unb, toid=toid, item_id=item_id
                )
                await recv_ack(ws, create_mid)

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
            ack = await recv_ack(ws, mid)
        finally:
            hb.cancel()

    ack_code = (ack or {}).get("code")
    if ack_code != 200:
        detail = "无回包（超时）" if ack is None else f"ack_code={ack_code}"
        raise GoofishError(f"发送未被服务端接受：{detail}")

    body = (ack or {}).get("body") or {}
    return {
        "cid": cid,
        "toid": toid,
        "kind": kind,
        "ok": True,
        "mid": mid,
        "message_id": str(body.get("messageId", "")),
    }
