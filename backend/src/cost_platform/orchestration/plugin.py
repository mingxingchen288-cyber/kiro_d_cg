"""orchestration 的插件（架构 6.1）：`CommandExecutor`，消费各模块注册的管道阶段和 write-pipeline、delivery 的端口。

启动时检查阶段与 `STAGE_ORDER` 是否对得上（阶段的 name 不在列表里，或列表里某个位置没有任何实现），不对就拒绝启动。
"""

from __future__ import annotations

from cost_platform.contracts.ports import (
    CommandExecutor,
    CommandRecorder,
    DeliveryDispatcher,
    PipelineStage,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView, RegistryError

from .runner import CommandRunner, stage_problems

__all__ = ["OrchestrationPlugin"]


class OrchestrationPlugin:
    name = "orchestration"
    provides = (CommandExecutor,)
    requires = (UnitOfWorkFactory, CommandRecorder, DeliveryDispatcher, PipelineStage)

    def setup(self, reg: PluginView) -> None:
        stages = reg.all(PipelineStage)
        problems = stage_problems(stages)
        if problems:
            raise RegistryError("插件 orchestration：" + "；".join(problems))
        reg.provide(CommandExecutor, CommandRunner(reg.get(UnitOfWorkFactory), reg.get(CommandRecorder),
                                                   reg.get(DeliveryDispatcher), stages))
