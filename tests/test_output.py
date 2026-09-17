"""统一输出渲染器（_as_rows 与 render）的单元测试。"""
from goofish_cli.core.output import Format, _as_rows, render

# ── _as_rows 结构推导测试 ──────────────────────────────────────────


def test_as_rows_extracts_items_from_wrapper_dict():
    # item list / search 返回 {"items": [...], "total": n}
    data = {"items": [{"rank": 1, "item_id": "a"}, {"rank": 2, "item_id": "b"}], "total": 2}
    cols, rows = _as_rows(data, columns=["rank", "item_id"])
    assert rows == [{"rank": 1, "item_id": "a"}, {"rank": 2, "item_id": "b"}]
    assert cols == ["rank", "item_id"]


def test_as_rows_extracts_sessions_key():
    # message list-chats 返回 {"sessions": [...], ...}
    data = {"sessions": [{"cid": "1"}], "has_more": False, "total": 1}
    _cols, rows = _as_rows(data)
    assert rows == [{"cid": "1"}]


def test_as_rows_flat_dict_stays_single_row():
    # auth status / media upload 等扁平 dict 保持单行渲染
    data = {"unb": "123", "valid": True}
    cols, rows = _as_rows(data, columns=["unb", "valid"])
    assert cols == ["unb", "valid"]
    assert rows == [data]


def test_as_rows_empty_items_yields_no_rows():
    # 空列表 → 无行，触发 render 降级为 JSON
    _cols, rows = _as_rows({"items": [], "total": 0}, columns=["rank", "item_id"])
    assert rows == []


def test_as_rows_bare_list_derives_cols():
    # message history 直接返回 list[dict]
    cols, rows = _as_rows([{"a": 1}, {"b": 2}])
    assert cols == ["a", "b"]
    assert len(rows) == 2


def test_as_rows_scalar_list_no_rows():
    _cols, rows = _as_rows(["a", "b"])
    assert rows == []


def test_as_rows_arbitrary_list_key_via_columns():
    # 第一性原理：哪怕不是 items/sessions，只要内部列表契合 columns 就能自适应识别
    data = {"orders": [{"order_id": "1001", "amount": 99}], "total": 1}
    cols, rows = _as_rows(data, columns=["order_id", "amount"])
    assert rows == [{"order_id": "1001", "amount": 99}]
    assert cols == ["order_id", "amount"]


def test_as_rows_single_dict_with_sublist_keeps_single_row_when_columns_match_parent():
    # 当根 dict 自身字段匹配 columns 时（如 location default），即使有 all 子列表也不误拆
    data = {
        "prov": "上海",
        "city": "上海",
        "area": "浦东",
        "all": [{"prov": "上海", "city": "上海", "area": "浦东"}],
    }
    cols, rows = _as_rows(data, columns=["prov", "city", "area"])
    assert len(rows) == 1
    assert rows[0]["prov"] == "上海"
    assert "all" in rows[0]


# ── render 表格渲染测试 ──────────────────────────────────────────


def test_render_table_prints_rows_from_wrapper_dict(capsys):
    data = {
        "items": [{"rank": 1, "item_id": "107", "title": "测试商品", "price": "¥1", "status": "在售"}],
        "total": 1,
    }
    render(data, fmt=Format.TABLE, columns=["rank", "item_id", "title", "price", "status"])
    out = capsys.readouterr().out
    assert "107" in out
    assert "测试商品" in out


def test_render_table_flat_dict_single_row(capsys):
    # 使用合规安全占位符，不触发 sensitive identifiers 规则
    data = {"unb": "test_unb_123", "valid": True}
    render(data, fmt=Format.TABLE, columns=["unb", "valid"])
    out = capsys.readouterr().out
    assert "test_unb_123" in out
