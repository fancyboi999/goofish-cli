"""纯函数测输出渲染器的行提取 + 表格渲染。"""
from goofish_cli.core.output import Format, _as_rows, render

# ── _as_rows ──────────────────────────────────────────────


def test_as_rows_extracts_items_from_wrapper_dict():
    # item list / search 返回 {"items": [...], "total": n}，行数据在 items 里
    data = {"items": [{"rank": 1, "item_id": "a"}, {"rank": 2, "item_id": "b"}], "total": 2}
    cols, rows = _as_rows(data)
    assert rows == [{"rank": 1, "item_id": "a"}, {"rank": 2, "item_id": "b"}]
    assert cols == ["rank", "item_id"]


def test_as_rows_extracts_sessions_key():
    # message list-chats 返回 {"sessions": [...], ...}
    data = {"sessions": [{"cid": "1"}], "has_more": False, "total": 1}
    _cols, rows = _as_rows(data)
    assert rows == [{"cid": "1"}]


def test_as_rows_flat_dict_stays_single_row():
    # auth status / media upload 等扁平 dict 仍按单行渲染
    data = {"unb": "123", "valid": True}
    cols, rows = _as_rows(data)
    assert cols == ["unb", "valid"]
    assert rows == [data]


def test_as_rows_empty_items_yields_no_rows():
    # 空列表 → 无行，render 侧降级 JSON，而不是渲染一行全空
    _cols, rows = _as_rows({"items": [], "total": 0})
    assert rows == []


def test_as_rows_bare_list_derives_cols():
    # message history 直接返回 list
    cols, rows = _as_rows([{"a": 1}, {"b": 2}])
    assert cols == ["a", "b"]
    assert len(rows) == 2


def test_as_rows_scalar_list_no_rows():
    _cols, rows = _as_rows(["a", "b"])
    assert rows == []


def test_as_rows_well_known_key_beats_flat_fields():
    # 同时有 items 和普通字段时优先取 items
    data = {"items": [{"x": 1}], "total": 1, "ok": True}
    _cols, rows = _as_rows(data)
    assert rows == [{"x": 1}]


# ── render table ──────────────────────────────────────────


def test_render_table_prints_rows_from_wrapper_dict(capsys):
    # 真机复现：goofish item list -o table 曾渲染出只有表头 + 一行全空的表
    data = {"items": [{"rank": 1, "item_id": "107", "title": "测试", "price": "¥1", "status": "在售"}], "total": 1}
    render(data, fmt=Format.TABLE, columns=["rank", "item_id", "title", "price", "status"])
    out = capsys.readouterr().out
    assert "107" in out
    assert "测试" in out


def test_render_table_flat_dict_single_row(capsys):
    data = {"unb": "13327905", "valid": True}
    render(data, fmt=Format.TABLE, columns=["unb", "valid"])
    out = capsys.readouterr().out
    assert "13327905" in out
