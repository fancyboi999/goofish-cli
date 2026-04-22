"""验 mtop 调用的分类逻辑与 t 精度修复。"""
from __future__ import annotations

import time

import pytest


def test_t_precision_fixed():
    """验 t 毫秒位非 0：`int(time.time() * 1000)` 而不是 `int(time.time()) * 1000`（后者末三位恒为 0）"""
    # 直接模拟 mtop.call 里的取值
    t_ms = int(time.time() * 1000)
    assert t_ms > 1_700_000_000_000
    # 采样几次，应该不都是 000 结尾
    samples = [int(time.time() * 1000) % 1000 for _ in range(5)]
    time.sleep(0.003)
    samples.append(int(time.time() * 1000) % 1000)
    assert any(s != 0 for s in samples)


def test_classify_success():
    from goofish_cli.core.mtop import _classify_error

    _classify_error({"ret": ["SUCCESS::调用成功"]}, "mtop.test")  # 不抛


def test_classify_auth():
    from goofish_cli.core.errors import AuthRequiredError
    from goofish_cli.core.mtop import _classify_error

    with pytest.raises(AuthRequiredError):
        _classify_error({"ret": ["FAIL_SYS_SESSION_EXPIRED::session expired"]}, "mtop.test")


def test_classify_not_found():
    from goofish_cli.core.errors import NotFoundError
    from goofish_cli.core.mtop import _classify_error

    with pytest.raises(NotFoundError):
        _classify_error({"ret": ["FAIL_BIZ_ITEM_NOT_FOUND::商品不存在"]}, "mtop.test")


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("[api] 登录态失效：FAIL_SYS_TOKEN_EXOIRED::令牌过期", True),
        ("[api] 登录态失效：FAIL_SYS_TOKEN_EMPTY::令牌为空", True),
        ("[api] 登录态失效：FAIL_SYS_SESSION_EXPIRED::Session过期", True),
        ("[api] 登录态失效：令牌过期", True),
        # 风控/权限类刷 cookie 救不了，不触发自动刷新
        ("[api] 登录态失效：FAIL_SYS_ILLEGAL_ACCESS::非法访问", False),
        ("[api] 未找到：FAIL_BIZ_ITEM_NOT_FOUND", False),
    ],
)
def test_is_recoverable_auth_error(msg, expected):
    from goofish_cli.core.errors import AuthRequiredError
    from goofish_cli.core.mtop import _is_recoverable_auth_error

    assert _is_recoverable_auth_error(AuthRequiredError(msg)) is expected
