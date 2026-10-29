"""插件 `operations` 的 setup（plugin-spec 第 5 节）：用 contracts 的 `FakeRelatedQuery` 提供 `RelatedQuery`，
`Registry().boot` 之后两个管道阶段已注册，名称是 `STAGE_ORDER` 中的位置"确定涉及的单据""展开动作"。"""

from __future__ import annotations

from cost_platform.contracts.fakes import FakeRelatedQuery
from cost_platform.contracts.ports import PipelineStage, RelatedQuery
from cost_platform.contracts.registry import PluginView, Registry
from cost_platform.operations.plugin import OperationsPlugin
from cost_platform.operations.stages import ActionStage, ButtonInvolvedStage


class Providers:
    name = "fakes"
    provides = (RelatedQuery,)
    requires = ()

    def setup(self, reg: PluginView) -> None:
        reg.provide(RelatedQuery, FakeRelatedQuery())


class Consumer:
    name = "consumer"
    provides = ()
    requires = (PipelineStage,)

    def setup(self, reg: PluginView) -> None:
        self.stages = reg.all(PipelineStage)


def test_setup_registers_two_stages() -> None:
    consumer = Consumer()
    ordered = Registry().boot([consumer, OperationsPlugin(), Providers()])
    assert [p.name for p in ordered] == ["fakes", "operations", "consumer"]
    assert [(type(s), s.name) for s in consumer.stages] == [(ButtonInvolvedStage, "确定涉及的单据"), (ActionStage, "展开动作")]
