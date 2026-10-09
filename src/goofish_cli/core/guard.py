"""账号熔断状态原子持久化；旧共享熔断自然过期，手动重置只改变本机状态。"""
from __future__ import annotations

import hashlib
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

from goofish_cli.core.errors import GoofishError, RiskControlError
from goofish_cli.core.local_state import atomic_write, locked_state

STATE_PATH = Path.home() / ".goofish-cli" / "circuit.json"
DEFAULT_BREAK_MINUTES = 10


def _path() -> Path:
    return Path(os.environ.get("GOOFISH_GUARD_PATH", str(STATE_PATH))).expanduser()


def _break_seconds() -> int:
    try:
        return max(60, int(os.environ.get("GOOFISH_CIRCUIT_BREAK_MINUTES", DEFAULT_BREAK_MINUTES)) * 60)
    except ValueError:
        return DEFAULT_BREAK_MINUTES * 60


def _key(account: str) -> str:
    return hashlib.sha256(account.encode()).hexdigest()


def _validate(state: dict) -> None:
    values = state.get("accounts", {})
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise GoofishError("熔断状态格式无效，未清空状态")
    for value in [state.get("until", 0), *values.values()]:
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise GoofishError("熔断时间格式无效，未发起写请求")


def check(*, account: str = "") -> None:
    with locked_state(_path()) as state:
        _validate(state)
        until = max(state.get("until", 0), state.get("accounts", {}).get(_key(account), 0))
        if until and time.time() < until:
            remain = max(1, int(until - time.time()))
            raise RiskControlError(f"风控熔断中，剩余 {remain}s。等待冷却或由操作者检查后使用 auth reset-guard。")


def trip(reason: str = "", *, account: str = "") -> None:
    with locked_state(_path()) as state:
        _validate(state)
        until = time.time() + _break_seconds()
        if account:
            state.setdefault("accounts", {})[_key(account)] = until
        else:
            state["until"] = until


def reset() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=5, mode=0o600):
        atomic_write(path, {})


@contextmanager
def watch(*, account: str = ""):
    check(account=account)
    try:
        yield
    except RiskControlError as exc:
        try:
            trip(account=account)
        except GoofishError:
            exc.args = (str(exc) + "；本机熔断未能持久化，请停止写入并检查护栏目录",)
        raise
