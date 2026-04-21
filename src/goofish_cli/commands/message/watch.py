"""message watch — 常驻接收消息，每条解密后以 JSONL 打到 stdout。

不做自动回复；Agent 自己拿 JSONL 决策再调 message send。
Ctrl-C 退出。
"""

import asyncio
import json
import sys
from typing import Any

from loguru import logger

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.ws import (
    extract_incoming_text,
    extract_meta_event,
    extract_push_messages,
    run_forever,
)


@command(
    namespace="message",
    name="watch",
    description="常驻 IM 长连接，下行事件以 JSONL 输出到 stdout（Ctrl-C 退出）",
    strategy=Strategy.COOKIE,
    columns=[],
)
def watch() -> dict[str, Any]:
    session = Session.load()
    logger.info(f"[watch] unb={session.unb} tracknick={session.tracknick}")

    async def _handler(msg: dict[str, Any], _ws) -> None:
        # /s/para 是对方"正在输入"状态通知，跳过避免噪音
        if msg.get("lwp") == "/s/para":
            return
        for decoded in extract_push_messages(msg):
            # 优先识别元事件（read / new_msg 通知）
            meta = extract_meta_event(decoded)
            if meta is not None:
                sys.stdout.write(json.dumps(meta, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue
            # 再尝试嵌套消息正文
            item = extract_incoming_text(decoded)
            if item is None:
                continue
            # 真消息：send_message 非空 或 contentType=1
            if item.get("send_message") or item.get("content_type") == 1:
                sys.stdout.write(json.dumps(item, ensure_ascii=False) + "\n")
                sys.stdout.flush()

    try:
        asyncio.run(run_forever(session, handler=_handler))
    except KeyboardInterrupt:
        logger.info("[watch] 用户中断")
    return {"ok": True}
