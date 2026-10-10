"""测 search 的参数归一化、URL 构造与 _walk_pages 翻页状态机（fake page 驱动）。"""
from __future__ import annotations

import asyncio

import pytest

from goofish_cli.commands.search.search import __test__ as t
from goofish_cli.commands.search.search import _item_id_from_url


def test_normalize_limit_clamps_and_defaults():
    normalize = t["_normalize_limit"]
    assert normalize(10) == 10
    assert normalize("5") == 5
    assert normalize(0) == 1
    assert normalize(-3) == 1
    assert normalize(999) == t["MAX_LIMIT"]
    assert normalize(None) == 20
    assert normalize("abc") == 20


def test_normalize_pages_clamps_and_defaults():
    normalize = t["_normalize_pages"]
    assert normalize(1) == 1
    assert normalize("3") == 3
    assert normalize(0) == 1
    assert normalize(-2) == 1
    assert normalize(999) == t["MAX_PAGES"]
    assert normalize(None) == 1
    assert normalize("abc") == 1


def test_build_search_url_encodes_query():
    build = t["_build_search_url"]
    assert build("iPhone 15") == "https://www.goofish.com/search?q=iPhone%2015"
    assert build("中文") == "https://www.goofish.com/search?q=%E4%B8%AD%E6%96%87"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.goofish.com/item?id=123456&spm=foo", "123456"),
        ("https://www.goofish.com/item?spm=a&id=999", "999"),
        ("https://example.com/no-id", ""),
        ("", ""),
    ],
)
def test_item_id_from_url(url, expected):
    assert t["_item_id_from_url"](url) == expected


def test_auth_wall_attempts_is_two():
    """瞬时登录墙重试：总尝试 2 次（首次 + 1 次退避重试）。"""
    assert t["AUTH_WALL_ATTEMPTS"] == 2


# ---------------------------------------------------------------------------
# _walk_pages 翻页状态机（fake page 驱动，确定性、无网络）
# ---------------------------------------------------------------------------


class FakeLocator:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    def nth(self, i: int) -> FakeLocator:
        return self

    async def click(self, timeout: int = 0) -> None:
        self._page.clicks += 1


class FakePage:
    """按脚本依次返回 evaluate 结果；脚本耗尽后执行 on_exhausted。"""

    def __init__(self, script: list, on_exhausted=None) -> None:
        self.script = list(script)
        self.on_exhausted = on_exhausted
        self.clicks = 0

    def locator(self, sel: str) -> FakeLocator:
        return FakeLocator(self)

    async def evaluate(self, js: str, arg=None):
        # auto_scroll 的滚动指令不占脚本拍，直接短路
        if isinstance(js, str) and js.startswith("window.scrollTo"):
            return None
        if not self.script:
            if self.on_exhausted is not None:
                return self.on_exhausted()
            raise AssertionError("fake page script exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(arg) if callable(step) else step

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def goto(self, url: str, wait_until: str = "") -> None:
        return None


def _item(iid: str) -> dict:
    return {"url": f"https://www.goofish.com/item?id={iid}", "title": f"item-{iid}"}


def _page_payload(ids: list[str], **kw) -> dict:
    base = {"items": [_item(i) for i in ids], "requiresAuth": False, "blocked": False,
            "empty": False, "bodyPreview": ""}
    base.update(kw)
    return base


def _pagination(has_next: bool = True, total: int | None = 50) -> dict:
    return {"hasNext": has_next, "totalPages": total}


# 翻页状态机入口（fake page 驱动用）
_walk = t["_walk_pages"]


def test_should_retry_truth_table():
    """瞬时登录墙重试谓词（#28 契约）：只有 items=[] 且 requiresAuth 才重试。

    注意 `_EXTRACT_JS` 恒返回 `items` 键：真实登录墙载荷是
    `{"items": [], "requiresAuth": True, ...}`，必须重试；
    未知零卡片形态（requiresAuth=False）不重试，避免无谓的二次导航。
    """
    should_retry = t["_should_retry"]
    assert should_retry({"items": [{"id": 1}]}) is False
    assert should_retry({}) is False
    assert should_retry({"requiresAuth": True}) is True
    assert should_retry({"requiresAuth": False}) is False
    assert should_retry({"items": [], "requiresAuth": True}) is True
    assert should_retry({"items": [], "requiresAuth": False}) is False


def test_walk_pages_accumulates_and_dedupes_across_pages():
    """跨页去重：第 2 页重复第 1 页的 id 只计一次，pages_fetched 正确递增。"""
    script = [
        _pagination(True, 50),
        True,  # page-change 等待
        _page_payload(["201", "100", "202"]),  # 100 与第 1 页重复
    ]
    items, seen = [_item("100"), _item("101")], {"100", "101"}
    fetched, total, reason = asyncio.run(
        _walk(FakePage(script), items, seen, 1, pages=2, limit=200)
    )
    assert fetched == 2
    assert total == 50
    assert reason == "pages_reached"
    ids = [_item_id_from_url(it["url"]) for it in items]
    assert ids == ["100", "101", "201", "202"]  # 去重后顺序保持


def test_walk_pages_anchor_uses_unfiltered_first_card():
    """审核 P1-2：第 2 页首卡与第 1 页重复时，锚点仍取未过滤首卡，
    第 3 页可正常到达（不再因锚点失真而提前终止）。"""
    script = [
        _pagination(True, 50),
        True,  # 等待：page2 首卡 100 与 page1 重复（changed 依 DOM 而定，这里视为已变）
        _page_payload(["100", "201", "202"]),
        _pagination(True, 50),
        True,
        _page_payload(["301", "302"]),
    ]
    items, seen = [_item("100")], {"100"}
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), items, seen, 1, pages=3, limit=200)
    )
    assert fetched == 3
    assert reason == "pages_reached"
    ids = [_item_id_from_url(it["url"]) for it in items]
    assert ids == ["100", "201", "202", "301", "302"]


def test_walk_pages_stops_on_disabled_arrow():
    """右箭头 disabled（末页）→ last_page，保留已有结果。"""
    script = [_pagination(False, 1)]
    fetched, total, reason = asyncio.run(
        _walk(FakePage(script), [_item("100")], {"100"}, 1, pages=5, limit=200)
    )
    assert (fetched, total, reason) == (1, 1, "last_page")


def test_walk_pages_stops_at_cross_page_limit():
    """跨页 limit：累积到 limit 即停，reason=limit。"""
    script = [
        _pagination(True, 50),
        True,
        _page_payload(["201", "202"]),
    ]
    items, seen = [_item(f"{i}") for i in range(1, 44)], {str(i) for i in range(1, 44)}
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), items, seen, 1, pages=5, limit=45)
    )
    assert len(items) == 45
    assert reason == "limit"


def test_walk_pages_preserves_results_on_mid_walk_exception():
    """审核 P1-1：翻页途中 evaluate 抛（SPA 销毁执行上下文）→
    不抛出，返回第 1 页已累积结果 + reason=error。"""
    boom = RuntimeError("Execution context was destroyed")
    script = [
        _pagination(True, 50),
        boom,  # page-change 等待抛出
    ]
    items, seen = [_item("100"), _item("101")], {"100", "101"}
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), items, seen, 1, pages=3, limit=200)
    )
    assert fetched == 1
    assert reason == "error"
    assert len(items) == 2


def test_walk_pages_pagination_state_exception_preserves_results():
    """翻页第一拍（pagination 状态读取）抛出同样优雅终止。"""
    boom = RuntimeError("Execution context was destroyed")
    fetched, _, reason = asyncio.run(
        _walk(FakePage([boom]), [_item("100")], {"100"}, 1, pages=3, limit=200)
    )
    assert (fetched, reason) == (1, "error")


def test_walk_pages_wait_timeout_with_no_new_items_is_stale():
    """等待超时（changed=False）且提取无新数据 → reason=stale，保留结果。"""
    # wait JS resolve(False)；extract 返回与 seen 全重复的页
    script = [
        _pagination(True, 50),
        False,
        _page_payload(["100"]),  # 全是重复 → 无 fresh
    ]
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), [_item("100")], {"100"}, 1, pages=3, limit=200)
    )
    assert (fetched, reason) == (1, "stale")


def test_walk_pages_wait_timeout_but_fresh_items_continues():
    """等待超时但提取到新数据（渲染慢而非失败）→ 照常累积继续。"""
    script = [
        _pagination(True, 50),
        False,  # 等待超时
        _page_payload(["201"]),
        _pagination(False, 50),
    ]
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), [_item("100")], {"100"}, 1, pages=5, limit=200)
    )
    assert fetched == 2
    assert reason == "last_page"


def test_walk_pages_repeated_page_is_no_new():
    """重渲染成功但整页重复 → reason=no_new，防御性终止。"""
    script = [
        _pagination(True, 50),
        True,  # changed
        _page_payload(["100", "101"]),  # 全重复
    ]
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), [_item("100"), _item("101")], {"100", "101"}, 1,
              pages=3, limit=200)
    )
    assert (fetched, reason) == (1, "no_new")


def test_walk_pages_blocked_mid_walk():
    """翻页途中撞风控页 → reason=blocked，保留部分结果。"""
    script = [
        _pagination(True, 50),
        True,
        _page_payload([], blocked=True),
    ]
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), [_item("100")], {"100"}, 1, pages=3, limit=200)
    )
    assert (fetched, reason) == (1, "blocked")


def test_walk_pages_non_dict_extract_is_error():
    """extract 返回非 dict（结构突变）→ reason=error，保留结果。"""
    script = [
        _pagination(True, 50),
        True,
        "not-a-dict",
    ]
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), [_item("100")], {"100"}, 1, pages=3, limit=200)
    )
    assert (fetched, reason) == (1, "error")


def test_first_card_id_returns_first_with_id():
    """锚点函数：跳过无 id 条目，取首个可解析 id。"""
    f = t["_first_card_id"]
    assert f([{"url": "https://x/no-id"}, {"url": "https://www.goofish.com/item?id=42"}]) == "42"
    assert f([]) == ""
    assert f([{"url": ""}]) == ""


def test_walk_pages_skips_cards_without_numeric_id():
    """审核 P2：?id=abc 这类解析不出数字 id 的卡片不能跨页重复追加。"""
    bad = {"url": "https://www.goofish.com/item?id=abc", "title": "bad-card"}
    script = [
        _pagination(True, 50),
        True,
        # 第 2 页：新卡 101 + 坏卡（坏卡跳过，不影响继续翻页）
        {**_page_payload(["101"]), "items": [_item("101"), dict(bad)]},
        _pagination(True, 50),
        True,
        # 第 3 页：坏卡再次出现 + 新卡 102（坏卡不重复追加）
        {**_page_payload(["102"]), "items": [dict(bad), _item("102")]},
    ]
    items, seen = [_item("100")], {"100"}
    fetched, _, reason = asyncio.run(
        _walk(FakePage(script), items, seen, 1, pages=3, limit=200)
    )
    ids = [_item_id_from_url(it["url"]) for it in items]
    assert ids == ["100", "101", "102"]  # 坏卡被跳过，不重复出现
    assert fetched == 3
    assert reason == "pages_reached"


def test_walk_pages_non_dict_pagination_state_is_error():
    """审核 P2：pagination 状态返回 None/非 dict 时优雅终止，不 AttributeError。"""
    for bad in (None, [], "unexpected", 123):
        fetched, _, reason = asyncio.run(
            _walk(FakePage([bad]), [_item("100")], {"100"}, 1, pages=3, limit=200)
        )
        assert (fetched, reason) == (1, "error"), f"bad={bad!r}"
