"""approval 提供的能力：`FreezeReader` 和管道阶段（C08 第 6、13 节），由 assembly 注册到 orchestration。

阶段在架构第 7 节中的位置：
- 确定涉及的单据（审批命令）：`resolve`；
- 冻结检查：`freeze_check`（动作执行中新找到的单据由 write-pipeline 再执行一次，WP-18）；
- 审批处理：`process`；
- 触发审批：`trigger`，紧接着强制审批检查 `required`（第 8 步）。
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
