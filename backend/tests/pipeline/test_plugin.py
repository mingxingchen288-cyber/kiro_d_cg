"""插件 `pipeline` 的 setup（plugin-spec 第 5 节）：用 contracts 的替代实现提供它需要的端口，`Registry().boot` 之后
`CommandRecorder`、`TableWriter`、`CommandMonitor`、6 个管道阶段和命令审查的路由都已注册，阶段名都是 `STAGE_ORDER` 中的
位置。setup 不连 Redis。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from cost_platform.contracts.fakes import (
    FakeClock,
    FakeContextProvider,
    FakeEntityDirectory,
    FakePermissionChecker,
    FakeRulesEngine,
    FakeSchemaInspector,
)
from cost_platform.contracts.ports import (
    Clock,
    CommandMonitor,
    CommandRecorder,
    ContextProvider,
    EntityDirectory,
    PermissionChecker,
    PipelineStage,
    RulesEngine,
    SchemaInspector,
    TableWriter,
)
from cost_platform.contracts.registry import PluginView, Registry
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.plugin import MIGRATIONS, PipelinePlugin
from cost_platform.pipeline.review import RedisCommandMonitor
from cost_platform.pipeline.table_writer import OracleTableWriter

from .support import STAGE_ORDER, Setup


class Providers:
    name = "fakes"
    provides = (PermissionChecker, RulesEngine, SchemaInspector, Clock, ContextProvider, EntityDirectory)
    requires = ()

    def setup(self, reg: PluginView) -> None:
        reg.provide(PermissionChecker, FakePermissionChecker())
        reg.provide(RulesEngine, FakeRulesEngine())
        reg.provide(SchemaInspector, FakeSchemaInspector())
        reg.provide(Clock, FakeClock(datetime(2026, 10, 29, 10, 0, 0)))
        reg.provide(ContextProvider, FakeContextProvider(Setup().context()))
        reg.provide(EntityDirectory, FakeEntityDirectory())


class Consumer:
    name = "consumer"
    provides = ()
    requires = (CommandRecorder, TableWriter, CommandMonitor, PipelineStage, APIRouter)

    def setup(self, reg: PluginView) -> None:
        self.recorder = reg.get(CommandRecorder)
        self.tables = reg.get(TableWriter)
        self.monitor = reg.get(CommandMonitor)
        self.stages = reg.all(PipelineStage)
        self.routers = reg.all(APIRouter)


def test_setup_registers_recorder_table_writer_monitor_stages_and_router() -> None:
    consumer = Consumer()
    plugin = PipelinePlugin(lock_wait_seconds=5, request_wait_seconds=5, redis_url="redis://127.0.0.1:6379/0",
                            redis_namespace="cp")
    ordered = Registry().boot([consumer, plugin, Providers()])
    assert [p.name for p in ordered] == ["fakes", "pipeline", "consumer"]
    assert isinstance(consumer.recorder, OracleCommandRecorder)
    assert isinstance(consumer.tables, OracleTableWriter)
    assert isinstance(consumer.monitor, RedisCommandMonitor)
    assert [s.name for s in consumer.stages] == ["确定涉及的单据", "加锁读取", "合并修改", "合并意图", "计算与规则", "写入变更"]
    assert {s.name for s in consumer.stages} <= set(STAGE_ORDER)
    [router] = consumer.routers
    assert {(route.path, method) for route in router.routes for method in route.methods} == {  # type: ignore[attr-defined]
        ("/api/admin/command-review", "GET"), ("/api/admin/command-review", "PUT")}
    assert (MIGRATIONS / "wp_0001_pf_command.py").is_file() and (MIGRATIONS / "wp_0002_escape_hatch_calls.py").is_file()
