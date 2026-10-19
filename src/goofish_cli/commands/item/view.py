"""item view — 浏览器商品详情。沙箱读取页面自身的响应并校验身份。

本机保留原有页面 SDK 调用；沙箱 item get 与 view 共用常驻浏览器路径。
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


def _build_item_url(item_id: str) -> str:
    return f"https://www.goofish.com/item?id={item_id}"


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


# 页面上下文里运行的抽取脚本。直接复用 OpenCLI 的提取逻辑（DOM 文案检查 + mtop 调用）。
_FETCH_JS = r"""
(itemId) => (async () => {
  const clean = (v) => String(v ?? '').replace(/\s+/g, ' ').trim();
  const extractRetCode = (ret) => {
    const first = Array.isArray(ret) ? ret[0] : '';
    return clean(first).split('::')[0] || '';
  };
  const waitFor = async (predicate, timeoutMs = 5000) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (predicate()) return true;
      await new Promise((r) => setTimeout(r, 150));
    }
    return false;
  };

  const bodyText = document.body?.innerText || '';
  // 注意：「登录后」在页脚也会出现，不能作为 auth 判定；真正的未登录靠 mtop 返回的
  // FAIL_SYS_SESSION_EXPIRED 来判，这里只拦显式验证码/风控页。
  if (/验证码|安全验证|异常访问/.test(bodyText)) return { error: 'blocked' };

  await waitFor(() => window.lib?.mtop?.request);
  if (!window.lib || !window.lib.mtop || typeof window.lib.mtop.request !== 'function') {
    return { error: 'mtop-not-ready' };
  }

  let response;
  try {
    response = await window.lib.mtop.request({
      api: 'mtop.taobao.idle.pc.detail',
      data: { itemId: String(itemId) },
      type: 'POST',
      v: '1.0',
      dataType: 'json',
      needLogin: false,
      needLoginPC: false,
      sessionOption: 'AutoLoginOnly',
      ecode: 0,
    });
  } catch (error) {
    const ret = error?.ret || [];
    return {
      error: 'mtop-request-failed',
      error_code: extractRetCode(ret),
      error_message: clean(Array.isArray(ret) ? ret.join(' | ') : error?.message || String(error)),
    };
  }

  const retCode = extractRetCode(response?.ret || []);
  if (retCode && retCode !== 'SUCCESS') {
    return {
      error: 'mtop-response-error',
      error_code: retCode,
      error_message: clean((response?.ret || []).join(' | ')),
    };
  }

  const data = response?.data || {};
  const item = data.itemDO || {};
  const seller = data.sellerDO || {};
  const labels = Array.isArray(item.itemLabelExtList) ? item.itemLabelExtList : [];
  const findLabel = (name) => labels.find((l) => clean(l.propertyText) === name)?.text || '';
  const images = Array.isArray(item.imageInfos)
    ? item.imageInfos.map((e) => e?.url).filter(Boolean)
    : [];

  return {
    item_id: clean(item.itemId || itemId),
    title: clean(item.title || ''),
    description: clean(item.desc || ''),
    price: item.soldPrice == null || typeof item.soldPrice === 'boolean' || item.soldPrice === ''
      ? null : '¥' + clean(item.soldPrice),
    price_kind: item.defaultPrice === true ? 'negotiable' : 'fixed',
    original_price: clean(item.originalPrice || ''),
    want_count: String(item.wantCnt ?? ''),
    collect_count: String(item.collectCnt ?? ''),
    browse_count: String(item.browseCnt ?? ''),
    status: clean(item.itemStatusStr || ''),
    status_code: item.itemStatus ?? null,
    condition: clean(findLabel('成色')),
    brand: clean(findLabel('品牌')),
    category: clean(findLabel('分类')),
    location: clean(seller.publishCity || seller.city || ''),
    seller_name: clean(seller.nick || seller.uniqueName || ''),
    seller_id: String(seller.sellerId || ''),
    seller_score: clean(seller.xianyuSummary || ''),
    reply_ratio_24h: clean(seller.replyRatio24h || ''),
    reply_interval: clean(seller.replyInterval || ''),
    seller_url: seller.sellerId ? 'https://www.goofish.com/personal?userId=' + seller.sellerId : '',
    image_count: String(images.length),
    image_urls: images,
  };
})()
"""


async def _run_native(item_id: str) -> dict[str, Any]:
    url = _build_item_url(item_id)
    async with goofish_page() as page:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        result = await page.evaluate(_FETCH_JS, item_id)

    if not isinstance(result, dict):
        raise GoofishError("商品详情页返回结构非预期")

    err = result.get("error")
    if err == "blocked":
        raise GoofishError("商品详情页被验证码/安全验证拦截，触发风控")
    if err == "mtop-not-ready":
        raise GoofishError("页面 window.lib.mtop 未就绪（等待超时），页面加载异常")

    # auth 判定统一走 mtop 返回的 error_code/error_message 里的 SESSION_EXPIRED，
    # 不再依赖 body 文案正则（"登录后" 在页脚也会出现，误报多）。
    err_code = str(result.get("error_code") or "")
    err_msg = str(result.get("error_message") or "")
    if re.search(r"FAIL_SYS_SESSION_EXPIRED|SESSION_EXPIRED", err_code + " " + err_msg):
        raise AuthRequiredError("mtop 返回 session 过期：" + (err_msg or err_code))
    if err:
        raise GoofishError(f"mtop 调用失败 [{err_code or err}]: {err_msg or '无详情'}")
    if not result.get("title"):
        raise GoofishError(f"未拿到商品 {item_id} 的标题，接口返回为空")

    return result



async def _run(item_id: str) -> dict[str, Any]:
    if os.environ.get("GOOFISH_DESKTOP_SANDBOX") != "1":
        return await _run_native(item_id)
    async with goofish_page() as page:
        raw = await read_item_page(page, item_id)
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
    "_build_item_url": _build_item_url,
}
