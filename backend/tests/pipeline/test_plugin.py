"""插件 `pipeline` 的 setup（plugin-spec 第 5 节）：用 contracts 的替代实现提供它需要的端口，`Registry().boot` 之后
`CommandRecorder`、`TableWriter` 和 6 个管道阶段都已注册，阶段名都是 `STAGE_ORDER` 中的位置。"""

from __future__ import annotations

from cost_platform.contracts.fakes import FakePermissionChecker, FakeRulesEngine, FakeSchemaInspector
from cost_platform.contracts.ports import (
    CommandRecorder,
    PermissionChecker,
    PipelineStage,
    RulesEngine,
    SchemaInspector,
    TableWriter,
)
from cost_platform.contracts.registry import PluginView, Registry
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.plugin import MIGRATIONS, PipelinePlugin
from cost_platform.pipeline.table_writer import OracleTableWriter

from .support import STAGE_ORDER


class Providers:
    name = "fakes"
    provides = (PermissionChecker, RulesEngine, SchemaInspector)
    requires = ()

    def setup(self, reg: PluginView) -> None:
        reg.provide(PermissionChecker, FakePermissionChecker())
        reg.provide(RulesEngine, FakeRulesEngine())
        reg.provide(SchemaInspector, FakeSchemaInspector())


class Consumer:
    name = "consumer"
    provides = ()
    requires = (CommandRecorder, TableWriter, PipelineStage)

    def setup(self, reg: PluginView) -> None:
        self.recorder = reg.get(CommandRecorder)
        self.tables = reg.get(TableWriter)
        self.stages = reg.all(PipelineStage)


def test_setup_registers_recorder_table_writer_and_stages() -> None:
    consumer = Consumer()
    ordered = Registry().boot([consumer, PipelinePlugin(lock_wait_seconds=5, request_wait_seconds=5), Providers()])
    assert [p.name for p in ordered] == ["fakes", "pipeline", "consumer"]
    assert isinstance(consumer.recorder, OracleCommandRecorder)
    assert isinstance(consumer.tables, OracleTableWriter)
    assert [s.name for s in consumer.stages] == ["确定涉及的单据", "加锁读取", "合并修改", "合并意图", "计算与规则", "写入变更"]
    assert {s.name for s in consumer.stages} <= set(STAGE_ORDER)
    assert (MIGRATIONS / "wp_0001_pf_command.py").is_file()
