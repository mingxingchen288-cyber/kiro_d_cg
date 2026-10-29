"""命令结果（WP-12）和审计差异的内容（WP-11）。

受影响行取自候选数据，不再查询数据库，每行给出实体的全部字段；值已按 WP-15 处理，与数据库相同。提交审批的单据中，
被修改和删除的行给出正式值（命令开始时读到的当前值）并标出冻结它的审批，新增的行还没有写入，不在其中（C02 第 2 节）。
"""

from __future__ import annotations

from collections.abc import Iterable

from cost_platform.contracts.types import (
    CommandResult,
    CommandState,
    DeletedRow,
    DocumentData,
    DocumentRef,
    ExecutionContext,
    FrozenMark,
    ResultRow,
    Row,
    RowChange,
)
from cost_platform.contracts.values import to_wire


def _row(doc: DocumentData | None, change: RowChange) -> Row | None:
    if doc is None:
        return None
    rows = [doc.master, *(r for rows in doc.details.values() for r in rows)]
    key = change.client_row_id if change.op == "add" and change.client_row_id else change.row_key
    return next((r for r in rows if r.entity == change.entity and key in (r.row_key, r.client_row_id)), None)


def _result_row(ctx: ExecutionContext, row: Row, change: RowChange, frozen: FrozenMark | None) -> ResultRow:
    entity = ctx.config.entity(row.entity)
    values = {f.name: to_wire(f.type, row.values.get(f.name)) for f in entity.fields}
    return ResultRow(entity=row.entity, row_key=row.row_key or change.row_key or "",
                     client_row_id=change.client_row_id if change.op == "add" else None, values=values, frozen=frozen)


def written_changes(state: CommandState) -> list[RowChange]:
    """本命令写入业务表的行：提交审批的单据不写。"""
    return [c for c in state.changes.rows if c.document not in state.pending_documents]


def build_result(state: CommandState, ctx: ExecutionContext) -> CommandResult:
    """`outcome`（C02 第 2 节）：触发审批阶段给出的 approvalSubmitted 优先；否则本命令处理了审批（"审批处理"阶段写了
    `approvals`，C08 第 6 节）为 approvalProcessed，审批中途通过、驳回、撤回不写业务表也要提交；否则有写入为 saved，
    没有为 unchanged。调用过逃生舱也算有写入（它在命令事务里直接写库，OP-04）：结果为 saved，命令提交，调用记录随命令
    记录写入；否则 unchanged 不提交，逃生舱的写入会一起回滚。"""
    frozen = {DocumentRef(a.document.entity, a.document.record_key): FrozenMark(approval_id=a.approval_id)
              for a in state.approvals}
    rows: list[ResultRow | DeletedRow] = []
    written = written_changes(state)
    for change in written:
        if change.op == "delete":
            rows.append(DeletedRow(entity=change.entity, row_key=change.row_key or "", deleted=True))
            continue
        row = _row(state.candidate.get(change.document), change)
        if row is not None:
            rows.append(_result_row(ctx, row, change, None))
    for change in state.changes.rows:
        if change.document not in state.pending_documents or change.op == "add":
            continue
        row = _row(state.current.get(change.document), change)
        if row is not None:
            rows.append(_result_row(ctx, row, change, frozen.get(change.document)))
    id_map = {c.client_row_id: c.row_key for c in state.changes.rows
              if c.op == "add" and c.client_row_id and c.row_key is not None}
    outcome = state.outcome or ("approvalProcessed" if state.approvals
                                else "saved" if written or state.escape_hatch_calls else "unchanged")
    return CommandResult(request_key=state.command.request_key, outcome=outcome, rows=rows, id_map=id_map,
                         prompts=list(state.prompts), skipped=list(state.skipped), approvals=list(state.approvals))


def audit_changes(state: CommandState, ctx: ExecutionContext, extra: Iterable[RowChange] = ()) -> list[RowChange] | None:
    """审计差异（WP-11）：页面开启审计时为写入的行（含级联删除的明细）；`extra` 为 `TableWriter` 写没注册的表的改动，
    不看页面的 `audit`，总是记录（WP-19）。都没有时为 None，命令记录中不记审计差异。"""
    page = state.command.page
    audited = ctx.config.page_view(page).audit if page is not None else False
    rows = (written_changes(state) if audited else []) + list(extra)
    return rows if audited or rows else None
