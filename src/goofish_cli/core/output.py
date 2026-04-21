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


def _as_rows(data: Any) -> tuple[list[str], list[dict[str, Any]]]:
    if isinstance(data, dict):
        return list(data.keys()), [data]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        cols: list[str] = []
        for item in data:
            for k in item:
                if k not in cols:
                    cols.append(k)
        return cols, data
    return [], []


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

    cols, rows = _as_rows(data)
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
