"""验 message list-chats 的 session 结构解析。"""

from __future__ import annotations

from goofish_cli.commands.message.list_chats import _parse_session, _watch_record


def test_parse_session_full():
    raw = {
        "memberFlags": 0,
        "message": {
            "summary": {
                "sortIndex": 20260421220018,
                "summary": "在吗？这个还在卖吗",
                "ts": 1776780018537,
                "unread": 2,
                "version": 10363,
            }
        },
        "session": {
            "ownerInfo": {"userId": "test-owner", "nick": "x***2"},
            "sessionId": "test-cid",
            "sessionType": 1,
            "targetId": "1300",
            "userInfo": {
                "fishNick": "小号昵称",
                "logo": "https://x.png",
                "nick": "test-peer",
                "type": 0,
                "userId": "test-user",
            },
        },
    }
    out = _parse_session(raw)
    assert out["session_id"] == "test-cid"
    assert out["peer_nick"] == "test-peer"
    assert out["peer_user_id"] == "test-user"
    assert out["unread"] == 2
    assert out["last_msg"] == "在吗？这个还在卖吗"
    assert out["ts"] == 1776780018537
    assert out["session_type"] == 1
    assert out["source"] == "baseline"
    assert out["item_id"] == ""


def test_parse_session_falls_back_to_fish_nick():
    raw = {
        "session": {
            "sessionId": 123,
            "userInfo": {"fishNick": "鱼小铺", "userId": "9"},
        },
        "message": {"summary": {"summary": "通知"}},
    }
    out = _parse_session(raw)
    assert out["peer_nick"] == "鱼小铺"
    assert out["peer_user_id"] == "9"


def test_parse_session_missing_fields_defaults():
    out = _parse_session({})
    assert out["ts"] is None
    assert out["peer_user_id"] == ""


def test_parse_session_null_summary():
    raw = {
        "session": {"sessionId": 42, "userInfo": {"nick": "x", "userId": "1"}},
        "message": {"summary": None},
    }
    out = _parse_session(raw)
    assert out["session_id"] == "42"
    assert out["last_msg"] == ""
    assert out["unread"] == 0


def test_watch_record_shape():
    out = _watch_record(
        {
            "cid": "test-cid",
            "session_type": 1,
            "peer_user_id": "test-user",
            "item_id": "900123",
            "last_msg_id": "msg-x",
            "last_msg_ts": "1776780018537",
        }
    )
    assert out["session_id"] == "test-cid"
    assert out["peer_user_id"] == "test-user"
    assert out["item_id"] == "900123"
    assert out["session_type"] == 1
    assert out["ts"] == 1776780018537
    assert out["source"] == "watch"
    assert out["peer_nick"] == ""
    assert out["last_msg"] == ""


def test_watch_record_missing_activity_time_is_unknown():
    out = _watch_record({"cid": "123"})
    assert out["ts"] is None
    assert out["source"] == "watch"
