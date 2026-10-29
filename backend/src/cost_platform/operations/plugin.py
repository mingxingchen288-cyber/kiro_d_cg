"""operations 的插件（架构 6.1，`.reports/modules/plugin-spec.md` 第 1、2 节）。

提供管道阶段"确定涉及的单据"（按钮操作，`ButtonInvolvedStage`）和"展开动作"（`ActionStage`）。逃生舱的登记为空
（`EscapeHatchRegistry()`，只登记用户点名启用的逃生舱），执行器为 `SqlEscapeHatchRunner`；逃生舱的调用记录写进
`CommandState.escape_hatch_calls`，由 write-pipeline 随命令记录写入（OP-04）。

传播边界（OP-03）不另接：触发审批只对页面保存执行，按钮写到的目标本来就不触发审批；按钮写必须审批的字段时由强制审批检查
拒绝，与旧系统（`ApprovalRequiredFieldPolicy.guardDirectMutation`）相同，旧系统也没有 propagation=continue 的级联。
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
