"""message list-chats — 拉取会话列表（左栏）。

接口：mtop.taobao.idlemessage.pc.session.sync v3.0（只读）。
入参 fetchNum 必填，一次拉 N 条。当前观察到 hasMore 恒为 false，需分页时
再补 cursor 字段。
"""

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
    }


@command(
    namespace="message",
    name="list-chats",
    description="拉取会话列表（左栏），返回 session_id / 对方昵称 / 未读 / 最后消息",
    strategy=Strategy.COOKIE,
    columns=["session_id", "peer_nick", "peer_user_id", "unread", "last_msg", "ts"],
)
def list_chats(fetch_num: int = 50) -> dict[str, Any]:
    session = Session.load()
    raw = call(
        session,
        api="mtop.taobao.idlemessage.pc.session.sync",
        data={"fetchNum": int(fetch_num)},
        version="3.0",
        spm_cnt="a21ybx.im.0.0",
    )
    data = raw.get("data") or {}
    sessions = [_parse_session(s) for s in data.get("sessions") or []]
    return {
        "sessions": sessions,
        "has_more": bool(data.get("hasMore")),
        "total": len(sessions),
    }
