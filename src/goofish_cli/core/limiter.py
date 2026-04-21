"""令牌桶限流。单账号 + 单命名空间，默认 1 写/分钟（可配）。

写入 ~/.goofish-cli/limiter.json 做进程间共享（单机多进程场景）。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from goofish_cli.core.errors import RateLimitedError

STATE_PATH = Path.home() / ".goofish-cli" / "limiter.json"
DEFAULT_WRITE_RPM = 1


def _rpm() -> int:
    try:
        return max(1, int(os.environ.get("GOOFISH_WRITE_RPM", DEFAULT_WRITE_RPM)))
    except ValueError:
        return DEFAULT_WRITE_RPM


def _load() -> dict[str, list[float]]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: dict[str, list[float]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def check(bucket: str) -> None:
    """消耗一个令牌。超限抛 RateLimitedError。"""
    now = time.time()
    window = 60.0
    rpm = _rpm()
    state = _load()
    hits = [t for t in state.get(bucket, []) if now - t < window]
    if len(hits) >= rpm:
        wait = window - (now - hits[0])
        raise RateLimitedError(
            f"限流：bucket={bucket} 每 {window:.0f}s 上限 {rpm}，再等 {wait:.1f}s"
        )
    hits.append(now)
    state[bucket] = hits
    _save(state)


@contextmanager
def acquire(bucket: str):
    check(bucket)
    yield
