"""订单发货纯逻辑单测：返回码分类、秘钥池、内容模板、先标记后发内容决策。"""

import pytest

from goofish_cli.core.order import (
    build_message,
    classify_consign_ret,
    delivery_step,
    mark_succeeded,
    pop_key,
)


def test_classify_success():
    assert classify_consign_ret("SUCCESS::调用成功") == "success"
    assert mark_succeeded("success") is True


def test_classify_already_delivered_is_idempotent_success():
    assert classify_consign_ret("ORDER_ALREADY_DELIVERY") == "already_delivered"
    assert mark_succeeded("already_delivered") is True


def test_classify_token_expired():
    assert classify_consign_ret("FAIL_SYS_TOKEN_EXPIRED::xxx") == "token_expired"
    assert classify_consign_ret("FAIL_SYS_TOKEN_EXOIRED::xxx") == "token_expired"
    assert mark_succeeded("token_expired") is False


def test_classify_failed():
    assert classify_consign_ret("FAIL_SYS_ORDER_NOT_FOUND") == "failed"
    assert classify_consign_ret("") == "failed"


def test_pop_key_drains_pool(tmp_path):
    pool = tmp_path / "keys.txt"
    pool.write_text("KEY-1\nKEY-2\n", encoding="utf-8")
    assert pop_key(pool) == "KEY-1"
    assert pop_key(pool) == "KEY-2"
    assert pop_key(pool) is None
    assert pool.read_text(encoding="utf-8") == ""


def test_pop_key_missing_returns_none(tmp_path):
    assert pop_key(tmp_path / "nope.txt") is None


def test_build_message_fixed():
    assert build_message({"mode": "fixed", "fixed_text": "谢谢惠顾"}) == "谢谢惠顾"


def test_build_message_fixed_empty_errors():
    errors: list[str] = []
    assert build_message({"mode": "fixed", "fixed_text": "  "}, errors) is None
    assert errors


def test_build_message_key_pool_template(tmp_path):
    pool = tmp_path / "keys.txt"
    pool.write_text("ABC-123\n", encoding="utf-8")
    msg = build_message({
        "mode": "key_pool",
        "key_pool_file": str(pool),
        "message_template": "秘钥 {key}，请保存",
    })
    assert msg == "秘钥 ABC-123，请保存"


def test_build_message_unknown_mode():
    errors: list[str] = []
    assert build_message({"mode": "email"}, errors) is None
    assert errors[0].startswith("未知发货模式")


def test_delivery_success_sends_content():
    step = delivery_step("success", "您的秘钥：ABC")
    assert step["action"] == "deliver" and step["send_content"] is True


def test_delivery_already_delivered_still_sends():
    step = delivery_step("already_delivered", "您的秘钥：ABC")
    assert step["action"] == "deliver"


def test_delivery_token_expired_retries_not_sends():
    step = delivery_step("token_expired", "x")
    assert step["action"] == "retry_token" and step["send_content"] is False


def test_delivery_failed_holds_no_content():
    step = delivery_step("failed", "x")
    assert step["action"] == "hold" and step["send_content"] is False


def test_delivery_success_but_empty_message_holds():
    step = delivery_step("success", None)
    assert step["action"] == "hold" and step["send_content"] is False
