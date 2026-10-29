"""operations 的插件（架构 6.1，`.reports/modules/plugin-spec.md` 第 1、2 节）。

提供管道阶段"确定涉及的单据"（按钮操作，`ButtonInvolvedStage`）和"展开动作"（`ActionStage`）。逃生舱的登记为空
（`EscapeHatchRegistry()`，只登记用户点名启用的逃生舱），执行器为 `SqlEscapeHatchRunner`。

没有接的：`ActionStage.propagation_ended`（OP-03，传播边界 end 的目标单据不触发审批）和 `ActionStage.escape_hatch_calls`
（OP-04，逃生舱调用记录随命令记录写入）。`CommandState` 和 `CommandRecorder` 都没有接收它们的地方（contract-gaps.md 第 2、4 项）。
"""

from __future__ import annotations

from cost_platform.contracts.ports import PipelineStage, RelatedQuery
from cost_platform.contracts.registry import PluginView

from .stages import ActionStage, ButtonInvolvedStage


class OperationsPlugin:
    name = "operations"
    provides = (PipelineStage,)
    requires = (RelatedQuery,)

    def setup(self, reg: PluginView) -> None:
        related = reg.get(RelatedQuery)
        reg.add(PipelineStage, ButtonInvolvedStage(related))
        reg.add(PipelineStage, ActionStage(related))
