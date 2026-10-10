"""本机护栏状态：稳定锁文件覆盖事务，临时文件落盘后原子替换。"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from goofish_cli.core.errors import GoofishError


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise GoofishError("本机护栏状态不可读取；保留原文件，请检查配置或恢复备份") from exc
    if not isinstance(value, dict):
        raise GoofishError("本机护栏状态格式无效；未清空已有状态")
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked_state(path: Path) -> Iterator[dict[str, Any]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(path) + ".lock", timeout=5, mode=0o600):
            value = read_json(path)
            yield value
            atomic_write(path, value)
    except Timeout as exc:
        raise GoofishError("本机护栏状态锁超时，未发起写请求") from exc
    except OSError:
        raise GoofishError("本机护栏状态无法持久化，请检查目录权限或磁盘空间") from None
