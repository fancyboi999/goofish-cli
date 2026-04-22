"""search — 搜索闲鱼商品。对标 OpenCLI `xianyu/search.js`。

思路：打开 `https://www.goofish.com/search?q=xxx` 让页面自己渲染，autoScroll 触发
懒加载，再在 page context 里跑 DOM 选择器提卡片。**不走 mtop 直签**：
- search 没对外 API，只有 HTML 卡片 + 动态加载
- 浏览器真实渲染天然抗风控

字段参考 OpenCLI：`item_id / rank / title / price / original_price / condition /
brand / location / badge / url / extra`。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from goofish_cli.core import Strategy, command
from goofish_cli.core.browser import auto_scroll, goofish_page
from goofish_cli.core.errors import AuthRequiredError, GoofishError

MAX_LIMIT = 50


def _normalize_limit(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 20
    return min(MAX_LIMIT, max(1, n))


def _item_id_from_url(url: str) -> str:
    m = re.search(r"[?&]id=(\d+)", url or "")
    return m.group(1) if m else ""


def _build_search_url(query: str) -> str:
    from urllib.parse import quote
    return f"https://www.goofish.com/search?q={quote(query)}"


# 页面上下文里跑的 JS。抽出来做常量方便测试（`__test__` 导出）。
_EXTRACT_JS = r"""
(limit) => (async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, timeoutMs = 8000) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (predicate()) return true;
      await wait(150);
    }
    return false;
  };

  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const sel = {
    card: 'a[href*="/item?id="]',
    title: '[class*="row1-wrap-title"], [class*="main-title"]',
    attrs: '[class*="row2-wrap-cpv"] span[class*="cpv--"]',
    priceWrap: '[class*="price-wrap"]',
    priceNum: '[class*="number"]',
    priceDec: '[class*="decimal"]',
    priceDesc: '[class*="price-desc"] [title], [class*="price-desc"] [style*="line-through"]',
    sellerWrap: '[class*="row4-wrap-seller"]',
    sellerText: '[class*="seller-text"]',
    badge: '[class*="credit-container"] [title], [class*="credit-container"] span',
  };

  await waitFor(() => {
    const bodyText = document.body?.innerText || '';
    return Boolean(
      document.querySelector(sel.card)
      || /请先登录|登录后|验证码|安全验证|异常访问/.test(bodyText)
      || /暂无相关宝贝|未找到相关宝贝|没有找到/.test(bodyText)
    );
  });

  const bodyText = document.body?.innerText || '';
  const requiresAuth = /请先登录|登录后/.test(bodyText);
  const blocked = /验证码|安全验证|异常访问/.test(bodyText);
  const empty = /暂无相关宝贝|未找到相关宝贝|没有找到/.test(bodyText);

  const items = Array.from(document.querySelectorAll(sel.card))
    .slice(0, limit)
    .map((card) => {
      const href = card.href || card.getAttribute('href') || '';
      const title = clean(card.querySelector(sel.title)?.textContent || '');
      const attrs = Array.from(card.querySelectorAll(sel.attrs))
        .map((n) => clean(n.textContent || ''))
        .filter(Boolean);
      const priceWrap = card.querySelector(sel.priceWrap);
      const priceNumber = clean(priceWrap?.querySelector(sel.priceNum)?.textContent || '');
      const priceDecimal = clean(priceWrap?.querySelector(sel.priceDec)?.textContent || '');
      const location = clean(card.querySelector(sel.sellerWrap)?.querySelector(sel.sellerText)?.textContent || '');
      const originalPriceNode = card.querySelector(sel.priceDesc);
      const badgeNode = card.querySelector(sel.badge);

      return {
        title,
        url: href,
        price: clean('¥' + priceNumber + priceDecimal).replace(/^¥\s*$/, ''),
        original_price: clean(originalPriceNode?.getAttribute('title') || originalPriceNode?.textContent || ''),
        condition: attrs[0] || '',
        brand: attrs[1] || '',
        extra: attrs.slice(2).join(' | '),
        location,
        badge: clean(badgeNode?.getAttribute('title') || badgeNode?.textContent || ''),
      };
    })
    .filter((it) => it.title && it.url);

  return { requiresAuth, blocked, empty, items, bodyPreview: bodyText.slice(0, 500) };
})()
"""


async def _run(query: str, limit: int) -> list[dict[str, Any]]:
    url = _build_search_url(query)
    async with goofish_page() as page:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await auto_scroll(page, times=2)
        payload = await page.evaluate(_EXTRACT_JS, limit)

    if not isinstance(payload, dict):
        raise GoofishError("搜索页返回结构非预期")

    items = payload.get("items") or []
    # "登录后" 在页脚也会出现——只有在"没拿到卡片 && 命中关键词"时才判定 auth 失败
    if not items and payload.get("requiresAuth"):
        raise AuthRequiredError("www.goofish.com 搜索结果页要求登录，cookies 可能失效")
    if not items and payload.get("blocked"):
        raise GoofishError("搜索页返回验证码/安全验证（触发风控），稍后重试或换账号")

    if not items and not payload.get("empty"):
        preview = (payload.get("bodyPreview") or "")[:200]
        raise GoofishError(
            f"未在搜索页上解析到任何卡片，可能 DOM 结构已变。"
            f"页面文案预览：{preview!r}"
        )

    return [
        {
            "rank": i + 1,
            "item_id": _item_id_from_url(it.get("url", "")),
            **it,
        }
        for i, it in enumerate(items)
    ]


@command(
    namespace="search",
    name="items",
    description="搜索闲鱼商品（浏览器路径，抗风控）",
    strategy=Strategy.COOKIE,
    columns=["rank", "item_id", "title", "price", "condition", "brand", "location", "badge", "url"],
)
def search(query: str, limit: int = 20) -> dict[str, Any]:
    items = asyncio.run(_run(str(query).strip(), _normalize_limit(limit)))
    return {"items": items, "total": len(items), "query": query}


__test__ = {
    "MAX_LIMIT": MAX_LIMIT,
    "_normalize_limit": _normalize_limit,
    "_build_search_url": _build_search_url,
    "_item_id_from_url": _item_id_from_url,
}
