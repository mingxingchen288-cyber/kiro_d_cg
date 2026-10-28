"""快照的索引和旧对象的解析（视图的列来源、JSON 文本）。"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .inventory import Source
from .snapshot import Row, Snapshot

T_TABLE = "CMX.T_COST_TABLE_METADATA"
T_COLUMN = "CMX.T_COST_COLUMN_METADATA"
T_COMPONENT = "CMX.T_COST_PAGE_COMPONENT"
T_RULE = "CMX.T_COST_PAGE_RULE"
T_ROLE = "CMX.T_COST_ROLE"
T_ROLE_PAGE = "CMX.T_COST_ROLE_PAGE"
T_RESOURCE = "CMX.T_COST_RESOURCE"
T_EXPORT = "CMX.T_COST_EXPORT_CONFIG"
T_EXPORT_DETAIL = "CMX.T_COST_EXPORT_CONFIG_DETAIL"
T_LOOKUP = "CMX.T_COST_LOOKUP_CONFIG"
T_FLOW = "CMX.WF_FLOW_DEF"
T_FLOW_NODE = "CMX.WF_FLOW_NODE"
T_FLOW_APPROVER = "CMX.WF_FLOW_APPROVER"
T_FLOW_CONFIG = "CMX.WF_FLOW_CONFIG"
T_TAB_COLS = "ALL_TAB_COLS"
T_VIEWS = "ALL_VIEWS"


def src(table: str, row: Row, pk: str = "ID") -> Source:
    return Source(table, f"{pk}={row[pk]}")


def load_json(text: str | None) -> Any:
    return json.loads(text) if text else None


@dataclass(frozen=True)
class ViewColumn:
    """视图的一列：`column` 为它取自写入表的同名列；取自其他表或由表达式算出时为 None。"""

    name: str
    expression: str
    column: str | None


class Legacy:
    def __init__(self, snapshot: Snapshot) -> None:
        self.s = snapshot
        self.tables = {r["TABLE_CODE"]: r for r in snapshot[T_TABLE]}
        self.columns: dict[int, list[Row]] = defaultdict(list)
        for r in snapshot[T_COLUMN]:
            self.columns[r["TABLE_METADATA_ID"]].append(r)
        self.components: dict[str, list[Row]] = defaultdict(list)
        for r in sorted(snapshot[T_COMPONENT], key=lambda r: (r["SORT_ORDER"], r["ID"])):
            self.components[r["PAGE_CODE"]].append(r)
        self.rules: dict[tuple[str, str], list[Row]] = defaultdict(list)
        for r in snapshot[T_RULE]:
            self.rules[(r["PAGE_CODE"], r["COMPONENT_KEY"])].append(r)
        self.roles = {r["ID"]: r for r in snapshot[T_ROLE]}
        self.tab_cols: dict[str, dict[str, Row]] = defaultdict(dict)
        for r in snapshot[T_TAB_COLS]:
            self.tab_cols[r["TABLE_NAME"]][r["COLUMN_NAME"]] = r
        self.views = {r["VIEW_NAME"]: r["TEXT"] for r in snapshot[T_VIEWS]}
        self.lookups = {r["LOOKUP_CODE"]: r for r in snapshot[T_LOOKUP]}

    def rule(self, page: str, component: str, rule_type: str) -> Row | None:
        found = [r for r in self.rules[(page, component)] if r["RULE_TYPE"] == rule_type]
        return found[0] if found else None

    def view_columns(self, view: str, table: str) -> dict[str, ViewColumn]:
        """解析视图的选择列表，找出每一列是否取自写入表 `table` 的同名列。"""
        return parse_view(self.views[view], table, set(self.tab_cols[table]))


_ALIAS = re.compile(r"^(.*?)(?:\s+AS\s+|\s+|(?<=\)))([A-Za-z_][A-Za-z0-9_$#]*)$", re.S | re.I)
_QUALIFIED = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_$#]*)")
_WORD = re.compile(r"\b([A-Za-z_][A-Za-z0-9_$#]*)\b")


def split_top(text: str, sep: str = ",") -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def top_keyword(text: str, word: str) -> int:
    depth = 0
    pattern = re.compile(rf"\b{word}\b", re.I)
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and pattern.match(text, i) and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
            return i
    return -1


def parse_view(text: str, table: str, table_columns: set[str]) -> dict[str, ViewColumn]:
    body = text.strip()
    start = top_keyword(body, "SELECT") + len("SELECT")
    end = top_keyword(body, "FROM")
    tail = body[end + 4:]
    where = top_keyword(tail, "WHERE")
    from_part = tail[:where] if where >= 0 else tail
    aliases: dict[str, str] = {}
    for item in split_top(from_part):
        words = item.split()
        if words:
            aliases[(words[1] if len(words) > 1 else words[0]).upper()] = words[0].upper()
    own_aliases = {a for a, t in aliases.items() if t == table.upper()}
    result: dict[str, ViewColumn] = {}
    for item in split_top(body[start:end]):
        m = _ALIAS.match(item)
        if m and not re.search(r"[.(]\s*$", m.group(1)) and m.group(1).strip():
            expr, name = m.group(1).strip(), m.group(2)
        else:
            expr, name = item, item.split(".")[-1]
        name = name.upper()
        refs: set[str] = set()
        for alias, col in _QUALIFIED.findall(expr):
            if alias.upper() in own_aliases:
                refs.add(col.upper())
        if len(aliases) == 1:
            refs |= {w.upper() for w in _WORD.findall(expr) if w.upper() in table_columns}
        result[name] = ViewColumn(name, expr, name if name in refs else None)
    return result
