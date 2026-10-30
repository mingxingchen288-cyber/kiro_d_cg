"""queries-export 的插件（plugin-spec 第 5 节）：用 contracts 的替代实现做提供方，`Registry().boot` 后声明的端口都已注册；
`queries` 的接口从请求的配置快照取 Lookup、字典、导出配置和列表的汇总字段。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import cost_platform.queries.migrations.qe_0001_pf_personal_config as migration
from cost_platform.contracts.fakes import FakeConfigSnapshot, FakeEntityDirectory, FakeFreezeReader, FakePermissionChecker
from cost_platform.contracts.ports import (
    ContextProvider,
    DocumentReader,
    EntityDirectory,
    FreezeReader,
    PermissionChecker,
    RelatedQuery,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import MULTI_PORTS, PluginView, Registry
from cost_platform.contracts.types import DictConfig, DocumentRef, LookupConfig, PageView, RoleConfig, RolePage
from cost_platform.queries.documents import OracleDocumentReader
from cost_platform.queries.plugin import MIGRATIONS, QueriesPlugin, QueryReadersPlugin
from cost_platform.queries.related import OracleRelatedQuery

from .support import PAGE, context, database, entities, page_view, threaded_factory
from .test_exports import export_config


class Provider:
    """替代实现的提供方：一个插件注册给出的端口。"""

    name = "fakes"
    requires: tuple[type, ...] = ()

    def __init__(self, impls: dict[type, Any]) -> None:
        self.provides = tuple(impls)
        self._impls = impls

    def setup(self, reg: PluginView) -> None:
        for port, impl in self._impls.items():
            (reg.add if port in MULTI_PORTS else reg.provide)(port, impl)


class Consumer:
    """取用被测插件注册的端口，记下拿到的实现。"""

    name = "consumer"
    provides: tuple[type, ...] = ()

    def __init__(self, *ports: type) -> None:
        self.requires = ports
        self.got: dict[type, Any] = {}

    def setup(self, reg: PluginView) -> None:
        for port in self.requires:
            self.got[port] = reg.all(port) if port in MULTI_PORTS else reg.get(port)


def test_readers_plugin_registers_related_query_and_document_reader() -> None:
    """`queries.readers` 注册 `RelatedQuery`、`DocumentReader`，实体配置取自 `EntityDirectory`。"""
    consumer = Consumer(RelatedQuery, DocumentReader)
    fakes = Provider({UnitOfWorkFactory: database(), EntityDirectory: FakeEntityDirectory(entities())})
    order = Registry().boot([consumer, QueryReadersPlugin(), fakes])
    assert [p.name for p in order] == ["fakes", "queries.readers", "consumer"]
    assert isinstance(consumer.got[RelatedQuery], OracleRelatedQuery)
    reader = consumer.got[DocumentReader]
    assert isinstance(reader, OracleDocumentReader)
    document = reader.load(DocumentRef("COST_PINGGU", "1002"))
    assert document is not None and [r.row_key for r in document.details["COST_MATERIAL"]] == ["5002", "5003"]
    assert (MIGRATIONS / "qe_0001_pf_personal_config.py").exists()


def summed(view: PageView, *names: str) -> PageView:
    """页面视图中主表的这些字段设为求和（C05 `aggregate`）。"""
    fields = [f.model_copy(update={"aggregate": "sum"}) if f.name in names else f for f in view.master.fields]
    return view.model_copy(update={"master": view.master.model_copy(update={"fields": fields})})


class Context:
    """代替 assembly 的 `ContextProvider`：执行上下文的配置快照带 Lookup、字典和导出配置；主表的总成本求和。"""

    def __init__(self) -> None:
        configs = entities()
        role = RoleConfig(name="成本会计", admin=False, pages={PAGE: RolePage(buttons=["*"])})
        self.snapshot = FakeConfigSnapshot(
            version=13, role_code="COST_ACCOUNTANT", role=role, page_views={PAGE: summed(page_view(configs), "TOTAL_COST")}, pages=[PAGE],
            entities=configs,
            lookups={"GOODS": LookupConfig(table="T_COST_GOODS", columns=["GOODSID", "GOODSNAME"], keyword_columns=["GOODSNAME"],
                                           order_by="GOODSID")},
            dicts={"STATUS": DictConfig(items=[{"value": "1", "label": "启用", "order": 1}])},
            exports={"cost-pinggu-export": export_config()})

    def context(self, request: Any, is_write: bool) -> Any:
        return context(self.snapshot)


def test_queries_plugin_router_reads_config_from_snapshot() -> None:
    """`queries` 注册 C09 第 4 节的路由：字典、Lookup、导出列表来自请求的配置快照；列表的汇总字段取页面视图中
    `aggregate` 为 `sum` 的字段，对全部满足条件的行求和（QE-04）。"""
    factory = database(threaded_factory())
    with factory.engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    consumer = Consumer(APIRouter)
    fakes = Provider({UnitOfWorkFactory: factory, PermissionChecker: FakePermissionChecker(), FreezeReader: FakeFreezeReader(),
                      ContextProvider: Context()})
    order = Registry().boot([consumer, QueriesPlugin(), fakes])
    assert [p.name for p in order] == ["fakes", "queries", "consumer"]
    [router] = consumer.got[APIRouter]
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        assert c.get("/api/dicts/STATUS").json() == {"items": [{"value": "1", "label": "启用"}]}
        found = c.post("/api/lookups/GOODS/search", json={"keyword": "胶", "startRow": 0, "endRow": 50}).json()
        assert [r["values"]["GOODSNAME"] for r in found["rows"]] == ["胶囊壳", "空心胶囊", "胶体二氧化硅"]
        assert c.get(f"/api/pages/{PAGE}/exports").json() == {
            "items": [{"exportCode": "cost-pinggu-export", "name": "物料成本核算表导出"}]}
        rows = c.post(f"/api/pages/{PAGE}/rows", json={"startRow": 0, "endRow": 2})
        assert rows.status_code == 200 and rows.json()["total"] == 5
        assert list(rows.json()["aggregates"]) == ["TOTAL_COST"] and Decimal(rows.json()["aggregates"]["TOTAL_COST"]) == Decimal("46.25")
