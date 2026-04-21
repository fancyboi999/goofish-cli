"""闲鱼 IM WebSocket 运行时。

协议：LWP（Long-polling WebSocket Protocol，钉钉体系）——JSON 而非 Protobuf。
端点：wss://wss-goofish.dingtalk.com/

职责：
- 连接 + /reg 注册（accessToken 鉴权）
- 心跳 /!（15s）
- 下行 ack（code=200 回包，透传 mid/sid/app-key/ua/dt）
- 上行业务帧：send_msg / list_user_messages / create_chat
- 收包解密回退（syncPushPackage.data[].data → json 或 decrypt）
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

import websockets
from loguru import logger
from websockets.asyncio.client import ClientConnection

from goofish_cli.core.session import Session
from goofish_cli.core.sign import decrypt, generate_mid, generate_uuid
from goofish_cli.core.token import IM_APP_KEY, get_access_token

WS_URL = "wss://wss-goofish.dingtalk.com/"
UA_WEB = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)
UA_IM = (
    UA_WEB
    + " DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) "
    + "DingWeb/2.1.5 IMPaaS DingWeb/2.1.5"
)


def _cookie_header(session: Session) -> str:
    return "; ".join(f"{k}={v}" for k, v in session.http.cookies.get_dict().items())


def _handshake_headers(session: Session) -> dict[str, str]:
    return {
        "Cookie": _cookie_header(session),
        "Host": "wss-goofish.dingtalk.com",
        "Connection": "Upgrade",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "User-Agent": UA_WEB,
        "Origin": "https://www.goofish.com",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


@asynccontextmanager
async def connect(session: Session) -> AsyncIterator[ClientConnection]:
    """建立 WebSocket 连接（未 reg）。外层自己 reg + heartbeat。"""
    async with websockets.connect(
        WS_URL,
        additional_headers=_handshake_headers(session),
        ping_interval=None,  # 禁用 WS ping，我们走 LWP /! 心跳
        max_size=4 * 1024 * 1024,
    ) as ws:
        yield ws


async def register(ws: ClientConnection, session: Session, token: str) -> None:
    """/reg + /r/SyncStatus/ackDiff。发完立即返回，后续由外层 recv 循环消化回包。"""
    reg = {
        "lwp": "/reg",
        "headers": {
            "cache-header": "app-key token ua wv",
            "app-key": IM_APP_KEY,
            "token": token,
            "ua": UA_IM,
            "dt": "j",
            "wv": "im:3,au:3,sy:6",
            "sync": "0,0;0;0;",
            "did": session.device_id,
            "mid": generate_mid(),
        },
    }
    await ws.send(json.dumps(reg))
    current_ms = int(time.time() * 1000)
    ack_diff = {
        "lwp": "/r/SyncStatus/ackDiff",
        "headers": {"mid": generate_mid()},
        "body": [
            {
                "pipeline": "sync",
                "tooLong2Tag": "PNM,1",
                "channel": "sync",
                "topic": "sync",
                "highPts": 0,
                "pts": current_ms * 1000,
                "seq": 0,
                "timestamp": current_ms,
            }
        ],
    }
    await ws.send(json.dumps(ack_diff))


async def heartbeat_loop(ws: ClientConnection, interval: float = 15.0) -> None:
    """LWP /! 空心跳，默认 15s 一次。"""
    while True:
        try:
            await ws.send(json.dumps({"lwp": "/!", "headers": {"mid": generate_mid()}}))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"heartbeat send failed: {e}")
            return
        await asyncio.sleep(interval)


def build_ack(msg: dict[str, Any]) -> dict[str, Any]:
    """对下行包回 code=200 ack，透传关键 header。"""
    h = msg.get("headers") or {}
    ack: dict[str, Any] = {
        "code": 200,
        "headers": {
            "mid": h.get("mid") or generate_mid(),
            "sid": h.get("sid", ""),
        },
    }
    for k in ("app-key", "ua", "dt"):
        if k in h:
            ack["headers"][k] = h[k]
    return ack


async def send_text(
    ws: ClientConnection, *, myid: str, cid: str, toid: str, text: str
) -> str:
    """发一条文本消息。返回用于追踪的 mid。"""
    return await _send_custom(ws, myid=myid, cid=cid, toid=toid, ctype=1, payload={
        "contentType": 1, "text": {"text": text},
    })


async def send_image(
    ws: ClientConnection,
    *,
    myid: str,
    cid: str,
    toid: str,
    url: str,
    width: int,
    height: int,
) -> str:
    return await _send_custom(ws, myid=myid, cid=cid, toid=toid, ctype=2, payload={
        "contentType": 2,
        "image": {"pics": [{"type": 0, "url": url, "width": width, "height": height}]},
    })


async def _send_custom(
    ws: ClientConnection,
    *,
    myid: str,
    cid: str,
    toid: str,
    ctype: int,
    payload: dict[str, Any],
) -> str:
    mid = generate_mid()
    data_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    msg = {
        "lwp": "/r/MessageSend/sendByReceiverScope",
        "headers": {"mid": mid},
        "body": [
            {
                "uuid": generate_uuid(),
                "cid": f"{cid}@goofish",
                "conversationType": 1,
                "content": {
                    "contentType": 101,
                    "custom": {"type": ctype, "data": data_b64},
                },
                "redPointPolicy": 0,
                "extension": {"extJson": "{}"},
                "ctx": {"appVersion": "1.0", "platform": "web"},
                "mtags": {},
                "msgReadStatusSetting": 1,
            },
            {
                "actualReceivers": [f"{toid}@goofish", f"{myid}@goofish"],
            },
        ],
    }
    await ws.send(json.dumps(msg))
    return mid


async def create_chat(ws: ClientConnection, *, myid: str, toid: str, item_id: str) -> str:
    """创建/复用单聊会话。返回 mid 供回包配对（若需要）。"""
    mid = generate_mid()
    msg = {
        "lwp": "/r/SingleChatConversation/create",
        "headers": {"mid": mid},
        "body": [
            {
                "pairFirst": f"{toid}@goofish",
                "pairSecond": f"{myid}@goofish",
                "bizType": "1",
                "extension": {"itemId": item_id},
                "ctx": {"appVersion": "1.0", "platform": "web"},
            }
        ],
    }
    await ws.send(json.dumps(msg))
    return mid


async def list_user_messages(
    session: Session, cid: str, limit_per_page: int = 20
) -> list[dict[str, Any]]:
    """一次性拉指定会话的历史消息（翻页直到 hasMore=0）。"""
    token = get_access_token(session)
    messages: list[dict[str, Any]] = []
    send_mid = generate_mid()
    req = {
        "lwp": "/r/MessageManager/listUserMessages",
        "headers": {"mid": send_mid},
        "body": [f"{cid}@goofish", False, 9007199254740991, limit_per_page, False],
    }

    async with connect(session) as ws:
        await register(ws, session, token)
        hb = asyncio.create_task(heartbeat_loop(ws))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                with suppress(Exception):
                    await ws.send(json.dumps(build_ack(msg)))

                lwp = msg.get("lwp")
                if lwp == "/s/vulcan":
                    await ws.send(json.dumps(req))
                    continue

                recv_mid = (msg.get("headers") or {}).get("mid", "")
                if recv_mid != send_mid:
                    continue

                body = msg.get("body") or {}
                models = body.get("userMessageModels") or []
                for um in models:
                    try:
                        ext = um["message"]["extension"]
                        data_b64 = um["message"]["content"]["custom"]["data"]
                        payload = json.loads(base64.b64decode(data_b64).decode("utf-8"))
                        messages.insert(0, {
                            "send_user_id": ext.get("senderUserId", ""),
                            "send_user_name": ext.get("reminderTitle", ""),
                            "message": payload,
                        })
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"parse history item failed: {e}")

                has_more = body.get("hasMore") == 1
                if has_more:
                    send_mid = generate_mid()
                    req["headers"]["mid"] = send_mid
                    req["body"][2] = body.get("nextCursor")
                    await ws.send(json.dumps(req))
                else:
                    break
        finally:
            hb.cancel()
    return messages


def _decode_one(raw: str) -> dict[str, Any] | None:
    """三种解码尝试：明文 JSON → base64(JSON) → decrypt。"""
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(base64.b64decode(raw))
    except Exception:  # noqa: BLE001
        pass
    try:
        return json.loads(decrypt(raw))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"decrypt push failed: {e}")
        return None


def extract_push_messages(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 /s/vulcan 推送包。**一帧可能包含多条 push**（实测 32 条/帧很常见）。

    三种编码尝试：明文 JSON / base64(JSON) / decrypt。任一成功即收录。
    """
    try:
        data_list = msg["body"]["syncPushPackage"]["data"]
    except (KeyError, TypeError):
        return []
    if not isinstance(data_list, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data_list:
        if not isinstance(item, dict):
            continue
        decoded = _decode_one(item.get("data", ""))
        if decoded is not None:
            out.append(decoded)
    return out


def extract_push_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """[deprecated 保留] 只取第一条 —— 新代码请用 extract_push_messages。"""
    batch = extract_push_messages(msg)
    return batch[0] if batch else None


def extract_incoming_text(decoded: dict[str, Any]) -> dict[str, Any] | None:
    """从解码后的推送包里提取一条消息事件。

    两种格式兼容：
    - 新 web 端（base64(JSON)）：顶层有 operation.content.contentType + sessionId
    - 老协议（decrypt 返回）：message["1"]["10"] 挂 reminder*/sender*/cid
    """
    # —— 新格式 ——
    op = decoded.get("operation") if isinstance(decoded, dict) else None
    if isinstance(op, dict):
        content = op.get("content") or {}
        content_type = content.get("contentType")
        sess = op.get("sessionInfo") or {}
        sender = op.get("senderInfo") or {}
        reminder = content.get("reminder") or {}
        cid = str(decoded.get("sessionId") or sess.get("sessionId") or "")
        # contentType=1 文本；2 图片；8 会话激活；101 是 custom
        text = ""
        if content_type == 1:
            text = (content.get("text") or {}).get("text", "") or reminder.get("reminderContent", "")
        elif content_type == 101:
            # custom 包装：data 是 base64(payload)
            custom = content.get("custom") or {}
            data_b64 = custom.get("data", "")
            if data_b64:
                try:
                    payload = json.loads(base64.b64decode(data_b64))
                    text = (payload.get("text") or {}).get("text", "")
                except Exception:  # noqa: BLE001
                    text = ""
            text = text or reminder.get("reminderContent", "")
        else:
            text = reminder.get("reminderContent", "")

        return {
            "event": "message",
            "cid": cid,
            "content_type": content_type,
            "send_user_id": str(sender.get("senderUserId", "") or reminder.get("senderUserId", "")),
            "send_user_name": reminder.get("reminderTitle", ""),
            "send_message": text,
        }

    # —— 老格式（decrypt 后嵌套带正文）——
    one = decoded.get("1") if isinstance(decoded, dict) else None
    if isinstance(one, dict):
        node = one.get("10")
        if isinstance(node, dict):
            cid_full = one.get("2", "")
            cid = cid_full.split("@")[0] if isinstance(cid_full, str) else ""
            return {
                "event": "message",
                "cid": cid,
                "send_user_id": node.get("senderUserId", ""),
                "send_user_name": node.get("reminderTitle", ""),
                "send_message": node.get("reminderContent", ""),
            }

    return None


def extract_meta_event(decoded: dict[str, Any]) -> dict[str, Any] | None:
    """识别 /s/sync 平结构里的元事件：new_msg 通知 / read receipt。

    new_msg 通知（无正文）：{"1":"cid@goofish","2":1,"3":"msgId","4":"ts"}
    read receipt：         {"1":[msgIds],"2":2,"3":"cid@goofish","4":1,"5":"ts"}

    没识别出来返回 None；调用方再尝试 extract_incoming_text。
    """
    if not isinstance(decoded, dict):
        return None
    one, two, three = decoded.get("1"), decoded.get("2"), decoded.get("3")

    # read receipt
    if isinstance(one, list) and two == 2 and isinstance(three, str) and three.endswith("@goofish"):
        return {
            "event": "read",
            "cid": three.split("@")[0],
            "msg_ids": [str(x) for x in one],
            "status": decoded.get("4"),
            "ts": str(decoded.get("5", "")),
        }

    # new_msg 轻量通知（cid 在 "1"，msgId 在 "3"）
    if isinstance(one, str) and one.endswith("@goofish") and two == 1 and isinstance(three, str):
        return {
            "event": "new_msg",
            "cid": one.split("@")[0],
            "msg_id": three,
            "ts": str(decoded.get("4", "")),
        }

    return None


MessageHandler = Callable[[dict[str, Any], ClientConnection], Awaitable[None]]


async def run_forever(
    session: Session,
    handler: MessageHandler | None = None,
    *,
    refresh_every: float = 600.0,
) -> None:
    """常驻 IM 长连接。每条下行包走 ack，然后丢给 handler。

    handler(msg, ws) —— msg 是 json.loads 后的原始帧；需要业务自己去 extract_push_message。
    refresh_every 秒调一次 mtop.taobao.idlemessage.pc.loginuser.get 保活。

    外层套重连循环：服务端会不定时关连接（观察约每 10~30 分钟一次），
    捕获 ConnectionClosed 后指数退避重连 + 重新 reg。
    """
    from goofish_cli.core.token import refresh_login

    async def _keepalive() -> None:
        while True:
            await asyncio.sleep(refresh_every)
            try:
                refresh_login(session)
                logger.debug("login refreshed")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"login refresh failed: {e}")

    async def _one_session() -> None:
        token = get_access_token(session)
        async with connect(session) as ws:
            await register(ws, session, token)
            hb = asyncio.create_task(heartbeat_loop(ws))
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    with suppress(Exception):
                        await ws.send(json.dumps(build_ack(msg)))
                    if handler is not None:
                        try:
                            await handler(msg, ws)
                        except Exception as e:  # noqa: BLE001
                            logger.exception(f"handler error: {e}")
            finally:
                hb.cancel()

    ka = asyncio.create_task(_keepalive())
    backoff = 1.0
    try:
        while True:
            try:
                logger.info("WS 连接中…")
                await _one_session()
                logger.info("WS 正常退出，3s 后重连")
                backoff = 1.0
                await asyncio.sleep(3)
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WS 断连：{e}；{backoff:.1f}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception(f"WS 会话异常：{e}；{backoff:.1f}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
    finally:
        ka.cancel()
