"""本模块用到的配置读取：审批流（带编码和名称）和按表找实体（原缺口见 `.reports/modules/approval/contract-gaps.md`
第 1、2 项，2026-10-29 契约已补上 `ConfigSnapshot.approval_flow_entries` 和 `EntityDirectory`）。

- 审批流的编码和名称：审批实例、进度、勾选（C09 的 `flow`、`flowName`）都要用它们。
- 按表找实体：冻结表、修改表注册与否，以及"表 + 主键"所属的实体和单据（C06 7.4、7.5）。
- 角色名称：审批进度中按角色配置的审批人显示角色名称（C09 第 6 节样例的"系统管理员"），不显示编码。

接线时用 `SnapshotApprovalCatalog`（由 `catalog_of(entity_directory, config_reader)` 经 `CatalogOf` 注入，plugin.py）；
`ItemsApprovalCatalog` 是按给定配置内容的实现，测试直接用。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from cost_platform.contracts.ports import ConfigSnapshot, ConfigSnapshotReader, EntityDirectory
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

    def role_name(self, code: str) -> str:
        """角色名称（C06 第 8 节角色配置项的名称）：审批进度中按角色配置的审批人显示它（C09 第 6 节 `members[].name`）。"""
        ...


CatalogOf = Callable[[ExecutionContext], ApprovalCatalog]
"""取本次请求所用的配置（与执行上下文中的配置快照同一版本）。"""


class SnapshotApprovalCatalog:
    """接线用的 `ApprovalCatalog`（2026-10-29 契约补上后）：审批流取本次请求的配置快照
    `ConfigSnapshot.approval_flow_entries`；按表找实体取 `EntityDirectory.entities_on_table`（最新已发布的实体配置，
    端口不带 ctx），实体的配置仍取本次请求的快照；角色名称取该角色的配置快照（`ConfigSnapshotReader.read(角色).role()`，
    同 identity 的 `describe_role_from`）。"""

    def __init__(self, snapshot: ConfigSnapshot, entities: EntityDirectory, roles: ConfigSnapshotReader) -> None:
        self._snapshot = snapshot
        self._entities = entities
        self._roles = roles

    def flows(self, page: str) -> list[NamedFlow]:
        return [NamedFlow(e.code, e.name, e.flow) for e in self._snapshot.approval_flow_entries(page)]

    def entities_on_table(self, table: str) -> list[TableEntity]:
        entity = self._snapshot.entity
        return [TableEntity(found.entity, entity(found.entity), found.master, entity(found.master), found.parent_key)
                for found in sorted(self._entities.entities_on_table(table), key=lambda f: f.entity)]

    def role_name(self, code: str) -> str:
        return self._roles.read(code).role().name


def catalog_of(entities: EntityDirectory, roles: ConfigSnapshotReader) -> CatalogOf:
    """`ApprovalDeps.catalog`：每个请求按它的执行上下文建 `SnapshotApprovalCatalog`。"""
    return lambda ctx: SnapshotApprovalCatalog(ctx.config, entities, roles)


class ItemsApprovalCatalog:
    """按给定配置内容实现 `ApprovalCatalog`：`flows` 为编码 ->（名称、内容），`entities` 为全部实体，`roles` 为角色编码 -> 名称。"""

    def __init__(self, flows: Mapping[str, tuple[str, ApprovalFlowConfig]], entities: Mapping[str, EntityConfig],
                 roles: Mapping[str, str] | None = None) -> None:
        self._flows = dict(flows)
        self._entities = dict(entities)
        self._role_names = dict(roles or {})
        self._roots = {link.entity: (code, link.parent_key) for code, e in self._entities.items() for link in e.details}

    @classmethod
    def from_items(cls, items: Iterable[ConfigDraft]) -> ItemsApprovalCatalog:
        flows: dict[str, tuple[str, ApprovalFlowConfig]] = {}
        entities: dict[str, EntityConfig] = {}
        roles: dict[str, str] = {}
        for item in items:
            if item.type == "approvalFlow":
                flows[item.key] = (item.name, parse_config_content(item.type, item.content))  # type: ignore[assignment]
            elif item.type == "entity":
                entities[item.key] = parse_config_content(item.type, item.content)  # type: ignore[assignment]
            elif item.type == "role":
                roles[item.key] = parse_config_content(item.type, item.content).name  # type: ignore[union-attr]
        return cls(flows, entities, roles)

    def role_name(self, code: str) -> str:
        return self._role_names[code]

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
