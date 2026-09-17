"""统一输出渲染器。支持 json/yaml/table/md/csv。非 TTY 场景 table → json 降级。"""
from __future__ import annotations

import csv
import io
import json
import sys
from enum import StrEnum
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table


class Format(StrEnum):
    JSON = "json"
    YAML = "yaml"
    TABLE = "table"
    MD = "md"
    CSV = "csv"


# 常见多行数据包裹键优先顺序
_WELL_KNOWN_WRAPPER_KEYS = ("items", "sessions", "messages", "records", "results", "rows", "data", "list")


def _is_dict_list(val: Any) -> bool:
    """判断 val 是否为 dict 列表（包含空列表）。"""
    return isinstance(val, list) and (not val or all(isinstance(x, dict) for x in val))


def _extract_dict_rows(data: dict[str, Any], columns: list[str] | None = None) -> list[dict[str, Any]] | None:
    """从 dict 中提取多行数据；若本身为单实体 dict 则返回 None。"""
    col_set = set(columns or [])

    # 收集候选的 list[dict] 字段
    candidates: dict[str, list[dict[str, Any]]] = {}
    for k, v in data.items():
        if _is_dict_list(v):
            candidates[k] = v

    if not candidates:
        return None

    # 若提供了 columns，基于契约对比：候选列表元素 vs data 根节点 对 columns 的匹配度
    if col_set:
        data_match = len(set(data.keys()) & col_set)
        best_key: str | None = None
        best_score = data_match

        for k, cand in candidates.items():
            if cand:
                cand_keys = set(cand[0].keys())
                score = len(cand_keys & col_set)
            else:
                score = 1 if k in _WELL_KNOWN_WRAPPER_KEYS else 0

            if score > best_score:
                best_score = score
                best_key = k

        if best_key is not None:
            return candidates[best_key]

        if data_match > 0:
            return None

    # 未提供 columns 或匹配度一致：优先采用约定包裹键
    for key in _WELL_KNOWN_WRAPPER_KEYS:
        if key in candidates:
            return candidates[key]

    # 若有且仅有一个 list[dict] 候选字段，自适应推导为行数据
    if len(candidates) == 1:
        return next(iter(candidates.values()))

    return None


def _as_rows(data: Any, columns: list[str] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    if isinstance(data, dict):
        wrapped = _extract_dict_rows(data, columns=columns)
        if wrapped is not None:
            data = wrapped
        else:
            return list(data.keys()), [data]

    if isinstance(data, list) and data and isinstance(data[0], dict):
        cols: list[str] = []
        for item in data:
            for k in item:
                if k not in cols:
                    cols.append(k)
        return cols, data
    return columns or [], []


def render(data: Any, fmt: Format = Format.JSON, columns: list[str] | None = None) -> None:
    # 非 TTY 且用户没显式指定 table → 走 json（便于管道处理）
    if fmt is Format.TABLE and not sys.stdout.isatty():
        fmt = Format.JSON

    if fmt is Format.JSON:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    if fmt is Format.YAML:
        print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        return

    cols, rows = _as_rows(data, columns=columns)
    if columns:
        cols = columns
    if not rows:
        # 标量或空：降级为 JSON
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    if fmt is Format.TABLE:
        console = Console()
        table = Table(show_header=True, header_style="bold cyan")
        for c in cols:
            table.add_column(c)
        for row in rows:
            table.add_row(*[str(row.get(c, "")) for c in cols])
        console.print(table)
        return

    if fmt is Format.MD:
        print("| " + " | ".join(cols) + " |")
        print("| " + " | ".join("---" for _ in cols) + " |")
        for row in rows:
            print("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
        return

    if fmt is Format.CSV:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in cols})
        sys.stdout.write(buf.getvalue())
        return
