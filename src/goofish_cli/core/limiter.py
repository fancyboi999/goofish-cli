"""账号与业务桶限流，锁住读取/检查/写入事务，写尝试失败不退还预算。"""
from __future__ import annotations

import hashlib
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

from goofish_cli.core.errors import GoofishError, RateLimitedError
from goofish_cli.core.local_state import locked_state

STATE_PATH = Path.home() / ".goofish-cli" / "limiter.json"
DEFAULT_WRITE_RPM = 1
DEFAULT_MEDIA_RPM = 9


def _rpm(bucket: str = "") -> int:
    variable = "GOOFISH_MEDIA_WRITE_RPM" if bucket == "media.write" else "GOOFISH_WRITE_RPM"
    default = DEFAULT_MEDIA_RPM if bucket == "media.write" else DEFAULT_WRITE_RPM
    try:
        return max(1, int(os.environ.get(variable, default)))
    except ValueError:
        return default


def check(bucket: str, *, account: str = "") -> None:
    window = 60.0
    rpm = _rpm(bucket)
    path = Path(os.environ.get("GOOFISH_LIMITER_PATH", str(STATE_PATH))).expanduser()
    key = f"account/{hashlib.sha256(account.encode()).hexdigest()}/{bucket}" if account else bucket
    with locked_state(path) as state:
        now = time.time()
        for name, values in state.items():
            if not isinstance(name, str) or not isinstance(values, list) or any(
                isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or value < 0 for value in values
            ):
                raise GoofishError("限流状态格式无效；未清空预算，未发起写请求")
        hits = [t for t in state.get(key, []) if now - t < window]
        # 旧版没有账号字段，最近的共享预算仍须自然过期，不能借升级绕过。
        legacy = [t for t in state.get(bucket, []) if now - t < window] if account else []
        active = sorted(hits + legacy)
        if len(active) >= rpm:
            wait = max(0, window - (now - active[0]))
            error = RateLimitedError(f"限流：bucket={bucket} 每 {window:.0f}s 上限 {rpm}，再等 {wait:.1f}s")
            error.retry_after = wait
            raise error
        state[key] = hits + [now]


@contextmanager
def acquire(bucket: str, *, account: str = ""):
    check(bucket, account=account)
    yield
