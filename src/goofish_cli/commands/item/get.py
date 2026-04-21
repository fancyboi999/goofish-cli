"""item get — 查询商品详情。接口 mtop.taobao.idle.pc.detail v1.0（只读）"""

from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.mtop import call


@command(
    namespace="item",
    name="get",
    description="查询闲鱼商品详情（只读）",
    strategy=Strategy.COOKIE,
    columns=["item_id", "title", "price", "seller_nick", "status"],
)
def get(item_id: str) -> dict[str, Any]:
    session = Session.load()
    raw = call(
        session,
        api="mtop.taobao.idle.pc.detail",
        data={"itemId": str(item_id)},
        version="1.0",
        spm_cnt="a21ybx.item.0.0",
    )
    data = raw.get("data", {}) or {}
    track = data.get("trackParams", {}) or {}
    return {
        "item_id": track.get("id", item_id),
        "title": track.get("title", ""),
        "price": track.get("soldPrice") or track.get("price", ""),
        "seller_nick": track.get("seller_nick", ""),
        "status": track.get("itemStatus", ""),
        "raw": raw,
    }
