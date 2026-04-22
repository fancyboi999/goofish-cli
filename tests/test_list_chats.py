"""验 message list-chats 的 session 结构解析。"""
from __future__ import annotations

from goofish_cli.commands.message.list_chats import _parse_session


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
            "ownerInfo": {"userId": "2214350705775", "nick": "x***2"},
            "sessionId": 60585751957,
            "sessionType": 1,
            "targetId": "1300",
            "userInfo": {
                "fishNick": "小号昵称",
                "logo": "https://x.png",
                "nick": "xy575986224572",
                "type": 0,
                "userId": "2215266653893",
            },
        },
    }
    out = _parse_session(raw)
    assert out["session_id"] == "60585751957"
    assert out["peer_nick"] == "xy575986224572"
    assert out["peer_user_id"] == "2215266653893"
    assert out["unread"] == 2
    assert out["last_msg"] == "在吗？这个还在卖吗"
    assert out["ts"] == 1776780018537
    assert out["session_type"] == 1


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
    assert out == {
        "session_id": "",
        "peer_nick": "",
        "peer_user_id": "",
        "unread": 0,
        "last_msg": "",
        "ts": 0,
        "session_type": 0,
    }


def test_parse_session_null_summary():
    raw = {
        "session": {"sessionId": 42, "userInfo": {"nick": "x", "userId": "1"}},
        "message": {"summary": None},
    }
    out = _parse_session(raw)
    assert out["session_id"] == "42"
    assert out["last_msg"] == ""
    assert out["unread"] == 0
