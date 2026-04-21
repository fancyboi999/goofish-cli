"""验令牌桶限流：达到上限抛 RateLimitedError。"""
from __future__ import annotations


def test_rate_limited(tmp_path, monkeypatch):
    # 隔离 state 到 tmp
    monkeypatch.setattr("goofish_cli.core.limiter.STATE_PATH", tmp_path / "limiter.json")
    monkeypatch.setenv("GOOFISH_WRITE_RPM", "2")

    from goofish_cli.core import limiter
    from goofish_cli.core.errors import RateLimitedError

    limiter.check("test")
    limiter.check("test")
    try:
        limiter.check("test")
    except RateLimitedError:
        return
    raise AssertionError("第 3 次应该被限流")


def test_different_buckets_independent(tmp_path, monkeypatch):
    monkeypatch.setattr("goofish_cli.core.limiter.STATE_PATH", tmp_path / "limiter.json")
    monkeypatch.setenv("GOOFISH_WRITE_RPM", "1")

    from goofish_cli.core import limiter

    limiter.check("a")
    limiter.check("b")  # 不同 bucket 不受影响
