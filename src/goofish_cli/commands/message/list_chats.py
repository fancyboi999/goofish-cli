"""合并 HTTP 与有界 WS 会话发现，读取最近消息后按真实活动时间排序。"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from websockets.exceptions import ConnectionClosed, InvalidHandshake

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.message_history import normalize_id, recent_messages, timestamp
from goofish_cli.core.mtop import call
from goofish_cli.core.ws import collect_session_cids


def _parse_session(item: dict[str, Any], myid: str = "") -> dict[str, Any]:
    session = item.get("session") or {}
    user_info = session.get("userInfo") or {}
    if myid and session.get("sessionType") == 1:
        people = [user_info, session.get("ownerInfo") or {}]
        peers = {
            normalize_id(p.get("userId")): p
            for p in people
            if p.get("userId") and normalize_id(p["userId"]) != myid
        }
        user_info = next(iter(peers.values())) if len(peers) == 1 else {}
    summary = (item.get("message") or {}).get("summary") or {}
    return {
        "session_id": normalize_id(session.get("sessionId")),
        "peer_nick": user_info.get("nick", "") or user_info.get("fishNick", ""),
        "peer_user_id": normalize_id(user_info.get("userId")),
        "unread": summary.get("unread", 0),
        "last_msg": summary.get("summary", ""),
        "ts": timestamp(summary.get("ts")),
        "session_type": session.get("sessionType", 0),
        "item_id": "",
        "message_id": "",
        "source": "baseline",
        "metadata_status": "http",
    }


def _watch_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": normalize_id(item["cid"]),
        "peer_nick": "",
        "peer_user_id": normalize_id(item.get("peer_user_id")),
        "unread": None,
        "last_msg": "",
        "ts": timestamp(item.get("last_msg_ts")),
        "session_type": int(item.get("session_type") or 0),
        "item_id": str(item.get("item_id") or ""),
        "message_id": str(item.get("last_msg_id") or ""),
        "source": "watch",
        "metadata_status": "pending",
    }


def _preview(message: Any) -> str:
    if not isinstance(message, dict):
        return str(message or "")
    text = message.get("text") or {}
    if isinstance(text, dict) and text.get("text"):
        return str(text["text"])
    if message.get("contentType") == 2:
        return "[图片]"
    return str(message.get("summary") or "[非文本消息]")


def _enrich(
    row: dict[str, Any], messages: list[dict[str, Any]], participants: list[str], myid: str
) -> None:
    if not messages:
        row.update(metadata_status="empty", ts=None, last_msg="", message_id="")
        if row["peer_user_id"] == myid:
            row.update(peer_user_id="", peer_nick="")
        missing = [key for key in ("peer_user_id", "peer_nick") if not row[key]]
        if missing:
            row.update(metadata_status="partial", metadata_missing=missing)
        return
    latest = max(messages, key=lambda m: m["created_at"] or 0)
    row.update(
        ts=latest["created_at"],
        message_id=latest["message_id"],
        last_msg=_preview(latest["message"]),
        metadata_status="current",
    )
    if row["session_type"] == 0 and latest.get("session_type"):
        row["session_type"] = latest["session_type"]
    if row["session_type"] not in (0, 1):
        row["metadata_status"] = "system"
        return
    members = {normalize_id(value) for value in participants if value}
    peers = members - {myid} if myid in members else set()
    if row["peer_user_id"] and row["peer_user_id"] != myid:
        peers.add(row["peer_user_id"])
    if not peers:
        peers = {
            m["send_user_id"] for m in messages if m["send_user_id"] and m["send_user_id"] != myid
        }
        peers.update(uid for m in messages for uid in m["receiver_user_ids"] if uid and uid != myid)
    if len(peers) == 1:
        peer = next(iter(peers))
        row["peer_user_id"] = peer
        labels = [
            m
            for m in messages
            if m["send_user_id"] == peer
            and m["send_user_name"]
            and isinstance(m["message"], dict)
            and m["message"].get("contentType") in (1, 2)
        ]
        if labels:
            row["peer_nick"] = max(labels, key=lambda m: m["created_at"] or 0)["send_user_name"]
    else:
        row["peer_user_id"] = ""
        row["peer_nick"] = ""
    missing = [key for key in ("ts", "message_id", "peer_user_id", "peer_nick") if not row[key]]
    if latest.get("parse_error"):
        missing.append("message_content")
    if missing:
        row.update(metadata_status="partial", metadata_missing=missing)


async def _snapshot(
    session: Session, baseline: list[dict[str, Any]], watch_secs: float, timeout: float
) -> tuple[list[dict[str, Any]], int, list[dict[str, str]]]:
    records = {row["session_id"]: row for row in baseline if row["session_id"]}
    participants: dict[str, list[str]] = {}
    errors: list[dict[str, str]] = []
    discovered = 0
    if watch_secs:
        try:
            async with asyncio.timeout(watch_secs + 15):
                pushed = await collect_session_cids(session, duration=watch_secs)
            for item in pushed:
                cid = normalize_id(item["cid"])
                if not cid:
                    continue
                participants[cid] = item.get("participant_user_ids", [])
                if cid not in records:
                    records[cid] = _watch_record(item)
                    discovered += 1
                else:
                    records[cid]["source"] = "baseline+watch"
                    if item.get("item_id"):
                        records[cid]["item_id"] = str(item["item_id"])
        except (TimeoutError, ConnectionClosed, OSError, InvalidHandshake) as exc:
            errors.append({"stage": "discovery", "error": type(exc).__name__})

    cids = [cid for cid, row in records.items() if row["session_type"] in (0, 1)]
    for row in records.values():
        if row["source"] == "watch" and row["session_type"] not in (0, 1):
            row["metadata_status"] = "system"
    cids.sort(key=lambda cid: "watch" not in records[cid]["source"])
    histories, failures = await recent_messages(session, cids, timeout=timeout)
    for cid in cids:
        if cid in failures:
            records[cid]["metadata_status"] = "stale"
            errors.append({"stage": "recent_message", "session_id": cid, "error": failures[cid]})
        else:
            _enrich(records[cid], histories[cid], participants.get(cid, []), session.unb)
    rows = sorted(records.values(), key=lambda r: (r["ts"] or 0, r["session_id"]), reverse=True)
    return rows, discovered, errors


@command(
    namespace="message",
    name="list-chats",
    description="会话列表：HTTP + 默认短时 WS 发现，最近消息补齐并按活动时间倒序",
    strategy=Strategy.COOKIE,
    columns=[
        "session_id",
        "peer_nick",
        "peer_user_id",
        "unread",
        "last_msg",
        "ts",
        "source",
        "metadata_status",
    ],
)
def list_chats(
    fetch_num: int = 50, watch_secs: float = 5.0, timeout: float = 30.0
) -> dict[str, Any]:
    if (
        fetch_num < 1
        or watch_secs < 0
        or timeout <= 0
        or not math.isfinite(watch_secs)
        or not math.isfinite(timeout)
    ):
        raise GoofishError("fetch-num 和 timeout 必须大于 0，watch-secs 不得为负")
    session = Session.load()
    try:
        raw = call(
            session,
            api="mtop.taobao.idlemessage.pc.session.sync",
            data={"fetchNum": fetch_num},
            version="3.0",
            spm_cnt="a21ybx.im.0.0",
        )
    except OSError as exc:
        raise GoofishError(f"HTTP 会话基线连接失败：{type(exc).__name__}") from None
    data = raw.get("data") or {}
    baseline = [_parse_session(item, session.unb) for item in data.get("sessions") or []]
    rows, discovered, errors = asyncio.run(_snapshot(session, baseline, watch_secs, timeout))
    return {
        "sessions": rows,
        "has_more": bool(data.get("hasMore")),
        "has_more_scope": "http",
        "total": len(rows),
        "from_baseline": len(baseline),
        "from_watch": discovered,
        "ws_enabled": watch_secs > 0,
        "enumeration_complete": False,
        "enumeration_note": "HTTP 与短时 WS 是有界会话发现，不能保证覆盖所有历史会话",
        "metadata_complete": not errors
        and all(r["metadata_status"] not in ("pending", "partial", "stale") for r in rows),
        "metadata_scope": "personal_and_unclassified",
        "metadata_errors": errors,
        "unknown_activity_count": sum(r["ts"] is None for r in rows),
    }
