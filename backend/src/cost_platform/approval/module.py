"""approval 提供的能力：`FreezeReader` 和管道阶段（C08 第 6、13 节），由插件 `approval`（plugin.py）注册。

阶段在 `STAGE_ORDER` 中的位置（阶段的 `name`）：
- 确定涉及的单据（审批命令）：`resolve`；
- 冻结检查：`freeze_check`（每个动作一轮时，编排只对这一轮新读入的单据再执行一次，WP-18）；
- 审批处理：`process`；
- 触发审批：`trigger`，之后是强制审批检查 `required`。
"""

from __future__ import annotations

from dataclasses import dataclass

from cost_platform.contracts.ports import PipelineStage

from .deps import ApprovalDeps
from .freeze import ApprovalFreezeReader, FreezeCheckStage
from .process import ProcessStage, ResolveStage
from .required import ApprovalRequiredStage
from .trigger import TriggerStage


@dataclass(frozen=True)
class ApprovalModule:
    freeze_reader: ApprovalFreezeReader
    resolve: ResolveStage
    freeze_check: FreezeCheckStage
    process: ProcessStage
    trigger: TriggerStage
    required: ApprovalRequiredStage

    def stages(self) -> list[PipelineStage]:
        """按架构第 7 节的先后。"""
        return [self.resolve, self.freeze_check, self.process, self.trigger, self.required]


def create_approval(deps: ApprovalDeps) -> ApprovalModule:
    return ApprovalModule(freeze_reader=ApprovalFreezeReader(deps.store), resolve=ResolveStage(deps),
                          freeze_check=FreezeCheckStage(deps.store), process=ProcessStage(deps), trigger=TriggerStage(deps),
                          required=ApprovalRequiredStage())
