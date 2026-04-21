"""ws 模块的纯解码/编码逻辑（不连 WebSocket）。"""

import base64
import json

from goofish_cli.core.ws import (
    build_ack,
    extract_incoming_text,
    extract_meta_event,
    extract_push_message,
)


def _wrap(data_str: str) -> dict:
    return {
        "headers": {"mid": "m1", "sid": "s1"},
        "lwp": "/s/para",
        "body": {"syncPushPackage": {"data": [{"data": data_str}]}},
    }


def test_extract_push_plain_json():
    payload = {"chatType": 1, "sessionId": "999"}
    msg = _wrap(json.dumps(payload))
    assert extract_push_message(msg) == payload


def test_extract_push_base64_json():
    """闲鱼 web 端新格式：data 字段是 base64(JSON)。防回归 —— 必须能识别。"""
    payload = {"operation": {"content": {"contentType": 1, "text": {"text": "你好"}}},
               "sessionId": "88888"}
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    msg = _wrap(b64)
    out = extract_push_message(msg)
    assert out == payload


def test_extract_push_missing_path():
    assert extract_push_message({"headers": {}, "body": {}}) is None


def test_incoming_text_new_format():
    decoded = {
        "sessionId": "12345",
        "operation": {
            "content": {
                "contentType": 1,
                "text": {"text": "可以砍价吗"},
                "reminder": {"reminderTitle": "小号昵称", "reminderContent": "可以砍价吗"},
            },
            "senderInfo": {"senderUserId": "2217372889946"},
        },
    }
    got = extract_incoming_text(decoded)
    assert got == {
        "event": "message",
        "cid": "12345",
        "content_type": 1,
        "send_user_id": "2217372889946",
        "send_user_name": "小号昵称",
        "send_message": "可以砍价吗",
    }


def test_incoming_text_custom_wrapped():
    """contentType=101 时 text 藏在 custom.data（base64 JSON）里。"""
    inner = {"contentType": 1, "text": {"text": "hi"}}
    custom_b64 = base64.b64encode(json.dumps(inner).encode()).decode()
    decoded = {
        "sessionId": "999",
        "operation": {
            "content": {"contentType": 101, "custom": {"type": 1, "data": custom_b64}},
            "senderInfo": {"senderUserId": "u1"},
        },
    }
    got = extract_incoming_text(decoded)
    assert got["send_message"] == "hi"
    assert got["content_type"] == 101


def test_incoming_text_legacy_format():
    decoded = {"1": {"2": "6666@goofish", "10": {
        "senderUserId": "u9", "reminderTitle": "n", "reminderContent": "t",
    }}}
    got = extract_incoming_text(decoded)
    assert got == {
        "event": "message", "cid": "6666",
        "send_user_id": "u9", "send_user_name": "n", "send_message": "t",
    }


def test_meta_event_read_receipt():
    """{"1":[msgIds],"2":2,"3":"cid@goofish","4":1,"5":"ts"} → 已读回执。"""
    decoded = {
        "1": ["4066826134477.PNM", "4066820235744.PNM"],
        "2": 2, "3": "60585751957@goofish", "4": 1, "5": "1776770736198",
    }
    got = extract_meta_event(decoded)
    assert got == {
        "event": "read", "cid": "60585751957",
        "msg_ids": ["4066826134477.PNM", "4066820235744.PNM"],
        "status": 1, "ts": "1776770736198",
    }


def test_meta_event_new_msg_notification():
    """{"1":"cid@goofish","2":1,"3":"msgId","4":"ts"} → 新消息轻量通知（无正文）。"""
    decoded = {"1": "60585751957@goofish", "2": 1, "3": "4077151514478.PNM", "4": "1776770736064"}
    got = extract_meta_event(decoded)
    assert got == {
        "event": "new_msg", "cid": "60585751957",
        "msg_id": "4077151514478.PNM", "ts": "1776770736064",
    }


def test_meta_event_skip_nested():
    """嵌套带正文的不应被 meta_event 误判。"""
    decoded = {"1": {"2": "6666@goofish", "10": {"reminderContent": "t"}}}
    assert extract_meta_event(decoded) is None


def test_build_ack_passthrough():
    msg = {"headers": {"mid": "M", "sid": "S", "app-key": "K", "ua": "U", "dt": "j"},
           "body": {}}
    ack = build_ack(msg)
    assert ack["code"] == 200
    assert ack["headers"] == {"mid": "M", "sid": "S", "app-key": "K", "ua": "U", "dt": "j"}
