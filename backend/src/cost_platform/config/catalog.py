"""内存中的一套配置（C06 的配置项，已按类型解析），供校验、生成页面视图和规则包使用。"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from cost_platform.contracts.types import (
    ApprovalFlowConfig,
    ConfigDraft,
    EntityConfig,
    EscapeHatch,
    MenuConfig,
    MenuItem,
    OperationConfig,
    PageConfig,
    RoleApprover,
    RoleConfig,
    RuleConfig,
    UpdateRecords,
    UpdateTargets,
    parse_config_content,
)

from .records import BASE_TYPES, ItemRecord


@dataclass(frozen=True)
class Entry:
    type: str
    key: str
    name: str
    content: Any
    """按类型解析后的内容（contracts 中 C06 的模型）。"""
    raw: dict[str, Any]
    """原样保存的内容。"""


class Catalog:
    def __init__(self, entries: dict[tuple[str, str], Entry]) -> None:
        self._entries = entries

    @classmethod
    def from_records(cls, records: Iterable[ItemRecord]) -> Catalog:
        entries = {}
        for record in records:
            if record.type in BASE_TYPES:
                raw = record.content()
                entries[(record.type, record.key)] = Entry(record.type, record.key, record.name,
                                                           parse_config_content(record.type, raw), raw)
        return cls(entries)

    def merged(self, drafts: Iterable[ConfigDraft]) -> Catalog:
        """加入或替换这些配置项；内容不符合 C06 结构时抛 pydantic.ValidationError。"""
        entries = dict(self._entries)
        for draft in drafts:
            raw = dict(draft.content)
            entries[(draft.type, draft.key)] = Entry(draft.type, draft.key, draft.name, parse_config_content(draft.type, raw), raw)
        return Catalog(entries)

    def without(self, config_type: str, key: str) -> Catalog:
        return Catalog({k: v for k, v in self._entries.items() if k != (config_type, key)})

    def __iter__(self) -> Iterator[Entry]:
        return iter(sorted(self._entries.values(), key=lambda e: (e.type, e.key)))

    def get(self, config_type: str, key: str) -> Entry | None:
        return self._entries.get((config_type, key))

    def has(self, config_type: str, key: str) -> bool:
        return (config_type, key) in self._entries

    def of_type(self, config_type: str) -> dict[str, Any]:
        return {e.key: e.content for e in self if e.type == config_type}

    # ---------------------------------------------------------------- 常用的取法

    def entity(self, code: str) -> EntityConfig | None:
        found = self._entries.get(("entity", code))
        return None if found is None else found.content

    def page(self, code: str) -> PageConfig | None:
        found = self._entries.get(("page", code))
        return None if found is None else found.content

    def operation(self, code: str) -> OperationConfig | None:
        found = self._entries.get(("operation", code))
        return None if found is None else found.content

    def entities(self) -> dict[str, EntityConfig]:
        return self.of_type("entity")

    def pages(self) -> dict[str, PageConfig]:
        return self.of_type("page")

    def roles(self) -> dict[str, RoleConfig]:
        return self.of_type("role")

    def rules(self) -> dict[str, RuleConfig]:
        return self.of_type("rule")

    def flows(self) -> dict[str, ApprovalFlowConfig]:
        return self.of_type("approvalFlow")

    def menus(self) -> dict[str, MenuConfig]:
        return self.of_type("menu")

    def page_regions(self, page_code: str) -> list[tuple[str, str]]:
        """页面的表格：（区域编码，实体编码）。主表区为 `master`，明细区为明细实体编码（C06 第 8 节的分组）。"""
        page = self.page(page_code)
        if page is None:
            return []
        return [("master", page.master.entity), *((d.entity, d.entity) for d in page.details)]

    def masters(self) -> list[str]:
        """业务对象的主表实体：页面的主表实体（规则包按它一份，C07 第 1 节）。"""
        return sorted({p.master.entity for p in self.pages().values()})

    def business_entities(self, master: str) -> list[str]:
        """业务对象中的实体：主表实体和它的明细实体。"""
        entity = self.entity(master)
        return [master, *(d.entity for d in entity.details)] if entity else [master]

    def masters_of(self, entity_code: str) -> list[str]:
        """包含这个实体的业务对象（主表实体）。"""
        return [m for m in self.masters() if entity_code in self.business_entities(m)]

    def parent_of(self, entity_code: str) -> tuple[str, str] | None:
        """明细实体所属的主表实体和关联字段（实体的 `details`）。"""
        for code, entity in self.entities().items():
            for link in entity.details:
                if link.entity == entity_code:
                    return code, link.parent_key
        return None

    def pages_using_operation(self, operation: str) -> list[str]:
        """页面保存或区域按钮引用了这个操作的页面。"""
        found = []
        for code, page in self.pages().items():
            areas = [page.master, *page.details]
            if page.save_operation == operation or any(b.operation == operation for a in areas for b in a.buttons):
                found.append(code)
        return found

    def entities_on_table(self, table: str) -> list[str]:
        """`table` 为这张表的实体：这张表在平台注册过（C06 7.4、7.5）。"""
        return [code for code, e in self.entities().items() if e.table == table]


def references(config_type: str, content: Any) -> list[tuple[str, str, str]]:
    """配置内容按编码引用的其他配置项：（类型、编码、在内容中的位置）。位置按 C03 的写法，例如 `master.entity`、
    `levels[0].nodes[1].approvers[0].role`。用于引用检查（C06 第 10 节）和删除检查（CF-09）。"""
    refs: list[tuple[str, str, str]] = []

    def actions(steps: Iterable[Any], at: str) -> None:
        for i, step in enumerate(steps):
            here = f"{at}[{i}]"
            if isinstance(step, UpdateTargets):
                for j, target in enumerate(step.targets):
                    refs.append(("entity", target.entity, f"{here}.targets[{j}].entity"))
                    if target.detail_entity:
                        refs.append(("entity", target.detail_entity, f"{here}.targets[{j}].detailEntity"))
            elif isinstance(step, UpdateRecords):
                refs.append(("entity", step.find.entity, f"{here}.find.entity"))
            elif isinstance(step, EscapeHatch):
                refs.append(("operation", step.operation, f"{here}.operation"))

    if config_type == "entity":
        refs += [("entity", d.entity, f"details[{i}].entity") for i, d in enumerate(content.details)]
        refs += [("page", p, f"approvalRequired[{i}].sourcePages[{j}]")
                 for i, rule in enumerate(content.approval_required) for j, p in enumerate(rule.source_pages)]
    elif config_type == "page":
        refs.append(("operation", content.save_operation, "saveOperation"))
        areas = [("master", content.master), *((f"details[{i}]", d) for i, d in enumerate(content.details))]
        for at, area in areas:
            refs.append(("entity", area.entity, f"{at}.entity"))
            refs += [("operation", b.operation, f"{at}.buttons[{j}].operation") for j, b in enumerate(area.buttons) if b.operation]
            for name, setting in area.fields.items():
                if setting.lookup:
                    refs.append(("lookup", setting.lookup.code, f"{at}.fields.{name}.lookup.code"))
                if setting.dict_type:
                    refs.append(("dict", setting.dict_type, f"{at}.fields.{name}.dictType"))
    elif config_type == "operation":
        refs += [("entity", e, f"writableFields.{e}") for e in content.writable_fields]
        refs += [("entity", e, f"impact[{i}]") for i, e in enumerate(content.impact)]
        actions(content.actions, "actions")
    elif config_type == "rule":
        refs.append((content.layer, content.target, "target"))
    elif config_type == "approvalFlow":
        refs.append(("page", content.page, "page"))
        refs += [("entity", e, f"operations.{e}") for e in content.operations]
        refs += [("role", a.role, f"levels[{i}].nodes[{j}].approvers[{k}].role")
                 for i, level in enumerate(content.levels) for j, node in enumerate(level.nodes)
                 for k, a in enumerate(node.approvers) if isinstance(a, RoleApprover)]
        for i, block in enumerate(content.display):
            if block.region in ("master", "detail"):
                refs.append(("entity", block.source, f"display[{i}].source"))
            actions(block.actions, f"display[{i}].actions")
    elif config_type == "role":
        refs += [("page", p, f"pages.{p}") for p in content.pages]
    elif config_type == "menu":
        def walk(items: Iterable[MenuItem], at: str) -> None:
            for i, item in enumerate(items):
                if item.page_code:
                    refs.append(("page", item.page_code, f"{at}[{i}].pageCode"))
                walk(item.children, f"{at}[{i}].children")
        walk(content.items, "items")
    elif config_type == "export":
        refs.append(("page", content.page, "page"))
    return refs


def referrers(catalog: Catalog, config_type: str, key: str) -> list[tuple[Entry, str]]:
    """引用了这一项的其他配置项，以及引用的位置。"""
    found = []
    for entry in catalog:
        if (entry.type, entry.key) == (config_type, key):
            continue
        for ref_type, ref_key, at in references(entry.type, entry.content):
            if (ref_type, ref_key) == (config_type, key):
                found.append((entry, at))
    return found
