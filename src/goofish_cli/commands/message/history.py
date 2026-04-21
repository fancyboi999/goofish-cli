"""message history — 拉取指定会话的历史消息。

走 WebSocket LWP `/r/MessageManager/listUserMessages`（官方没有对应的 HTTP 版）。
一次性命令：连 → reg → 翻页直到 hasMore=0 → 断开。
"""

import asyncio
from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.ws import list_user_messages


@command(
    namespace="message",
    name="history",
    description="拉取指定 cid 会话的历史消息（翻页到底）",
    strategy=Strategy.COOKIE,
    columns=["send_user_id", "send_user_name", "message"],
)
def history(cid: str, limit_per_page: int = 20) -> list[dict[str, Any]]:
    session = Session.load()
    return asyncio.run(list_user_messages(session, cid, limit_per_page=limit_per_page))
