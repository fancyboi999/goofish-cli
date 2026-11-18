"""search analyze — 竞品价格带统计 + 调价定位建议（只读，不改价）。

复用 `search items` 的浏览器采集结果，做本地分位数统计（min/P25/中位/P75/max），
并在给出 `--price` 我的定价时定位分档、给出方向建议。样本 <5 条只报价格带，
不下方向性结论。移植自 xianyu-seller 技能 price_advisor.py 的纯统计逻辑。

只读：不调用任何改价接口；统计基于搜索页可见样本，不代表成交保证。
"""
from __future__ import annotations

import re
from typing import Any

from goofish_cli.core import Strategy, command
from goofish_cli.core.errors import GoofishError

# 样本少于此数只报价格带，不给方向性结论（与技能一致）
MIN_SAMPLE = 5


def parse_price(value: Any) -> float | None:
    """从 ¥199.00 / 199元 / 数字 字符串解析金额；无法解析返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).replace(",", "").strip()
    m = re.search(r"\d+(?:\.\d{1,2})?", text)
    return float(m.group()) if m else None


def percentile(sorted_vals: list[float], q: float) -> float | None:
    """最近邻分位：idx = round(q*(n-1))，与技能 price_advisor 口径一致。"""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    idx = max(0, min(n - 1, round(q * (n - 1))))
    return sorted_vals[idx]


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return round((s[mid - 1] + s[mid]) / 2, 2)


def price_band(prices: list[float]) -> dict[str, Any]:
    sv = sorted(prices)
    return {
        "count": len(prices),
        "min": sv[0] if sv else None,
        "p25": percentile(sv, 0.25),
        "median": median(prices),
        "p75": percentile(sv, 0.75),
        "max": sv[-1] if sv else None,
    }


def advise(my_price: float | None, prices: list[float], sample_size: int) -> dict[str, Any]:
    """定位我的定价并给方向建议；样本不足只报价格带。"""
    band = price_band(prices)
    advice: dict[str, Any] = {"position": "", "suggestion": "", "confidence": "low"}
    if not prices:
        advice["suggestion"] = "无可见价格样本，无法给出建议"
        return {**band, **advice}
    if sample_size < MIN_SAMPLE or len(prices) < MIN_SAMPLE:
        advice["suggestion"] = (
            f"样本不足（价格样本 {len(prices)} 条），仅作参考："
            f"可见价格带 ¥{band['min']}–¥{band['max']}，中位数 ¥{band['median']}"
        )
        return {**band, **advice}
    advice["confidence"] = "medium"
    if my_price is None:
        advice["position"] = "未提供 --price，仅报价格带"
        advice["suggestion"] = (
            f"市场参考：P25 ¥{band['p25']} / 中位 ¥{band['median']} / P75 ¥{band['p75']}；"
            "快速出手定价在 P25 以下，正常成交在中位附近，急售可再降 10%"
        )
        return {**band, **advice}
    if my_price > band["p75"]:
        advice["position"] = f"高于市场（P75=¥{band['p75']}）"
        advice["suggestion"] = (
            f"当前 ¥{my_price} 超过 75% 分位，浏览/想要转化会明显变差；"
            f"建议降至 ¥{band['median']} 附近，或加卖点（包邮/赠品）维持现价"
        )
    elif my_price > band["median"]:
        advice["position"] = "中位与 P75 之间（偏高）"
        advice["suggestion"] = (
            f"当前 ¥{my_price} 略高于中位 ¥{band['median']}；"
            "若想要数增长停滞，可小降至中位附近试探"
        )
    elif my_price >= band["p25"]:
        advice["position"] = "P25 与中位之间（合理区间）"
        advice["suggestion"] = f"当前 ¥{my_price} 处于主流成交区间，定价合理，维持观察"
    else:
        advice["position"] = "低于 P25（偏低）"
        advice["confidence"] = "medium"
        advice["suggestion"] = (
            f"当前 ¥{my_price} 低于 25% 分位 ¥{band['p25']}，可能让利过多；"
            f"若无急售需求，有上调至 ¥{band['median']} 附近的空间"
        )
    return {**band, **advice}


@command(
    namespace="search",
    name="analyze",
    description="竞品价格带统计 + 调价定位建议（只读，不改价）",
    strategy=Strategy.COOKIE,
    columns=["rank", "item_id", "title", "price", "condition", "location", "url"],
)
def analyze(
    query: str,
    price: float | None = None,
    limit: int = 20,
    pages: int = 1,
    condition: str = "",
) -> dict[str, Any]:
    q = str(query).strip()
    if not q:
        raise GoofishError("关键词不能为空")
    if price is not None and price < 0:
        raise GoofishError("我的定价不能为负")

    # 复用现有 search items 的浏览器采集，不重复实现抓取/翻页/风控。
    from goofish_cli.commands.search.search import search

    result = search(q, limit=limit, pages=pages)
    items = result.get("items") or []

    rows: list[dict[str, Any]] = []
    prices: list[float] = []
    for it in items:
        cond = it.get("condition") or ""
        if condition and condition not in str(cond):
            continue
        parsed = parse_price(it.get("price"))
        row = {
            "rank": it.get("rank"),
            "item_id": it.get("item_id"),
            "title": it.get("title"),
            "price": it.get("price"),
            "condition": cond,
            "location": it.get("location"),
            "url": it.get("url"),
        }
        rows.append(row)
        if parsed is not None:
            prices.append(parsed)

    analysis = advise(price, prices, len(rows))
    return {
        "query": q,
        "my_price": price,
        "sample_size": len(rows),
        "price_samples": len(prices),
        "analysis": analysis,
        "competitors": rows,
        "note": "统计基于搜索页可见样本，不代表成交保证；本命令只读，不改价。",
    }


__test__ = {
    "parse_price": parse_price,
    "percentile": percentile,
    "median": median,
    "price_band": price_band,
    "advise": advise,
    "MIN_SAMPLE": MIN_SAMPLE,
}
