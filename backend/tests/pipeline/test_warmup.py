"""启动时和配置变更后预读已发布实体的表的列定义（WP-15、WP-10）和读取视图读取的表（WP-03）：第一次保存不再多读一次。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from cost_platform.contracts.fakes import (
    FakeClock,
    FakeContextProvider,
    FakeEntityDirectory,
    FakePermissionChecker,
    FakeRulesEngine,
)
from cost_platform.contracts.ports import (
    Clock,
    ContextProvider,
    EntityDirectory,
    PermissionChecker,
    RulesEngine,
    SchemaInspector,
)
from cost_platform.contracts.registry import PluginView, Registry
from cost_platform.pipeline.plugin import PipelinePlugin
from cost_platform.pipeline.values import ColumnScales
from cost_platform.pipeline.warmup import SchemaWarmup

from .support import ENTITIES, MATERIAL_ENTITY, Setup, scales_inspector


def _tables_read(inspector: object) -> list[str]:
    return [c.args[0] for c in inspector.calls_to("columns")]  # type: ignore[attr-defined]


def test_start_preloads_published_tables_and_new_entity_later() -> None:
    """start 读完已发布实体的表才返回；之后发布了液体成本核算的明细（新的表），后台检查时读进来；保存时取小数位不再读。"""
    inspector = scales_inspector()
    scales = ColumnScales(inspector)
    directory = FakeEntityDirectory(ENTITIES)
    warmup = SchemaWarmup(scales, directory, interval=0.05)
    warmup.start()
    try:
        assert _tables_read(inspector) == directory.tables()
        directory.add("COST_MATERIAL_LQ", MATERIAL_ENTITY.model_copy(update={"table": "T_COST_PINGGU_DTL_LQ"}))
        deadline = time.monotonic() + 5
        while "T_COST_PINGGU_DTL_LQ" not in _tables_read(inspector) and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        warmup.stop()
    assert _tables_read(inspector) == [*sorted({e.table for e in ENTITIES.values()}), "T_COST_PINGGU_DTL_LQ"]
    reads = len(inspector.calls_to("columns"))
    scales.scale(MATERIAL_ENTITY.table, "PRICE")
    scales.scale("T_COST_PINGGU_DTL_LQ", "PRICE")
    assert len(inspector.calls_to("columns")) == reads


class _Providers:
    name = "fakes"
    provides = (PermissionChecker, RulesEngine, SchemaInspector, Clock, ContextProvider, EntityDirectory)
    requires = ()

    def __init__(self) -> None:
        self.inspector = scales_inspector()

    def setup(self, reg: PluginView) -> None:
        reg.provide(PermissionChecker, FakePermissionChecker())
        reg.provide(RulesEngine, FakeRulesEngine())
        reg.provide(SchemaInspector, self.inspector)
        reg.provide(Clock, FakeClock(datetime(2026, 10, 29, 10, 0, 0)))
        reg.provide(ContextProvider, FakeContextProvider(Setup().context()))
        reg.provide(EntityDirectory, FakeEntityDirectory(ENTITIES))


def test_plugin_start_preloads_before_ready() -> None:
    """插件 start 返回时已经读完（assembly 在全部插件 start 之后才接受请求）：表的列定义，和读取视图读取的表（WP-03，
    物料、成本核算明细的视图）；stop 停掉后台检查。"""
    providers = _Providers()
    plugin = PipelinePlugin(lock_wait_seconds=5, request_wait_seconds=5, redis_url="redis://127.0.0.1:6379/0",
                            redis_namespace="cp")
    Registry().boot([plugin, providers])
    asyncio.run(plugin.start())
    try:
        assert _tables_read(providers.inspector) == sorted({e.table for e in ENTITIES.values()})
        views = sorted({e.read_view for e in ENTITIES.values() if e.read_view})
        assert views and [c.args[0] for c in providers.inspector.calls_to("view_sources")] == views
    finally:
        asyncio.run(plugin.stop())
