"""插件 `orchestration` 的 setup（plugin-spec 第 5 节）：用替代实现提供它需要的端口（含 write-pipeline 的 `CommandMonitor`），
`Registry().boot` 之后 `CommandExecutor` 已注册；执行一个命令时经过命令审查。"""

from __future__ import annotations

from cost_platform.contracts.fakes import FakeCommandMonitor, FakeDeliveryDispatcher, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import (
    CommandExecutor,
    CommandMonitor,
    CommandRecorder,
    DeliveryDispatcher,
    PipelineStage,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView, Registry
from cost_platform.orchestration.plugin import OrchestrationPlugin

from ..contracts.support import context, sample_command
from .test_runner import MemoryRecorder, Stages


class Providers:
    name = "fakes"
    provides = (UnitOfWorkFactory, CommandRecorder, CommandMonitor, DeliveryDispatcher, PipelineStage)
    requires = ()

    def __init__(self) -> None:
        self.monitor = FakeCommandMonitor()

    def setup(self, reg: PluginView) -> None:
        reg.provide(UnitOfWorkFactory, FakeUnitOfWorkFactory())
        reg.provide(CommandRecorder, MemoryRecorder())
        reg.provide(CommandMonitor, self.monitor)
        reg.provide(DeliveryDispatcher, FakeDeliveryDispatcher())
        for stage in Stages().stages:
            reg.add(PipelineStage, stage)


class Consumer:
    name = "consumer"
    provides = ()
    requires = (CommandExecutor,)

    def setup(self, reg: PluginView) -> None:
        self.executor = reg.get(CommandExecutor)


def test_setup_registers_executor_that_goes_through_monitor() -> None:
    providers, consumer = Providers(), Consumer()
    ordered = Registry().boot([consumer, OrchestrationPlugin(), providers])
    assert [p.name for p in ordered] == ["fakes", "orchestration", "consumer"]
    command = sample_command()
    assert consumer.executor.execute(command, context()).outcome == "saved"
    assert providers.monitor.watched == [(command.request_key, None)]
