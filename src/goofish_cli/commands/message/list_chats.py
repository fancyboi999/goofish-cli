"""message list-chats — 拉取会话列表（左栏）。

h5 接口 `mtop.taobao.idlemessage.pc.session.sync` v3.0 是阉割版，只返回活跃
Top N 会话；网页左栏看到的完整列表其实是靠 ACCS 长连累积的，单次 HTTP 拿不到。
所以提供 `--watch-secs N` 可选开关：短时连 WS + `ackDiff(pts=0)` 拉历史推送，
从中抽取会话激活事件 + new_msg 通知里的 cid，补齐 baseline 漏掉的会话。

数据来源两路合并：

1. `mtop.taobao.idlemessage.pc.session.sync` v3.0 —— baseline，字段齐全
   （peer_nick / peer_user_id / unread / last_msg / ts / session_type / item_id）。
2. `--watch-secs N`（可选）—— watch，只有 cid 骨架
   （session_id / session_type / item_id / ts），`peer_nick` / `peer_user_id` /
   `last_msg` / `unread` 都填空值。要正文请自己调 `message history <cid>`。

输出 record 带 `source` 字段区分 `baseline` 和 `watch`，shape 一致，方便调用方统一处理。
"""

import asyncio
from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.mtop import call


def _pick(d: dict[str, Any], *path: str, default: Any = "") -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _parse_session(item: dict[str, Any]) -> dict[str, Any]:
    session = item.get("session") or {}
    user_info = session.get("userInfo") or {}
    summary = _pick(item, "message", "summary", default={}) or {}
    return {
        "session_id": str(session.get("sessionId", "")),
        "peer_nick": user_info.get("nick", "") or user_info.get("fishNick", ""),
        "peer_user_id": str(user_info.get("userId", "")),
        "unread": summary.get("unread", 0),
        "last_msg": summary.get("summary", ""),
        "ts": summary.get("ts", 0),
        "session_type": session.get("sessionType", 0),
        "item_id": "",
        "source": "baseline",
    }


def _watch_record(w: dict[str, Any]) -> dict[str, Any]:
    """把 WS 收集到的裸 cid 包成跟 baseline 同形状的 record。"""
    ts_raw = w.get("last_msg_ts") or 0
    try:
        ts = int(ts_raw)
    except (TypeError, ValueError):
        ts = 0
    return {
        "session_id": str(w["cid"]),
        "peer_nick": "",
        "peer_user_id": str(w.get("peer_user_id", "")),
        "unread": 0,
        "last_msg": "",
        "ts": ts,
        "session_type": int(w.get("session_type") or 0),
        "item_id": str(w.get("item_id", "")),
        "source": "watch",
    }


@command(
    namespace="message",
    name="list-chats",
    description="拉取会话列表（左栏）：session.sync 基线 + 可选 WS 增量补 cid",
    strategy=Strategy.COOKIE,
    columns=[
        "session_id", "peer_nick", "peer_user_id",
        "unread", "last_msg", "ts", "source",
    ],
)
def list_chats(fetch_num: int = 50, watch_secs: float = 0.0) -> dict[str, Any]:
    session = Session.load()
    raw = call(
        session,
        api="mtop.taobao.idlemessage.pc.session.sync",
        data={"fetchNum": int(fetch_num)},
        version="3.0",
        spm_cnt="a21ybx.im.0.0",
    )
    data = raw.get("data") or {}
    baseline = [_parse_session(s) for s in data.get("sessions") or []]
    known = {b["session_id"] for b in baseline}

    extras: list[dict[str, Any]] = []
    if watch_secs > 0:
        from goofish_cli.core.ws import collect_session_cids

        pushed = asyncio.run(collect_session_cids(session, duration=float(watch_secs)))
        extras = [_watch_record(w) for w in pushed if str(w["cid"]) not in known]

    return {
        "sessions": baseline + extras,
        "has_more": bool(data.get("hasMore")),
        "total": len(baseline) + len(extras),
        "from_baseline": len(baseline),
        "from_watch": len(extras),
    }
