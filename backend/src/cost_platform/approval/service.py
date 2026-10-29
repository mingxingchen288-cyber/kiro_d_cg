"""C09 第 6 节的审批接口背后的处理：待办列表、审批详情、预览（只读，不加锁），以及把通过、驳回、撤回转成命令交给
orchestration 的 `CommandExecutor`（C02 第 1 节、架构 10.4）。

- 详情（AP-08、AP-15）：任何已登录的用户都能查看；进度只列已进入的节点和按当前数据推算后面会进入的节点；`view` 按当前
  勾选计算，`params` 为当前用户这次通过要填写的人工参数，`actions` 为当前用户能做的操作。
- 预览：按提交的勾选重算 `view` 和指纹，不保存勾选。
- 处理命令的执行上下文来源为本审批（C04），由各阶段判断能否处理（AP-05、AP-12）。
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from cost_platform.contracts.ports import CommandExecutor, UnitOfWorkFactory
from cost_platform.contracts.types import (
    ApprovalActions,
    ApprovalDetail,
    ApprovalList,
    ApprovalStep,
    ApprovalSummary,
    CheckedRow,
    Command,
    CommandResult,
    ErrorCode,
    ExecutionContext,
    FlowParam,
    Origin,
    PassRequest,
    PlatformError,
    PreviewRequest,
    PreviewResponse,
    RejectRequest,
    SourceRef,
    StepMember,
    UserBrief,
    WithdrawRequest,
    dump_wire,
)

from .approvers import Directory
from .deps import ApprovalDeps
from .model import ApprovalRecord
from .process import NextLevels, apply_checked, editable_blocks, load, manual_for
from .routing import Action, Node, can_withdraw, decide, pending_nodes
from .view import Evaluator

Box = Literal["todo", "mine"]


def summary(record: ApprovalRecord) -> ApprovalSummary:
    return ApprovalSummary(
        approval_id=record.approval_id, page=record.page, page_title=record.page_title, operation=record.operation,
        operation_label=record.operation_label,
        source=SourceRef(entity=record.source.entity, record_key=record.source.record_key, label=record.source_label),
        applicant=UserBrief(user_id=record.applicant_id, display_name=record.applicant_name), submitted_at=record.submitted_at,
        status=record.progress.status, level=record.progress.level)  # type: ignore[arg-type]


def step(record: ApprovalRecord, node: Node, status: str | None = None) -> ApprovalStep:
    flow = record.flow(node.flow)
    members = [StepMember(type=m.kind, id=m.id, name=m.name, status=m.status,
                          processed_by=UserBrief(user_id=m.processed_by, display_name=m.processed_by_name or m.processed_by)
                          if m.processed_by else None, processed_at=m.processed_at, comment=m.comment) for m in node.members]
    return ApprovalStep(level=node.level, flow=node.flow, flow_name=flow.name, node=node.name, mode=node.mode,
                        status=status or node.status, members=members)  # type: ignore[arg-type]


class ApprovalService:
    def __init__(self, deps: ApprovalDeps, uow_factory: UnitOfWorkFactory, executor: CommandExecutor | None = None) -> None:
        self.deps = deps
        self._uow = uow_factory
        self._executor = executor
        self.evaluator = Evaluator(deps)

    # ---------------------------------------------------------------- 待办

    def list(self, ctx: ExecutionContext, box: str, start_row: int, end_row: int) -> ApprovalList:
        """`todo`：当前用户是本级尚未处理的审批人的审批；`mine`：当前用户发起的审批。"""
        if box not in ("todo", "mine"):
            raise PlatformError(ErrorCode.INVALID_REQUEST, "box 只能是 todo 或 mine")
        user = ctx.identity.user_id
        with self._uow.begin() as uow:
            if box == "todo":
                is_member = Directory(self.deps.directory).membership()
                records = [r for r in self.deps.store.pending(uow) if pending_nodes(r.progress, user, is_member)]
            else:
                records = self.deps.store.by_applicant(uow, user)
        return ApprovalList(rows=[summary(r) for r in records[max(start_row, 0):max(end_row, 0)]], total=len(records))

    # ---------------------------------------------------------------- 详情和预览

    def detail(self, ctx: ExecutionContext, approval_id: str) -> ApprovalDetail:
        with self._uow.begin() as uow:
            record = load(self.deps, uow, approval_id)
            affected = self.deps.store.affected(uow, approval_id)
            directory = Directory(self.deps.directory)
            is_member = directory.membership()
            mine = pending_nodes(record.progress, ctx.identity.user_id, is_member)
            computation = self.evaluator.compute(uow, ctx, record, affected, editable=editable_blocks(record, mine))
            upcoming = NextLevels(self.deps, uow, record, computation.scopes, strict=False)
            steps = self._steps(record, upcoming)
            params = self._params(record, mine, upcoming, ctx, is_member)
        actions = ApprovalActions(can_pass=bool(mine), can_reject=bool(mine),
                                  can_withdraw=can_withdraw(record.progress, record.applicant_id, ctx.identity.user_id))
        base = summary(record)
        return ApprovalDetail(approval_id=base.approval_id, status=base.status, page=base.page, page_title=base.page_title,
                              operation=base.operation, operation_label=base.operation_label, source=base.source,
                              applicant=base.applicant, submitted_at=base.submitted_at, current_level=record.progress.level,
                              steps=steps, view=computation.view, fingerprint=computation.fingerprint, params=params,
                              actions=actions)

    def preview(self, ctx: ExecutionContext, approval_id: str, request: PreviewRequest) -> PreviewResponse:
        """审批人改了勾选：按提交的勾选重新计算 `view` 和指纹，不保存勾选（AP-08）。"""
        with self._uow.begin() as uow:
            record = load(self.deps, uow, approval_id)
            affected = self.deps.store.affected(uow, approval_id)
            mine = pending_nodes(record.progress, ctx.identity.user_id, Directory(self.deps.directory).membership())
            editable = editable_blocks(record, mine)
            apply_checked(affected, editable, request.checked_rows)
            computation = self.evaluator.compute(uow, ctx, record, affected, editable=editable)
        return PreviewResponse(view=computation.view, fingerprint=computation.fingerprint)

    def _steps(self, record: ApprovalRecord, upcoming: NextLevels) -> list[ApprovalStep]:
        order = {f.code: i for i, f in enumerate(record.flows)}
        items = [(n.level, order[n.flow], n.index, step(record, n)) for n in record.progress.nodes]
        if record.progress.status == "pending":
            active = record.progress.active_flows()
            level = record.progress.level
            while active:
                level += 1
                still = []
                for flow in active:
                    nodes = upcoming(flow, level)
                    if nodes:
                        still.append(flow)
                        items += [(n.level, order[n.flow], n.index, step(record, n, "upcoming")) for n in nodes]
                active = still
        return [s for *_, s in sorted(items, key=lambda i: i[:3])]

    def _params(self, record: ApprovalRecord, mine: list[Node], upcoming: NextLevels, ctx: ExecutionContext,
                is_member: object) -> list[FlowParam]:
        if not mine:
            return []
        found = manual_for(record, {n.flow for n in mine}, record.progress.level)
        trial = decide(record.progress, Action("pass", ctx.identity.user_id, ctx.identity.display_name, ctx.now),
                       applicant_id=record.applicant_id, is_member=is_member, next_nodes=upcoming)  # type: ignore[arg-type]
        if trial.destination == "end":
            found += manual_for(record, set(record.progress.flows), None)
        return found

    # ---------------------------------------------------------------- 通过、驳回、撤回（转成命令）

    def _execute(self, ctx: ExecutionContext, approval_id: str, operation: str, request_key: str,
                 params: dict[str, object]) -> CommandResult:
        if self._executor is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, "没有接入 CommandExecutor")
        command = Command(request_key=request_key, page=None, operation=operation, documents=[],
                          params={"approvalId": approval_id, **params})  # type: ignore[dict-item]
        local = dataclasses.replace(ctx, origin=Origin(kind="approval", approval_id=approval_id))
        return self._executor.execute(command, local)

    def pass_(self, ctx: ExecutionContext, approval_id: str, request: PassRequest) -> CommandResult:
        return self._execute(ctx, approval_id, "approval.pass", request.request_key, {
            "fingerprint": request.fingerprint, "checkedRows": [dump_wire(CheckedRow, c) for c in request.checked_rows],
            "comment": request.comment, "params": dict(request.params)})

    def reject(self, ctx: ExecutionContext, approval_id: str, request: RejectRequest) -> CommandResult:
        return self._execute(ctx, approval_id, "approval.reject", request.request_key, {"comment": request.comment})

    def withdraw(self, ctx: ExecutionContext, approval_id: str, request: WithdrawRequest) -> CommandResult:
        return self._execute(ctx, approval_id, "approval.withdraw", request.request_key, {"comment": request.comment})


__all__ = ["ApprovalService", "Box", "summary"]
