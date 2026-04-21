"""命令认证/调用策略枚举（参照 opencli Strategy）。"""
from __future__ import annotations

from enum import StrEnum


class Strategy(StrEnum):
    PUBLIC = "public"
    COOKIE = "cookie"
    WEBSOCKET = "ws"
