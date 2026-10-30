"""本模块实现的管道阶段（C08 第 6 节）：按钮操作的"确定涉及的单据"和"展开动作"。

orchestration 按 `STAGE_ORDER` 调用：确定涉及的单据 → 加锁读取 → 冻结检查 → … → 每个动作一轮
（`ActionStage.applies` 为 True 时调用 `run` 展开下一个动作 → write-pipeline 的"加锁读取"→ 只对这一轮新读入的单据
"冻结检查"→ write-pipeline 的"合并意图""计算与规则"）→ 触发审批 → 写入变更 → 命令记录。

传播边界（OP-03）不另做处理：触发审批阶段只对页面保存执行（approval `trigger.py` 的 applies 要求 `command.documents`
不为空，按钮命令的 documents 必须为空），按钮写到的目标本来就不触发审批；按钮写必须审批的字段时由强制审批检查拒绝，
与旧系统（`ActionWriteGuard` → `ApprovalRequiredFieldPolicy.guardDirectMutation`）相同；旧系统也没有 propagation=continue 的级联。
"""

from __future__ import annotations

from cost_platform.contracts.ports import RelatedQuery, UnitOfWork
from cost_platform.contracts.types import (
    CommandState,
    DocumentRef,
    ErrorCode,
    ErrorDetail,
    EscapeHatch,
    ExecutionContext,
    OperationConfig,
    PlatformError,
    Recalculate,
    ReplaceDetails,
    Row,
    SkippedRow,
    UpdateRecords,
    UpdateRows,
    UpdateTargets,
)

from .actions import Round, expand_recalculate, expand_update_records, expand_update_targets
from .escape_hatch import EscapeHatchExecutor, EscapeHatchRegistry, EscapeHatchRunner, SqlEscapeHatchRunner
from .memory import MemoryBook
from .selection import SelectedRow, SelectionResolver, requires_selection, selected_rows, sort_key
from .sql_actions import expand_replace_details, expand_update_rows

_APPROVAL_OPERATIONS = "approval."


def _button_operation(state: CommandState, ctx: ExecutionContext) -> OperationConfig | None:
    """按钮操作（`kind` 为 `action` 或 `escapeHatch`）的配置；页面保存和审批处理为 None。"""
    code = state.command.operation
    if code.startswith(_APPROVAL_OPERATIONS):
        return None
    operation = ctx.config.operation(code)
    return operation if operation.kind in ("action", "escapeHatch") else None


class ButtonInvolvedStage:
    """"确定涉及的单据"的按钮部分（OP-05、OP-08）：写 `involved` 和 `actions`。

    - 命令带了 `documents` 时 400 INVALID_REQUEST：按钮只传选中行的主键（C02 第 1 节）。
    - 页面上引用本操作的按钮要求选中行、`params.selectedRows` 却为空时 422 VALIDATION_FAILED。
    - 选中行所属的单据按（实体、主键）排序写入 `involved`，由 write-pipeline 加锁读取；动作的来源都取加锁读到的数据。
    - `actions` 为操作的通用动作；操作本身是逃生舱（`kind` 为 `escapeHatch`）时为调用它的一个 `escapeHatch` 动作。
    """

    name = "确定涉及的单据"

    def __init__(self, related: RelatedQuery) -> None:
        self._resolver = SelectionResolver(related)

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return _button_operation(state, ctx) is not None

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        command = state.command
        operation = _button_operation(state, ctx)
        if operation is None:
            return
        if command.documents:
            raise PlatformError(ErrorCode.INVALID_REQUEST, "按钮操作只传选中行的主键，documents 必须为空数组")
        rows = selected_rows(command)
        view = ctx.config.page_view(command.page) if command.page is not None else None
        if not rows and view is not None and requires_selection(view, command.operation):
            raise PlatformError(ErrorCode.VALIDATION_FAILED, "请先选中要处理的行",
                                [ErrorDetail(message="这个按钮需要选中行", field="selectedRows")])
        refs = self._resolver.documents(uow, ctx, view, rows) if rows and view is not None else []
        for ref in sorted(set(refs) - set(state.involved), key=sort_key):
            state.involved.append(ref)
        if operation.kind == "escapeHatch":
            state.actions.append(EscapeHatch(action="escapeHatch", operation=command.operation))
        else:
            state.actions.extend(operation.actions)


class ActionStage:
    """"展开动作"（OP-01、OP-02、OP-04、OP-07、OP-09、OP-10）：每次 `run` 展开 `actions` 中的下一个动作。
    `replaceDetails`、`updateRows` 的展开见 `sql_actions.py`。

    `applies` 在还有没执行的动作时为 True。展开结果写入 `intents`；逃生舱在这一轮直接执行，每次调用的记录
    （`EscapeHatchCall.to_record()`）写入 `escape_hatch_calls`，由 write-pipeline 随命令记录写入（OP-04）。第一轮先检查
    选中的行是否还在：已被删除的按操作的 `rowNotFound` 处理，`skip` 写入 `skipped`，`reject` 返回 409 ROW_NOT_FOUND（WP-05）。
    """

    name = "展开动作"

    def __init__(self, related: RelatedQuery, registry: EscapeHatchRegistry | None = None,
                 runner: EscapeHatchRunner | None = None) -> None:
        self._related = related
        self._escape = EscapeHatchExecutor(registry or EscapeHatchRegistry(), runner or SqlEscapeHatchRunner())
        self._book = MemoryBook()

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        memory = self._book.peek(state)
        return (memory.cursor if memory is not None else 0) < len(state.actions)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        memory = self._book.of(state)
        if memory.cursor >= len(state.actions):
            return
        command = state.command
        operation = _button_operation(state, ctx)
        rows = selected_rows(command) if operation is not None else []
        located = self._locate(state, rows)
        if not memory.selection_checked:
            memory.selection_checked = True
            if operation is not None:
                self._check_rows(state, operation, rows, located)
        action = state.actions[memory.cursor]
        memory.cursor += 1
        sources = list(dict.fromkeys(ref for ref, _ in located)) if rows else \
            [ref for ref in state.involved if ref in state.current]
        if isinstance(action, EscapeHatch):
            documents = [(ref, data.master) for ref in sources if (data := state.candidate.get(ref) or state.current.get(ref))]
            calls = self._escape.run(uow, state, ctx, action.operation, located, documents)
            state.escape_hatch_calls += [call.to_record() for call in calls]
            return
        if operation is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"动作 {action.action} 只用于按钮操作")
        view = ctx.config.page_view(command.page) if command.page is not None else None
        rnd = Round(uow=uow, state=state, ctx=ctx, related=self._related, operation_code=command.operation,
                    operation=operation, page_master=view.master.entity if view is not None else None,
                    sources=sources, memory=memory)
        if isinstance(action, Recalculate):
            state.intents.extend(expand_recalculate(rnd, action))
        elif isinstance(action, UpdateRecords):
            state.intents.extend(expand_update_records(rnd, action))
        elif isinstance(action, UpdateTargets):
            state.intents.extend(expand_update_targets(rnd, action))
        elif isinstance(action, ReplaceDetails):
            state.intents.extend(expand_replace_details(rnd, action, memory.cursor - 1))
        elif isinstance(action, UpdateRows):
            state.intents.extend(expand_update_rows(rnd, action))

    @staticmethod
    def _locate(state: CommandState, rows: list[SelectedRow]) -> list[tuple[DocumentRef, Row]]:
        """选中的行在加锁读到的数据中的位置：（所属单据，这一行计算后的数据），按选中的先后；找不到的不在其中。"""
        located: list[tuple[DocumentRef, Row]] = []
        for selected in rows:
            for ref in state.involved:
                data = state.candidate.get(ref) or state.current.get(ref)
                if data is None:
                    continue
                if ref.entity == selected.entity and ref.record_key == selected.row_key:
                    located.append((ref, data.master))
                    break
                row = next((r for r in data.details.get(selected.entity, []) if r.row_key == selected.row_key), None)
                if row is not None:
                    located.append((ref, row))
                    break
        return located

    @staticmethod
    def _check_rows(state: CommandState, operation: OperationConfig, rows: list[SelectedRow],
                    located: list[tuple[DocumentRef, Row]]) -> None:
        """选中的行已不存在时按 `rowNotFound`（WP-05）。write-pipeline 加锁读取时已经记下的不重复记。"""
        present = {(row.entity, row.row_key) for _, row in located}
        missing = [r for r in rows if (r.entity, r.row_key) not in present]
        if not missing:
            return
        if operation.row_not_found == "reject":
            raise PlatformError(ErrorCode.ROW_NOT_FOUND, "选中的数据已被删除",
                                [ErrorDetail(message="记录已不存在", entity=r.entity, row_key=r.row_key) for r in missing])
        known = {(s.entity, s.row_key) for s in state.skipped}
        for r in missing:
            if (r.entity, r.row_key) not in known:
                state.skipped.append(SkippedRow(entity=r.entity, row_key=r.row_key, reason="ROW_NOT_FOUND"))
