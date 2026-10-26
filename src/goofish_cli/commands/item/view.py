"""item view — 读取商品页自身的响应并校验身份。

本机与沙箱共用页面响应读取器；取数不依赖页面 JavaScript 上下文。
平台要求验证时明确报错并保留沙箱页面，由用户亲自处理。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from goofish_cli.core import Strategy, command
from goofish_cli.core.browser import goofish_page
from goofish_cli.core.errors import AuthRequiredError, GoofishError
from goofish_cli.core.item_data import normalize_item
from goofish_cli.core.item_page import read_item_page


def _normalize_item_id(value: Any) -> str:
    s = str(value or "").strip()
    if not re.fullmatch(r"\d+", s):
        raise GoofishError(f"item_id 必须是数字，收到：{value!r}")
    return s


def _view_result(raw: dict[str, Any], item_id: str) -> dict[str, Any]:
    base = normalize_item(raw, item_id)
    data = raw["data"]
    item, seller = data["itemDO"], data.get("sellerDO") or {}

    def clean(value):
        return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()

    images = [
        image["url"]
        for image in item.get("imageInfos") or []
        if isinstance(image, dict) and image.get("url")
    ]
    result = {key: value for key, value in base.items() if key not in {"raw", "seller_nick"}}
    result.update(
        title=clean(base["title"]),
        description=clean(base["description"]),
        price="¥" + clean(base["price"]) if base["price"] is not None else None,
        original_price=clean(base["original_price"]),
        seller_name=clean(base["seller_nick"]),
        seller_id=clean(base["seller_id"]),
        status=clean(base["status"]),
        location=clean(base["location"]),
        condition=clean(base["condition"]),
        brand=clean(base["brand"]),
        category=clean(base["category"]),
        want_count=clean(item.get("wantCnt")),
        collect_count=clean(item.get("collectCnt")),
        browse_count=clean(item.get("browseCnt")),
        seller_score=clean(seller.get("xianyuSummary")),
        reply_ratio_24h=clean(seller.get("replyRatio24h")),
        reply_interval=clean(seller.get("replyInterval")),
        seller_url="https://www.goofish.com/personal?userId=" + clean(base["seller_id"])
        if base["seller_id"] is not None
        else "",
        image_count=str(len(images)),
        image_urls=images,
    )
    return result


async def _run(item_id: str) -> dict[str, Any]:
    try:
        async with goofish_page() as page:
            raw = await read_item_page(page, item_id)
    except GoofishError as exc:
        # 沙箱沿用响应读取器的类型；本机保留原有 CLI 退出码和 MCP 错误类型。
        ret = (exc.raw or {}).get("ret")
        if os.environ.get("GOOFISH_DESKTOP_SANDBOX") == "1" or not ret:
            raise
        message = " | ".join(ret)
        code = ret[0].partition("::")[0]
        if "SESSION_EXPIRED" in message:
            raise AuthRequiredError("mtop 返回 session 过期：" + message, raw=exc.raw) from exc
        raise GoofishError(f"mtop 调用失败 [{code}]: {message}", raw=exc.raw) from exc
    result = _view_result(raw, item_id)
    if not result.get("title"):
        raise GoofishError(f"未拿到商品 {item_id} 的标题，接口返回为空")
    return result


@command(
    namespace="item",
    name="view",
    description="浏览器视角查看商品详情（读取页面响应，含图片和卖家字段）",
    strategy=Strategy.COOKIE,
    columns=[
        "item_id",
        "title",
        "price",
        "condition",
        "brand",
        "location",
        "seller_name",
        "want_count",
        "browse_count",
    ],
)
def view(item_id: str) -> dict[str, Any]:
    normalized = _normalize_item_id(item_id)
    # MCP / table 渲染依赖 dict；image_urls 是列表（JSON 里保留，table 里压成长度）
    result = asyncio.run(_run(normalized))
    result["_image_urls_json"] = json.dumps(result.get("image_urls", []), ensure_ascii=False)
    return result


__test__ = {
    "_normalize_item_id": _normalize_item_id,
}
