"""计算与规则（WP-08）和必填检查（WP-07），动作执行阶段中 write-pipeline 的部分。

写入以 rules-core commit 阶段的结果为准。求值请求中各行的 `old` 取加锁读取时读到的当前值（多个动作时始终取命令开始时的
值），不另查数据库；计算带出的变化并入同一个变更计划，包括 Patch 未涉及的行，例如汇总到的主表行。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable

from cost_platform.contracts.ports import RulesEngine
from cost_platform.contracts.types import (
    ChangedRow,
    CommandState,
    DocumentData,
    DocumentRef,
    MasterAdd,
    MasterDelete,
    MasterModify,
    ErrorCode,
    ErrorDetail,
    EvalComputed,
    EvalContext,
    EvalDocument,
    EvalFailure,
    EvalRow,
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    FieldState,
    PlatformError,
    Prompt,
    PromptEffect,
    RejectEffect,
    Row,
    dump_wire,
    parse_wire,
)
from cost_platform.contracts.values import from_wire, to_wire

from .merge import RowRef, Scales
from .plan import find_change, note_modify, row_id
from .values import NoScales, stored_value

FieldStates = dict[RowRef, dict[str, FieldState]]
"""rules-core 给出的每行字段状态（可编辑、必填），必填检查用。"""


def _rows(doc: DocumentData) -> Iterable[Row]:
    yield doc.master
    for rows in doc.details.values():
        yield from rows


def _find(rows: Iterable[Row], key: str | None) -> Row | None:
    return next((r for r in rows if key is not None and key in (r.row_key, r.client_row_id)), None)


def _master_deleted(state: CommandState, ref: DocumentRef) -> bool:
    change = find_change(state.changes, ref.entity, ref.record_key)
    return change is not None and change.op == "delete"


def pack_id_of(state: CommandState, ctx: ExecutionContext, ref: DocumentRef) -> str:
    """单据的规则包：本页面的单据用页面视图的规则包；不是本页面的单据（动作写到的目标）用它主表实体的规则包
    （C07 第 1 节：packId 是主表实体的编码）。"""
    page = state.command.page
    if page is not None:
        view = ctx.config.page_view(page)
        if view.master.entity == ref.entity:
            return view.rules_pack.pack_id
    return ref.entity


def needs_recalculation(state: CommandState, ctx: ExecutionContext, ref: DocumentRef) -> bool:
    """WP-08（用户 2026-10-29 选定）：这张单据有新增、删除的行，或者改到了保存时执行的规则读取的字段
    （`ConfigSnapshot.rule_fields`），才求值。只改备注这类字段时不求值，其他列保持原样。"""
    used = ctx.config.rule_fields(pack_id_of(state, ctx, ref))
    for change in state.changes.rows:
        if change.document != ref:
            continue
        if change.op in ("add", "delete") or set(change.values) & used.get(change.entity, frozenset()):
            return True
    return False


def patch_needs_details(state: CommandState, ctx: ExecutionContext) -> Callable[[DocumentRef], bool]:
    """页面保存加锁读取时，哪些单据要读明细（WP-08、WP-10）：Patch 改了明细、删除整张单据，或者主表改到了规则读取的
    字段（要按整张单据求值）。其余单据只锁主表行，不读明细，也不会求值（`needs_recalculation` 为 False）。"""
    wanted: set[DocumentRef] = set()
    for patch in state.command.documents:
        master = patch.master
        if isinstance(master, MasterAdd):
            continue
        ref = DocumentRef(entity=patch.entity, record_key=master.row_key)
        if patch.details or isinstance(master, MasterDelete):
            wanted.add(ref)
        elif isinstance(master, MasterModify):
            used = ctx.config.rule_fields(pack_id_of(state, ctx, ref)).get(patch.entity, frozenset())
            if set(master.changes) & used:
                wanted.add(ref)
    return wanted.__contains__


class Recalculator:
    def __init__(self, engine: RulesEngine, scales: Scales | None = None) -> None:
        self._engine = engine
        self._scales = scales or NoScales()

    def run(self, state: CommandState, ctx: ExecutionContext, refs: Iterable[DocumentRef] | None = None) -> FieldStates:
        """对有变化的单据（或 `refs`）按 commit 阶段求值；删除的单据不算。规则拒绝时 422 RULE_REJECTED，
        提示写入 `prompts`，效果写入 `effects`。"""
        if refs is None:
            touched = {c.document for c in state.changes.rows}
            refs = [r for r in state.candidate if r in touched]
        states: FieldStates = {}
        rejects: list[RejectEffect] = []
        for ref in list(refs):
            if ref not in state.candidate or _master_deleted(state, ref) or not needs_recalculation(state, ctx, ref):
                continue
            result = self._evaluate(state, ctx, ref, state.candidate[ref])
            self._apply(state, ctx, ref, result, states)
            state.effects.extend(result.effects)
            for effect in result.effects:
                if isinstance(effect, RejectEffect):
                    rejects.append(effect)
                elif isinstance(effect, PromptEffect):
                    state.prompts.append(Prompt(rule=effect.rule, message=effect.message, entity=effect.entity,
                                                row_key=effect.row_key, client_row_id=effect.client_row_id, field=effect.field))
        if rejects:
            raise PlatformError(ErrorCode.RULE_REJECTED, rejects[0].message, [
                ErrorDetail(message=e.message, entity=e.entity, row_key=e.row_key, client_row_id=e.client_row_id, field=e.field)
                for e in rejects])
        return states

    def _evaluate(self, state: CommandState, ctx: ExecutionContext, ref: DocumentRef, doc: DocumentData) -> EvalComputed:
        changed: list[ChangedRow] = []
        for change in state.changes.rows:
            if change.document != ref:
                continue
            key = {"client_row_id": change.client_row_id} if change.op == "add" and change.client_row_id else {"row_key": change.row_key}
            fields = [] if change.op == "delete" else list(change.values)
            changed.append(ChangedRow(entity=change.entity, op=change.op, fields=fields, **key))  # type: ignore[arg-type]

        def eval_row(row: Row) -> EvalRow:
            entity = ctx.config.entity(row.entity)
            types = {f.name: f.type for f in entity.fields}
            values = {name: to_wire(types[name], row.values.get(name)) for name in types}
            change = find_change(state.changes, row.entity, row.client_row_id or row.row_key or "")
            if row.client_row_id:
                return EvalRow(client_row_id=row.client_row_id, values=values)
            old = None
            if change is not None and change.op == "modify":
                old = {name: to_wire(types[name], value) for name, value in change.old.items()}
            return EvalRow(row_key=row.row_key, values=values, old=old)

        request = EvaluationRequest(
            purpose="operation", operation=state.command.operation, page=state.command.page, phase="commit",
            context=EvalContext(user_id=ctx.identity.user_id, department_id=ctx.identity.department_id,
                                role=ctx.identity.role_code, today=ctx.now.date(), origin=ctx.origin.kind),
            document=EvalDocument(entity=ref.entity, master=eval_row(doc.master),
                                  details={code: [eval_row(r) for r in rows] for code, rows in doc.details.items()}),
            changed=changed,
            data={},  # 规则需要的数据库数据：配置快照没有给出规则的 dataItems，见 contract-gaps.md
        )
        handle = ctx.config.rules_pack(pack_id_of(state, ctx, ref))
        raw = self._engine.evaluate(handle, json.dumps(dump_wire(EvaluationRequest, request), ensure_ascii=False))
        result = parse_wire(EvaluationResult, json.loads(raw))
        if isinstance(result, EvalFailure):
            raise PlatformError(ErrorCode.INTERNAL_ERROR, "规则计算失败")
        return result

    def _apply(self, state: CommandState, ctx: ExecutionContext, ref: DocumentRef, result: EvalComputed,
               states: FieldStates) -> None:
        """计算出的值按 WP-15 处理后与命令开始时的值比较，有变化的并入变更计划；删除的行不改。
        只在视图中的字段（`column` 为 null）只更新候选数据，不写。"""
        doc = state.candidate[ref]
        current = state.current.get(ref)
        for found in result.rows:
            key = found.client_row_id or found.row_key
            row = _find(_rows(doc), key)
            if row is None or row.entity != found.entity:
                continue
            states[row_id(row)] = dict(found.fields)
            change = find_change(state.changes, row.entity, key or "")
            if change is not None and change.op == "delete":
                continue
            entity = ctx.config.entity(row.entity)
            fields = {f.name: f for f in entity.fields}
            original_row = _find(_rows(current), row.row_key) if current is not None and row.row_key else None
            for name, wire in found.computed.items():
                field = fields.get(name)
                if field is None:
                    continue
                value = stored_value(field.type, from_wire(field.type, wire), self._scales.scale(entity.table, field.column))
                if field.column is None:
                    row.values[name] = value
                    continue
                original = original_row.values.get(name) if original_row is not None else None
                note_modify(state, ref, row, name, field.type, value, original)


def _required_fields(ctx: ExecutionContext, state: CommandState) -> dict[str, dict[str, bool]]:
    """各实体的必填字段：用户发起时取页面视图（实体、页面、角色叠加后的结果），否则取实体的 fieldDefaults。"""
    page = state.command.page
    if page is not None:
        view = ctx.config.page_view(page)
        areas = [view.master, *view.details]
        return {area.entity: {f.name: f.required for f in area.fields} for area in areas}
    return {}


def check_required(state: CommandState, ctx: ExecutionContext, patched: set[RowRef], field_states: FieldStates) -> None:
    """WP-07：只检查本次新增和修改的行（`patched`），检查这些行的全部必填字段；只因计算发生变化的行不检查。
    规则给出的必填（C07 结果的 `fields`）一起检查。为空时 422 VALIDATION_FAILED，逐项给出字段。"""
    if not patched:
        return
    by_page = _required_fields(ctx, state)
    problems: list[ErrorDetail] = []
    for ref, doc in state.candidate.items():
        for row in _rows(doc):
            ident = row_id(row)
            if ident not in patched:
                continue
            change = find_change(state.changes, row.entity, ident[1])
            if change is not None and change.op == "delete":
                continue
            entity = ctx.config.entity(row.entity)
            required = dict(by_page.get(row.entity) or {n: bool(f.required) for n, f in entity.field_defaults.items()})
            for name, field_state in field_states.get(ident, {}).items():
                if field_state.required is not None:
                    required[name] = field_state.required
            labels = {f.name: f.label for f in entity.fields}
            for name in (f.name for f in entity.fields):
                value = row.values.get(name)
                if required.get(name) and (value is None or value == ""):
                    problems.append(ErrorDetail(message=f"{labels[name]} 不能为空", entity=row.entity,
                                                row_key=None if row.client_row_id else row.row_key,
                                                client_row_id=row.client_row_id, field=name))
    if problems:
        raise PlatformError(ErrorCode.VALIDATION_FAILED, "有必填字段没有填写", problems)
