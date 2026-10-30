"""approval 的管道阶段通过 `PipelineStage` 的契约测试（C08 第 6、14 节）：每个阶段只写阶段表中它负责的字段。

强制审批检查（AP-18）在阶段表中归在"触发审批"一行（架构第 7 节第 8 步），不写 `CommandState`。
最终批准时"审批处理"阶段还要写 `intents`（AP-10），阶段表的"写入"一栏没有列出，见 contract-gaps.md 第 3 条；这里的
审批处理场景是中途一级通过，只写 `approvals`、`notifications`，最终批准写 `intents` 由 test_process.py 验证。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack

import pytest

from cost_platform.contracts import types as t

from ..contracts.test_pipeline_stage import PipelineStageContract, StageCase
from .support import ADMIN, YANGNA, Harness, _dtl, cost, modify
from .test_freeze import e37_save


class ApprovalStageHarness:
    kinds = frozenset({"确定涉及的单据", "冻结检查", "审批处理", "触发审批"})

    def __init__(self) -> None:
        self._stack = ExitStack()

    def close(self) -> None:
        self._stack.close()

    def _setup(self) -> tuple[Harness, t.ApprovalRef, object]:
        h = Harness(["COST_TO_GOODS"])
        approval = e37_save(h, "90")
        uow = self._stack.enter_context(h.uow.begin())
        return h, approval, uow

    def _command(self, h: Harness, page: str | None, operation: str, documents: list, params: dict) -> t.Command:
        return t.parse_wire(t.Command, {"requestKey": h.request_key(), "page": page, "operation": operation,
                                        "documents": documents, "params": params})

    def cases(self) -> list[StageCase]:
        h, approval, uow = self._setup()
        found = []
        # 触发审批：成本单 2602（说明用的假设数据）把滑石粉（116，清单价 12）的单价改成 15，走到触发审批之前。
        # 每个场景是一个命令，各用自己的事务（加锁顺序按事务检查）
        h.world.add_cost(2602, "说明用成本单", [_dtl(260201, 2602, 116, "12", "1")])
        save = self._command(h, "COST_PINGGU", "COST_PINGGU.save", [cost(2602, modify("COST_MATERIAL", 260201, PRICE="15"))], {})
        ctx = h.ctx(YANGNA)
        own = self._stack.enter_context(h.uow.begin())
        state = h.pipeline.prepare(own, save, ctx)
        found.append(StageCase("触发审批", h.approval.trigger, state, ctx, own))  # type: ignore[arg-type]
        memo = self._command(h, "COST_PINGGU", "COST_PINGGU.save", [cost(2556, modify("COST_MATERIAL", 103681, MEMO="改"))], {})
        other = self._stack.enter_context(h.uow.begin())
        found.append(StageCase("触发审批", h.approval.required, h.pipeline.prepare(other, memo, ctx), ctx, other))  # type: ignore[arg-type]
        found.append(StageCase("确定涉及的单据", h.approval.trigger_scope, t.CommandState(command=memo), ctx, uow))  # type: ignore[arg-type]
        # 冻结检查：没有冻结的单据
        check = t.CommandState(command=save, involved=[t.DocumentRef("COST_PINGGU", "2556")])
        found.append(StageCase("冻结检查", h.approval.freeze_check, check, ctx, uow))  # type: ignore[arg-type]
        # 确定涉及的单据、审批处理：系统管理员通过第 1 级
        fingerprint = h.detail(ADMIN, approval.approval_id).fingerprint
        command = self._command(h, None, "approval.pass", [], {"approvalId": approval.approval_id, "fingerprint": fingerprint,
                                                               "checkedRows": [], "comment": None, "params": {}})
        actx = h.config.ctx(ADMIN, origin=t.Origin(kind="approval", approval_id=approval.approval_id))
        found.append(StageCase("确定涉及的单据", h.approval.resolve, t.CommandState(command=command), actx, uow))  # type: ignore[arg-type]
        ref = t.DocumentRef("COST_PINGGU", "2550")
        processing = t.CommandState(command=command, involved=[ref], current={ref: h.world.load(ref)})  # type: ignore[dict-item]
        found.append(StageCase("审批处理", h.approval.process, processing, actx, uow))  # type: ignore[arg-type]
        return found

    def failing_cases(self) -> list[StageCase]:
        h, approval, uow = self._setup()
        save = self._command(h, "COST_PINGGU", "COST_PINGGU.save", [cost(2550, modify("COST_MATERIAL", 206325, MEMO="改"))], {})
        state = t.CommandState(command=save, involved=[t.DocumentRef("COST_PINGGU", "2550")])
        return [StageCase("冻结检查", h.approval.freeze_check, state, h.ctx(ADMIN), uow)]  # type: ignore[arg-type]


class TestApprovalStages(PipelineStageContract):
    @pytest.fixture
    def harness(self) -> Iterator[ApprovalStageHarness]:
        harness = ApprovalStageHarness()
        yield harness
        harness.close()
