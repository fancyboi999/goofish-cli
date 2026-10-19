"""item get — 查询商品详情。接口 mtop.taobao.idle.pc.detail v1.0（只读）"""

import asyncio
import os
from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.item_data import normalize_item
from goofish_cli.core.item_page import fetch_item_page
from goofish_cli.core.mtop import call


@command(
    namespace="item",
    name="get",
    description="查询闲鱼商品详情（只读）",
    strategy=Strategy.COOKIE,
    columns=["item_id", "title", "price", "seller_nick", "status"],
)
def get(item_id: str) -> dict[str, Any]:
    if os.environ.get("GOOFISH_DESKTOP_SANDBOX") == "1":
        if not str(item_id).isdigit():
            from goofish_cli.core.errors import GoofishError

            raise GoofishError("商品 ID 必须为数字")
        raw = asyncio.run(fetch_item_page(str(item_id)))
        return normalize_item(raw, str(item_id))
    session = Session.load()
    raw = call(
        session,
        api="mtop.taobao.idle.pc.detail",
        data={"itemId": str(item_id)},
        version="1.0",
        spm_cnt="a21ybx.item.0.0",
    )
    return normalize_item(raw, str(item_id))
