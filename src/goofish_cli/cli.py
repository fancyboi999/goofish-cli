"""Typer 入口。扫描 registry → 按 namespace 聚合为子命令树 → 统一注入 --format。"""
from __future__ import annotations

import sys
from collections import defaultdict

import typer
from loguru import logger

from goofish_cli.core import GoofishError, iter_commands
from goofish_cli.core.output import Format, render
from goofish_cli.core.registry import Command, discover

app = typer.Typer(
    name="goofish",
    help="闲鱼 CLI — 支持 MCP，未来支持 Skills。为 AI Agent 提供闲鱼自动化基础能力。",
    no_args_is_help=True,
    add_completion=False,
)


def _format_option() -> typer.Option:
    return typer.Option(
        Format.TABLE.value,
        "--format",
        "-f",
        help="输出格式：json/yaml/table/md/csv",
    )


def _wrap(cmd: Command):
    """把 registry 里的函数包装成 Typer 回调，注入 --format 并统一渲染/异常处理。"""

    # 直接复用原函数的签名，加一个 --format
    import functools
    import inspect

    sig = inspect.signature(cmd.func)

    @functools.wraps(cmd.func)
    def wrapper(**kwargs):
        fmt = Format(kwargs.pop("format"))
        try:
            result = cmd.func(**kwargs)
        except GoofishError as e:
            typer.secho(f"[{type(e).__name__}] {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=e.exit_code) from e
        except Exception as e:  # noqa: BLE001
            typer.secho(f"[Error] {e}", fg=typer.colors.RED, err=True)
            logger.exception(e)
            raise typer.Exit(code=1) from e
        render(result, fmt=fmt, columns=cmd.columns or None)

    # 重建签名以让 Typer 正确推导
    new_params = list(sig.parameters.values()) + [
        inspect.Parameter(
            "format",
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=Format.TABLE.value,
            annotation=str,
        )
    ]
    wrapper.__signature__ = sig.replace(parameters=new_params)  # type: ignore[attr-defined]
    return wrapper


def build_app() -> typer.Typer:
    discover()
    # namespace → Typer sub
    subs: dict[str, typer.Typer] = defaultdict(lambda: typer.Typer(no_args_is_help=True))

    by_ns: dict[str, list[Command]] = defaultdict(list)
    for cmd in iter_commands():
        by_ns[cmd.namespace].append(cmd)

    for ns, cmds in by_ns.items():
        sub = typer.Typer(
            name=ns,
            help=f"{ns} 子命令（{len(cmds)} 个）",
            no_args_is_help=True,
            add_completion=False,
        )
        for cmd in cmds:
            sub.command(name=cmd.name, help=cmd.description)(_wrap(cmd))
        subs[ns] = sub
        app.add_typer(sub, name=ns)

    return app


@app.command(name="version")
def version_cmd():
    """打印版本号。"""
    from goofish_cli import __version__
    print(f"goofish-cli {__version__}")


@app.command(name="list-commands")
def list_commands(format: str = Format.TABLE.value):  # noqa: A002
    """列出所有已注册命令（调试用）。"""
    discover()
    rows = [
        {
            "command": f"goofish {c.namespace} {c.name}",
            "description": c.description,
            "strategy": c.strategy.value,
            "write": c.write,
        }
        for c in iter_commands()
    ]
    render(rows, fmt=Format(format), columns=["command", "description", "strategy", "write"])


# 模块导入时即构建（Typer scripts 需要 top-level app）
build_app()


if __name__ == "__main__":
    sys.exit(app())
