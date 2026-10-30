"""插件 `approval`、`approval.service` 的 setup（plugin-spec 第 5 节），以及接线用的 `SnapshotApprovalCatalog`。

- setup：用 contracts 的替代实现提供需要的端口，`Registry().boot` 之后 `FreezeReader`、5 个管道阶段和审批接口的
  `APIRouter` 都已注册，阶段名都是 `STAGE_ORDER` 中的位置。`TableWriter`、`ContextProvider` 在 contracts 中没有替代实现
  （C08 第 5a 节直接用真实实现验证；`ContextProvider` 由 assembly 提供），这里用只为 setup 的最小替身，不会被调用。
- `SnapshotApprovalCatalog`：同一套配置（成本核算页和 C06 7.8、7.9 的两个审批流），经 `ConfigSnapshot.approval_flow_entries`
  和 `EntityDirectory` 得到的结果与原来按配置项内容的 `ItemsApprovalCatalog` 相同。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cost_platform.approval.catalog import SnapshotApprovalCatalog
from cost_platform.approval.freeze import ApprovalFreezeReader
from cost_platform.approval.plugin import MIGRATIONS, ApprovalPlugin, ApprovalServicePlugin
from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import (
    FakeCommandExecutor,
    FakeConfigSnapshot,
    FakeConfigSnapshotReader,
    FakeDirectory,
    FakeDocumentReader,
    FakeEntityDirectory,
    FakeRulesEngine,
    FakeSchemaInspector,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.ports import (
    CommandExecutor,
    ConfigSnapshotReader,
    ContextProvider,
    DirectoryReader,
    DocumentReader,
    EntityDirectory,
    FreezeReader,
    PipelineStage,
    RulesEngine,
    SchemaInspector,
    TableWriter,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView, Registry

from cost_platform.orchestration.runner import STAGE_ORDER

from .support import Config


class _SetupOnlyTableWriter:
    """只为 setup 的 `TableWriter` 替身：setup 不调用它。"""

    def lock_row(self, uow: Any, table: str, key_column: str, key: str) -> None:
        raise AssertionError("setup 不应调用 TableWriter")

    def update(self, uow: Any, table: str, key_column: str, key: str, values: Any) -> None:
        raise AssertionError("setup 不应调用 TableWriter")

    def insert(self, uow: Any, table: str, values: Any) -> str:
        raise AssertionError("setup 不应调用 TableWriter")

    def delete(self, uow: Any, table: str, key_column: str, key: str) -> None:
        raise AssertionError("setup 不应调用 TableWriter")


class _SetupOnlyContext:
    """只为 setup 的 `ContextProvider` 替身：setup 只取它的 `context` 方法交给路由，不调用。"""

    def context(self, request: Any, is_write: bool) -> t.ExecutionContext:
        raise AssertionError("setup 不应调用 ContextProvider")


class Providers:
    name = "fakes"
    provides = (SchemaInspector, DirectoryReader, DocumentReader, RulesEngine, TableWriter, EntityDirectory, ConfigSnapshotReader,
                UnitOfWorkFactory, CommandExecutor, ContextProvider)
    requires = ()

    def setup(self, reg: PluginView) -> None:
        reg.provide(SchemaInspector, FakeSchemaInspector())
        reg.provide(DirectoryReader, FakeDirectory())
        reg.provide(DocumentReader, FakeDocumentReader())
        reg.provide(RulesEngine, FakeRulesEngine())
        reg.provide(TableWriter, _SetupOnlyTableWriter())
        reg.provide(EntityDirectory, FakeEntityDirectory())
        reg.provide(ConfigSnapshotReader, FakeConfigSnapshotReader())
        reg.provide(UnitOfWorkFactory, FakeUnitOfWorkFactory())
        reg.provide(CommandExecutor, FakeCommandExecutor())
        reg.provide(ContextProvider, _SetupOnlyContext())


class Consumer:
    name = "consumer"
    provides = ()
    requires = (FreezeReader, PipelineStage, APIRouter)

    def setup(self, reg: PluginView) -> None:
        self.freeze = reg.get(FreezeReader)
        self.stages = reg.all(PipelineStage)
        self.routers = reg.all(APIRouter)


def test_setup_registers_freeze_reader_stages_and_router() -> None:
    consumer = Consumer()
    ordered = Registry().boot([consumer, ApprovalServicePlugin(), ApprovalPlugin(), Providers()])
    assert [p.name for p in ordered] == ["fakes", "approval", "approval.service", "consumer"]
    assert isinstance(consumer.freeze, ApprovalFreezeReader)
    assert [s.name for s in consumer.stages] == ["确定涉及的单据", "冻结检查", "审批处理", "触发审批", "强制审批检查"]
    assert {s.name for s in consumer.stages} <= set(STAGE_ORDER)
    [router] = consumer.routers
    paths = {(route.path, method) for route in router.routes for method in route.methods}  # type: ignore[attr-defined]
    assert paths == {("/api/approvals", "GET"), ("/api/approvals/{approval_id}", "GET"),
                     ("/api/approvals/{approval_id}/preview", "POST"), ("/api/approvals/{approval_id}/pass", "POST"),
                     ("/api/approvals/{approval_id}/reject", "POST"), ("/api/approvals/{approval_id}/withdraw", "POST")}
    assert (MIGRATIONS / "ap_0001_pf_approval.py").is_file()


def test_snapshot_catalog_matches_items_catalog() -> None:
    config = Config(["COST_TO_GOODS", "TECH_CUSTOMER_MATERIAL"])
    snapshot = FakeConfigSnapshot(version=1, role_code="COST", role=config.roles["COST"], entities=config.entities,
                                  approval_flows={code: flow for code, (_, flow) in config.flows.items()},
                                  flow_names={code: name for code, (name, _) in config.flows.items()})
    roles = FakeConfigSnapshotReader([config.snapshot(code) for code in config.roles])
    catalog = SnapshotApprovalCatalog(snapshot, FakeEntityDirectory(config.entities), roles)
    assert catalog.flows("COST_PINGGU") == config.catalog.flows("COST_PINGGU")
    assert [(f.code, f.name) for f in catalog.flows("COST_PINGGU")] == [
        ("COST_TO_GOODS", "成本明细改价审批"), ("TECH_CUSTOMER_MATERIAL", "技术中心客指物料变更审批")]
    for table in ("T_COST_PINGGU", "T_COST_PINGGU_DTL"):
        assert catalog.entities_on_table(table) == config.catalog.entities_on_table(table)
    assert [(e.code, e.root, e.parent_key) for e in catalog.entities_on_table("T_COST_PINGGU_DTL")] == [
        ("COST_MATERIAL", "COST_PINGGU", "DOCID"), ("COST_PACKAGE", "COST_PINGGU", "DOCID")]
    # 审批人角色的名称取该角色的配置快照（C06 第 8 节），与按配置项内容的相同
    assert [catalog.role_name(code) for code in ("ADMIN", "008", "007")] == ["系统管理员", "采购", "生产"]
    assert [config.catalog.role_name(code) for code in ("ADMIN", "008", "007")] == ["系统管理员", "采购", "生产"]
