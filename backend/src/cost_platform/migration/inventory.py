"""迁移输出的登记：配置项及其来源（MG-11）、三份清单（MG-02）、迁移报告中的说明（MG-10）。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

ListName = Literal["manual", "escape", "approval"]
LIST_TITLES: dict[ListName, str] = {"manual": "人工改写清单", "escape": "候选逃生舱清单", "approval": "审批确认清单"}


@dataclass(frozen=True)
class Source:
    """旧数据中的位置：旧表名和行的主键，例如 `CMX.T_COST_PAGE_RULE` 中 `ID=475`。"""

    table: str
    key: str

    def text(self) -> str:
        return f"{self.table} {self.key}"


@dataclass
class Item:
    type: str
    key: str
    name: str
    content: dict[str, Any]
    sources: list[Source]


@dataclass
class Entry:
    """清单中的一项。`handling` 说明这次生成怎样处理（没有生成、按旧行为生成等）。"""

    list: ListName
    id: str
    page: str
    title: str
    sources: list[Source]
    original: str
    reason: str
    handling: str
    proposal: str | None = None
    scenario: str | None = None


@dataclass
class Inventory:
    confirmed: Mapping[str, str] = field(default_factory=dict)
    """用户确认过的人工改写：清单项编号到改写后的文本。"""

    items: dict[tuple[str, str], Item] = field(default_factory=dict)
    entries: list[Entry] = field(default_factory=list)
    notes: dict[str, list[str]] = field(default_factory=dict)
    withheld: dict[tuple[str, str], str] = field(default_factory=dict)
    """没有生成的配置项及原因（清单项编号）。"""

    def add(self, type_: str, key: str, name: str, content: dict[str, Any], sources: list[Source]) -> None:
        if (type_, key) in self.withheld:
            return
        self.items[(type_, key)] = Item(type_, key, name, content, sources)

    def withhold(self, type_: str, key: str, entry_id: str) -> None:
        self.withheld[(type_, key)] = entry_id
        self.items.pop((type_, key), None)

    def entry(self, entry: Entry) -> str | None:
        """登记清单项；人工改写清单中用户已确认的项返回确认的文本，调用方据此生成。"""
        if entry.list == "manual" and entry.id in self.confirmed:
            entry.handling = "已按用户确认的改写生成"
            entry.proposal = self.confirmed[entry.id]
            self.entries.append(entry)
            return self.confirmed[entry.id]
        self.entries.append(entry)
        return None

    def note(self, section: str, text: str) -> None:
        bucket = self.notes.setdefault(section, [])
        if text not in bucket:
            bucket.append(text)
