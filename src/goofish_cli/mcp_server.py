"""FastMCP 入口。扫描同一 registry → 每个 Command 注册为 @mcp.tool()。

启动：`uvx goofish-mcp` 或 `python -m goofish_cli.mcp_server`
Claude Code 配置:
  {
    "mcpServers": {
      "goofish": { "command": "uvx", "args": ["goofish-mcp"] }
    }
  }
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

from mcp.server.fastmcp import FastMCP

from goofish_cli.core import GoofishError, iter_commands
from goofish_cli.core.registry import discover

mcp = FastMCP("goofish")


def _register_all() -> None:
    discover()
    for cmd in iter_commands():
        _register_one(cmd)


def _register_one(cmd) -> None:
    """把一条 registry Command 注册为 MCP tool，保留参数签名。

    handler 是 async（FastMCP 要求），但 registry 里的 cmd.func 是同步函数——
    其中有些（`message list-chats --watch-secs` / `search items` / `item view`）
    内部用 `asyncio.run(...)` 驱动 async 逻辑。直接 `cmd.func(**kwargs)` 会在
    MCP 的事件循环里再起一个 event loop，触发 `RuntimeError: asyncio.run() cannot
    be called from a running event loop`。

    用 `asyncio.to_thread` 把同步调用扔线程池，即可绕开嵌套 loop 限制，同时
    对纯 HTTP 命令（没有 asyncio.run 的）也零成本兼容。
    """
    tool_name = f"{cmd.namespace}_{cmd.name}".replace("-", "_")
    doc = cmd.description
    sig = inspect.signature(cmd.func)

    async def handler(**kwargs: Any) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(cmd.func, **kwargs)
            return {"ok": True, "data": result}
        except GoofishError as e:
            return {"ok": False, "error_type": type(e).__name__, "message": str(e)}

    handler.__name__ = tool_name
    handler.__doc__ = doc
    handler.__signature__ = sig  # type: ignore[attr-defined]

    mcp.tool(name=tool_name, description=doc)(handler)


def main() -> None:
    _register_all()
    mcp.run()


if __name__ == "__main__":
    main()
