"""本模块用到的配置读取：审批流（带编码和名称）和按表找实体（原缺口见 `.reports/modules/approval/contract-gaps.md`
第 1、2 项，2026-10-29 契约已补上 `ConfigSnapshot.approval_flow_entries` 和 `EntityDirectory`）。

- 审批流的编码和名称：审批实例、进度、勾选（C09 的 `flow`、`flowName`）都要用它们。
- 按表找实体：冻结表、修改表注册与否，以及"表 + 主键"所属的实体和单据（C06 7.4、7.5）。

接线时用 `SnapshotApprovalCatalog`（由 `catalog_of(entity_directory)` 经 `CatalogOf` 注入，plugin.py）；
`ItemsApprovalCatalog` 是按给定配置内容的实现，测试直接用。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from cost_platform.contracts.ports import ConfigSnapshot, EntityDirectory
from cost_platform.contracts.types import (
    ApprovalFlowConfig,
    ConfigDraft,
    EntityConfig,
    ExecutionContext,
    parse_config_content,
)


@dataclass(frozen=True)
class NamedFlow:
    """一个审批流：配置项的编码、名称和内容。"""

    code: str
    name: str
    config: ApprovalFlowConfig


@dataclass(frozen=True)
class TableEntity:
    """`table` 为某张表的实体，以及它所属单据的主表实体（主表实体为它自己）和明细关联主表的字段。"""

    code: str
    config: EntityConfig
    root: str
    root_config: EntityConfig
    parent_key: str | None

    @property
    def is_root(self) -> bool:
        return self.code == self.root


class ApprovalCatalog(Protocol):
    def flows(self, page: str) -> list[NamedFlow]:
        """所属页面为 page 的启用审批流，按 `order`、编码排列（C06 7.1，与 `ConfigSnapshot.approval_flows` 相同）。"""
        ...

    def entities_on_table(self, table: str) -> list[TableEntity]:
        """`table` 为这张表的实体；没有时这张表没在平台注册。按实体编码排列。"""
        ...


CatalogOf = Callable[[ExecutionContext], ApprovalCatalog]
"""取本次请求所用的配置（与执行上下文中的配置快照同一版本）。"""


class SnapshotApprovalCatalog:
    """接线用的 `ApprovalCatalog`（2026-10-29 契约补上后）：审批流取本次请求的配置快照
    `ConfigSnapshot.approval_flow_entries`；按表找实体取 `EntityDirectory.entities_on_table`（最新已发布的实体配置，
    端口不带 ctx），实体的配置仍取本次请求的快照。"""

    def __init__(self, snapshot: ConfigSnapshot, entities: EntityDirectory) -> None:
        self._snapshot = snapshot
        self._entities = entities

    def flows(self, page: str) -> list[NamedFlow]:
        return [NamedFlow(e.code, e.name, e.flow) for e in self._snapshot.approval_flow_entries(page)]

    def entities_on_table(self, table: str) -> list[TableEntity]:
        entity = self._snapshot.entity
        return [TableEntity(found.entity, entity(found.entity), found.master, entity(found.master), found.parent_key)
                for found in sorted(self._entities.entities_on_table(table), key=lambda f: f.entity)]


def catalog_of(entities: EntityDirectory) -> CatalogOf:
    """`ApprovalDeps.catalog`：每个请求按它的执行上下文建 `SnapshotApprovalCatalog`。"""
    return lambda ctx: SnapshotApprovalCatalog(ctx.config, entities)


class ItemsApprovalCatalog:
    """按给定配置内容实现 `ApprovalCatalog`：`flows` 为编码 ->（名称、内容），`entities` 为全部实体。"""

    def __init__(self, flows: Mapping[str, tuple[str, ApprovalFlowConfig]], entities: Mapping[str, EntityConfig]) -> None:
        self._flows = dict(flows)
        self._entities = dict(entities)
        self._roots = {link.entity: (code, link.parent_key) for code, e in self._entities.items() for link in e.details}

    @classmethod
    def from_items(cls, items: Iterable[ConfigDraft]) -> ItemsApprovalCatalog:
        flows: dict[str, tuple[str, ApprovalFlowConfig]] = {}
        entities: dict[str, EntityConfig] = {}
        for item in items:
            if item.type == "approvalFlow":
                flows[item.key] = (item.name, parse_config_content(item.type, item.content))  # type: ignore[assignment]
            elif item.type == "entity":
                entities[item.key] = parse_config_content(item.type, item.content)  # type: ignore[assignment]
        return cls(flows, entities)

    def flows(self, page: str) -> list[NamedFlow]:
        found = [NamedFlow(code, name, f) for code, (name, f) in self._flows.items() if f.page == page and f.enabled]
        return sorted(found, key=lambda n: (n.config.order, n.code))

    def entities_on_table(self, table: str) -> list[TableEntity]:
        found = []
        for code in sorted(self._entities):
            entity = self._entities[code]
            if entity.table.upper() != table.upper():
                continue
            root, parent_key = self._roots.get(code, (code, None))
            found.append(TableEntity(code, entity, root, self._entities[root], parent_key))
        return found
