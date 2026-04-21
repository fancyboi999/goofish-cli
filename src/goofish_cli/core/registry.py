"""命令注册中心。参照 opencli cli({...}) —— 单一 registry → CLI / MCP / Skill 共享。"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from goofish_cli.core.strategy import Strategy


@dataclass
class Command:
    namespace: str
    name: str
    description: str
    func: Callable[..., Any]
    strategy: Strategy = Strategy.COOKIE
    columns: list[str] = field(default_factory=list)
    write: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.namespace}.{self.name}"


_REGISTRY: dict[str, Command] = {}


def command(
    *,
    namespace: str,
    name: str,
    description: str,
    strategy: Strategy = Strategy.COOKIE,
    columns: list[str] | None = None,
    write: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰器：将函数注册为命令。"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cmd = Command(
            namespace=namespace,
            name=name,
            description=description,
            func=func,
            strategy=strategy,
            columns=columns or [],
            write=write,
        )
        if cmd.full_name in _REGISTRY:
            raise RuntimeError(f"重复注册命令：{cmd.full_name}")
        _REGISTRY[cmd.full_name] = cmd
        return func

    return decorator


def registry() -> dict[str, Command]:
    return dict(_REGISTRY)


def iter_commands() -> Iterator[Command]:
    return iter(_REGISTRY.values())


def discover() -> None:
    """自动扫描 goofish_cli.commands.* 所有模块，触发装饰器注册。"""
    from goofish_cli import commands  # noqa: WPS433

    def _walk(pkg: Any) -> None:
        for info in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
            module = importlib.import_module(info.name)
            if info.ispkg:
                _walk(module)

    _walk(commands)
