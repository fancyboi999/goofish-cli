"""实际写入口共用护栏：先检查熔断，再占一次账号与业务桶的写预算。"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from goofish_cli.core.guard import watch
from goofish_cli.core.limiter import acquire
from goofish_cli.core.session import Session


@contextmanager
def write_operation(session: Session, bucket: str) -> Iterator[None]:
    with watch(account=session.unb), acquire(bucket, account=session.unb):
        yield
