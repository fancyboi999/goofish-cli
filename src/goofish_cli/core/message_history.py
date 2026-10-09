"""消息页读取：复用已就绪的连接，保留身份、消息 ID 和活动时间。"""

from __future__ import annotations

import asyncio
import base64
import json
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from websockets.exceptions import ConnectionClosed, InvalidHandshake

from goofish_cli.core.errors import GoofishError
from goofish_cli.core.session import Session
from goofish_cli.core.sign import generate_mid
from goofish_cli.core.token import get_access_token
from goofish_cli.core.ws import connect, heartbeat_loop, recv_ack, register, wait_ready


def normalize_id(value: Any) -> str:
    """LWP 与 HTTP 使用同一不带域后缀的标识。"""
    return str(value or "").removesuffix("@goofish").strip()


def timestamp(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if result > 0 else None


def parse_message(model: dict[str, Any], cid: str) -> dict[str, Any]:
    if not isinstance(model, dict) or not isinstance(model.get("message"), dict):
        raise GoofishError("消息记录缺少 message 对象")
    message = model.get("message") or {}
    extension = message.get("extension") or {}
    content = message.get("content") or {}
    if not isinstance(extension, dict) or not isinstance(content, dict):
        raise GoofishError("消息扩展或正文格式无效")
    payload = content
    parse_error = ""
    custom = content.get("custom") or {}
    if not isinstance(custom, dict):
        raise GoofishError("消息 custom 正文格式无效")
    if custom.get("data"):
        try:
            payload = json.loads(base64.b64decode(custom["data"]))
        except (ValueError, TypeError, UnicodeDecodeError):
            payload = {
                "contentType": content.get("contentType"),
                "summary": custom.get("summary", ""),
            }
            parse_error = "消息正文无法解码"
    sender = message.get("sender") or {}
    receivers = message.get("receivers") or []
    if not isinstance(sender, dict) or not isinstance(receivers, list):
        raise GoofishError("消息参加者格式无效")
    result = {
        "cid": normalize_id(message.get("cid")) or cid,
        "message_id": str(message.get("messageId") or ""),
        "created_at": timestamp(message.get("createAt")),
        "session_type": timestamp(extension.get("sessionType")),
        "send_user_id": normalize_id(extension.get("senderUserId") or sender.get("uid")),
        "send_user_name": extension.get("reminderTitle", ""),
        "receiver_user_ids": [
            normalize_id(r.get("uid") if isinstance(r, dict) else r) for r in receivers
        ],
        "message": payload,
    }
    if parse_error:
        result["parse_error"] = parse_error
    return result


@asynccontextmanager
async def history_connection(session: Session) -> AsyncIterator[Any]:
    token = get_access_token(session)
    async with connect(session) as ws:
        mids = await register(ws, session, token)
        heartbeat = asyncio.create_task(heartbeat_loop(ws))
        try:
            if not await wait_ready(ws, mids=mids):
                raise GoofishError("IM 消息读取连接未就绪")
            yield ws
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat


async def read_page(ws: Any, cid: str, cursor: Any, page_size: int) -> dict[str, Any]:
    mid = generate_mid()
    await ws.send(
        json.dumps(
            {
                "lwp": "/r/MessageManager/listUserMessages",
                "headers": {"mid": mid},
                "body": [f"{cid}@goofish", False, cursor, page_size, False],
            }
        )
    )
    ack = await recv_ack(ws, mid, timeout=10.0)
    if ack is None:
        raise GoofishError("读取消息页超时")
    if ack.get("code") != 200:
        raise GoofishError(f"读取消息页被拒绝：code={ack.get('code')}")
    body = ack.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("userMessageModels"), list):
        raise GoofishError("消息页响应缺少 userMessageModels")
    return body


async def read_history(
    session: Session, cid: str, page_size: int = 20, limit: int = 0, timeout: float = 30.0
) -> list[dict[str, Any]]:
    cid = normalize_id(cid)
    if not cid or "@" in cid:
        raise GoofishError("cid 必须是有效会话标识")
    if not 1 <= page_size <= 100 or limit < 0 or timeout <= 0 or not math.isfinite(timeout):
        raise GoofishError("limit-per-page 必须为 1–100，limit 不得为负，timeout 必须大于 0")
    messages: dict[str | tuple[str, int], dict[str, Any]] = {}
    cursor: Any = 9007199254740991
    cursors: set[str] = set()
    try:
        async with asyncio.timeout(timeout), history_connection(session) as ws:
            while True:
                if str(cursor) in cursors:
                    raise GoofishError("消息分页游标没有推进")
                cursors.add(str(cursor))
                count = min(page_size, limit - len(messages)) if limit else page_size
                body = await read_page(ws, cid, cursor, count)
                for model in body["userMessageModels"]:
                    item = parse_message(model, cid)
                    # 缺少服务端 ID 时保留每次出现，不能以相同正文/时间推断同一消息。
                    key = item["message_id"] or ("missing_id", len(messages))
                    messages[key] = item
                if (limit and len(messages) >= limit) or body.get("hasMore") not in (1, "1", True):
                    break
                cursor = body.get("nextCursor")
                if cursor is None or not body["userMessageModels"]:
                    raise GoofishError("消息分页声称有下一页，但没有有效游标或消息")
    except TimeoutError as exc:
        raise GoofishError("读取会话历史超时，可增大 --timeout 或使用 --limit") from exc
    except (ConnectionClosed, OSError, InvalidHandshake) as exc:
        raise GoofishError(f"IM 消息连接失败或中断：{type(exc).__name__}") from None
    ordered = sorted(messages.values(), key=lambda m: m["created_at"] or 0)
    return ordered[-limit:] if limit else ordered


async def recent_messages(
    session: Session, cids: list[str], timeout: float = 30.0
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """单连接逐会话取最近一页；失败保留已读摘要，并明确未完成的会话。"""
    histories: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    pending = list(dict.fromkeys(normalize_id(cid) for cid in cids))
    if not pending:
        return histories, errors
    try:
        async with asyncio.timeout(timeout), history_connection(session) as ws:
            for cid in pending:
                try:
                    body = await read_page(ws, cid, 9007199254740991, 20)
                    histories[cid] = [parse_message(m, cid) for m in body["userMessageModels"]]
                except GoofishError as exc:
                    errors[cid] = str(exc)
    except (TimeoutError, ConnectionClosed, OSError, InvalidHandshake, GoofishError) as exc:
        reason = str(exc) if isinstance(exc, GoofishError) else "会话摘要读取超时或连接断开"
        errors.update(
            {cid: reason for cid in pending if cid not in histories and cid not in errors}
        )
    return histories, errors
