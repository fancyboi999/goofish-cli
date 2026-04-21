"""验风控熔断 watch() 上下文：触发 RGV587 后后续请求立即拒绝。"""
from __future__ import annotations

import pytest


def test_watch_trips_on_risk(tmp_path, monkeypatch):
    monkeypatch.setattr("goofish_cli.core.guard.STATE_PATH", tmp_path / "circuit.json")
    monkeypatch.setenv("GOOFISH_CIRCUIT_BREAK_MINUTES", "60")

    from goofish_cli.core import guard
    from goofish_cli.core.errors import RiskControlError

    # 第一次：上下文内抛 RiskControl → 自动熔断
    with pytest.raises(RiskControlError), guard.watch():
        raise RiskControlError("RGV587_ERROR::SM::test")

    # 第二次：进入 watch 即被 check() 拒绝
    with pytest.raises(RiskControlError), guard.watch():
        pass


def test_reset_clears_circuit(tmp_path, monkeypatch):
    monkeypatch.setattr("goofish_cli.core.guard.STATE_PATH", tmp_path / "circuit.json")

    from goofish_cli.core import guard

    guard.trip("test")
    assert guard._load() > 0
    guard.reset()
    assert guard._load() == 0
    # reset 后 watch 不再抛
    with guard.watch():
        pass


def test_classify_risk_via_mtop():
    """mtop._classify_error 命中风控关键字时抛 RiskControlError。"""
    from goofish_cli.core.errors import RiskControlError
    from goofish_cli.core.mtop import _classify_error

    with pytest.raises(RiskControlError):
        _classify_error(
            {"ret": ["FAIL_SYS_USER_VALIDATE::哎哟喂,被挤爆啦"]},
            "mtop.test",
        )
