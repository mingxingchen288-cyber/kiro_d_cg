"""审批命令（`approval.pass`、`approval.reject`、`approval.withdraw`，C02 第 1 节）的"确定涉及的单据"和"审批处理"阶段。

通过（AP-04、AP-05、AP-07、AP-08、AP-16、AP-20）：核对结果指纹 → 记录处理和勾选，同一账号计入本级他所在的全部节点 →
本级完成时各审批流分别判断下一级的节点或终点（第 2 级起只对触发行判断入口条件，参数取这一行合并待审修改、计算后的值）
→ 全部审批流到达终点时（AP-09、AP-10）：先把待审修改展开为写入意图，再按审批流的 `order`、块的顺序对勾选的行执行操作：
修改表注册过的展开为写入意图交给 write-pipeline（照常校验、计算、写入、审计），没注册的经 `TableWriter` 加行锁、做冻结
检查后按主键写入、不重算；然后解除冻结。审批中途任何一级通过都只记录处理、勾选和参数，不写业务表（AP-20）。

驳回、撤回（AP-11、AP-12）：写处理记录和原因，审批状态改为已驳回或已撤回，待审修改标为作废，删除本审批的冻结记录，
生成通知意图。驳回必须填写原因；只有发起人能撤回，只要有人做过通过就不能撤回。

结束（最终通过、驳回、撤回）时把那一刻的修改内容存进审批（`final_view`），已结束的审批详情显示它（C06 7.6）；
对照旧系统送审时存下展示快照、查看历史不再执行 SQL（`ApprovalPresentationService.readSnapshot`）。

命令的执行上下文来源为本审批（C04）：可以写本审批冻结的数据，写入不再触发审批。
对照旧系统 `ConfiguredApprovalRuntime.approve`、`approveComposite`、`reject`、`cancel`、`finish`、`applyPending`。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    ApprovalRef,
    CheckedRow,
    CommandState,
    DocumentRef,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    FlowParam,
    MasterAdd,
    PlatformError,
    RecordRef,
    RowIntent,
    parse_wire,
)

from . import notify
from .approvers import Directory, resolve
from .calc import coerce
from .catalog import ApprovalCatalog
from .deps import ApprovalDeps
from .freeze import check_rows
from .model import AffectedRow, ApprovalRecord, ProcessRecord
from .patch import patch_intents
from .routing import Action, Node, decide, pending_nodes
from .rows import column_field, owners
from .sql import RowScope, exists, key_text
from .trigger import level_of, node_entered
from .view import Computation, Evaluator, manual_params

APPROVAL_OPERATIONS = ("approval.pass", "approval.reject", "approval.withdraw")


def approval_id_of(params: Mapping[str, Any]) -> str:
    value = params.get("approvalId")
    if value is None:
        raise PlatformError(ErrorCode.INVALID_REQUEST, "审批命令缺少 approvalId")
    return str(value)


def load(deps: ApprovalDeps, uow: UnitOfWork, approval_id: str, *, lock: bool = False) -> ApprovalRecord:
    record = deps.store.load(uow, approval_id, lock=lock)
    if record is None:
        raise PlatformError(ErrorCode.NOT_FOUND, f"审批 {approval_id} 不存在")
    return record


def editable_blocks(record: ApprovalRecord, mine: Sequence[Node]) -> set[tuple[str, str]]:
    """当前用户这次通过可以改勾选的块：块的 `selection` 为 `checked`，且他是该审批流本级节点的待处理审批人（C09 第 6 节）。"""
    flows = {n.flow for n in mine}
    return {(f.code, b.key) for f in record.flows if f.code in flows for b in f.config.display
            if b.region == "affected" and (b.selection or "checked") == "checked"}


def apply_checked(affected: Sequence[AffectedRow], editable: set[tuple[str, str]], checked: Sequence[CheckedRow]) -> list[AffectedRow]:
    """AP-07：可改勾选的块中，没有列出的行就是取消了；只能从上一级保留的行里再取消，不能勾回上一级取消的行。返回勾选变了的行。"""
    wanted = {(c.flow, c.block, c.key) for c in checked}
    changed = []
    for row in affected:
        if (row.flow, row.block) not in editable or row.missing or not row.checked:
            continue
        if (row.flow, row.block, row.key) not in wanted:
            row.checked = False
            changed.append(row)
    return changed


def manual_for(record: ApprovalRecord, flows: set[str], level: int | None) -> list[FlowParam]:
    """要由审批人填写的参数：`level` 为数字时取这一级的，为 None 时取最终批准时填写的（不带 `level`）。"""
    return [p for f in record.flows if f.code in flows for p in f.config.params if p.source == "manual" and p.level == level]


def require_params(params: Sequence[FlowParam], submitted: Mapping[str, Any]) -> dict[str, Any]:
    """AP-20：必填参数缺失返回 422 VALIDATION_FAILED。返回本次填写的这些参数。"""
    missing = [p for p in params if p.required and submitted.get(p.name) in (None, "")]
    if missing:
        raise PlatformError(ErrorCode.VALIDATION_FAILED, "请填写审批参数",
                            [ErrorDetail(message=f"请填写{p.label}", field=p.name) for p in missing])
    return {p.name: submitted.get(p.name) for p in params if p.name in submitted}


class NextLevels:
    """第 k 级（k ≥ 2）会进入的节点（AP-04）：节点的发起部门限制满足，并且入口条件对这个审批流的某个触发行成立。"""

    def __init__(self, deps: ApprovalDeps, uow: UnitOfWork, record: ApprovalRecord, scopes: Mapping[int, RowScope], *,
                 strict: bool = True) -> None:
        self.deps, self.uow, self.record, self.scopes, self.strict = deps, uow, record, scopes, strict

    def __call__(self, flow_code: str, level: int) -> list[Node]:
        flow = self.record.flow(flow_code)
        found = level_of(flow.config.levels, level)
        if found is None:
            return []
        triggers = [t.id for t in self.record.triggers_of(flow_code)]
        nodes = []
        for index, node in enumerate(found.nodes):
            if not node_entered(node, self.record.applicant_department):
                continue
            if node.condition_type == "always":
                hits = triggers
            else:
                hits = [i for i in triggers if exists(self.deps.sql, self.uow, node.condition or "", self.scopes[i])]
            if hits:
                nodes.append(resolve(node, flow=flow_code, level=level, index=index, uow=self.uow, sql=self.deps.sql,
                                     directory=self.deps.directory, scope=self.scopes[hits[0]], strict=self.strict))
        return nodes


def approval_ref(record: ApprovalRecord) -> ApprovalRef:
    return ApprovalRef(approval_id=record.approval_id, document=RecordRef(entity=record.source.entity,
                                                                          record_key=record.source.record_key),
                       status=record.progress.status, level=record.progress.level, flows=[f.code for f in record.flows])


class ResolveStage:
    """审批命令的"确定涉及的单据"：通过时为来源单据（由 write-pipeline 加锁读取并做冻结检查）；最终批准时要写的受影响单据
    由写入意图带出，write-pipeline 按 WP-18 加锁。驳回、撤回不写业务表，没有涉及的单据。"""

    name = "确定涉及的单据"

    def __init__(self, deps: ApprovalDeps) -> None:
        self.deps = deps

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return state.command.operation in APPROVAL_OPERATIONS

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        if state.command.operation != "approval.pass":
            return
        record = load(self.deps, uow, approval_id_of(state.command.params))
        if record.progress.status == "pending" and not isinstance(record.patch.master, MasterAdd):
            ref = DocumentRef(record.source.entity, record.source.record_key)
            if ref not in state.involved:
                state.involved.append(ref)


class ProcessStage:
    name = "审批处理"

    def __init__(self, deps: ApprovalDeps) -> None:
        self.deps = deps
        self.evaluator = Evaluator(deps)

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return state.command.operation in APPROVAL_OPERATIONS

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        params = state.command.params
        record = load(self.deps, uow, approval_id_of(params), lock=True)
        directory = Directory(self.deps.directory)
        kind = state.command.operation.split(".", 1)[1]
        comment = params.get("comment")
        comment = comment if isinstance(comment, str) and comment.strip() else None
        if kind == "pass":
            self._pass(uow, state, ctx, record, directory, comment)
        else:
            self._close(uow, state, ctx, record, directory, kind, comment)
        state.approvals.append(approval_ref(record))

    # ---------------------------------------------------------------- 通过

    def _pass(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, record: ApprovalRecord, directory: Directory,
              comment: str | None) -> None:
        params = state.command.params
        who = ctx.identity
        is_member = directory.membership()
        mine = pending_nodes(record.progress, who.user_id, is_member)
        if not mine:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, "当前用户不是本级尚未处理的审批人")
        affected = self.deps.store.affected(uow, record.approval_id)
        editable = editable_blocks(record, mine)
        checked = [parse_wire(CheckedRow, c) for c in params.get("checkedRows") or []]  # type: ignore[union-attr]
        unchecked = apply_checked(affected, editable, checked)
        submitted = params.get("params") or {}
        assert isinstance(submitted, dict)
        level = record.progress.level
        level_values = require_params(manual_for(record, {n.flow for n in mine}, level), submitted)

        current = state.current.get(DocumentRef(record.source.entity, record.source.record_key))
        computation = self.evaluator.compute(uow, ctx, record, affected, editable=editable, current=current)
        if computation.fingerprint != params.get("fingerprint"):
            raise PlatformError(ErrorCode.RECONFIRM_REQUIRED, "审批内容已经变化，请重新打开详情确认后再通过")

        action = Action("pass", who.user_id, who.display_name, ctx.now, comment)
        decision = decide(record.progress, action, applicant_id=record.applicant_id, is_member=is_member,
                          next_nodes=NextLevels(self.deps, uow, record, computation.scopes))
        if level_values:
            record.params[str(level)] = {**record.params.get(str(level), {}), **level_values}
        if decision.destination == "end":
            final = require_params(manual_for(record, set(decision.progress.flows), None), submitted)
            if final:
                record.params["final"] = final
        record.progress = decision.progress
        self.deps.store.set_checked(uow, record.approval_id, unchecked)
        self._record(uow, record, ProcessRecord(
            seq=0, level=level, user_id=who.user_id, user_name=who.display_name, action="pass", at=ctx.now, comment=comment,
            checked=[{"flow": a.flow, "block": a.block, "key": a.key or ""} for a in affected
                     if (a.flow, a.block) in editable and a.checked and not a.missing],
            params={**level_values, **record.params.get("final", {})} if decision.destination == "end" else level_values))
        if decision.destination == "next":
            state.notifications += notify.intents(record, "levelEntered", directory)
        elif decision.destination == "end":
            self._finish(uow, state, ctx, record, affected, current, directory)
        self.deps.store.update(uow, record)

    def _finish(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, record: ApprovalRecord,
                affected: Sequence[AffectedRow], current: Any, directory: Directory) -> None:
        """全部审批流到达终点（AP-10）：先应用待审修改，再按顺序对各块勾选的行执行操作；取值在这时重新计算，人工参数用
        各级和最终批准时填写的。"""
        computation = self.evaluator.compute(uow, ctx, record, affected, manual=manual_params(record), current=current)
        catalog = self.deps.catalog(ctx)
        intents: list[RowIntent] = list(patch_intents(record.patch, record.key_map, ctx.config))
        results: list[dict[str, Any]] = []
        for row in affected:
            if row.missing:
                results.append({"flow": row.flow, "block": row.block, "key": None, "status": "skipped", "reason": "记录已不存在"})
        intents += self._apply(uow, ctx, catalog, computation, results)
        state.intents += intents
        record.result = results
        record.pending_status = "applied"
        record.finished_at = ctx.now
        # 结束那一刻的修改内容：修改前为加锁读到的当前数据，修改后为要写的值重算后的结果，以后数据再变也按它显示（C06 7.6）
        record.final_view = computation.view
        self.deps.store.release(uow, record.approval_id)
        state.notifications += notify.intents(record, "passed", directory)

    def _apply(self, uow: UnitOfWork, ctx: ExecutionContext, catalog: ApprovalCatalog, computation: Computation,
               results: list[dict[str, Any]]) -> list[RowIntent]:
        intents: list[RowIntent] = []
        registered_keys: dict[str, list[str]] = {}
        for plan in computation.plans:
            for write in plan.writes:
                if write.action in ("update", "delete") and write.key is not None and catalog.entities_on_table(write.table):
                    registered_keys.setdefault(write.table, []).append(write.key)
        owner_of = {(table.upper(), key): owner for table, keys in registered_keys.items()
                    for key, owner in owners(self.deps.sql, uow, catalog, table, keys).items()}
        for plan in computation.plans:
            for write in plan.writes:
                base = {"flow": plan.flow.code, "block": plan.block.key, "key": write.key, "action": write.action}
                if write.action == "escape":
                    raise PlatformError(ErrorCode.VALIDATION_FAILED, "逃生舱操作只在用户点名时启用，当前没有启用",
                                        [ErrorDetail(message=f"审批流 {plan.flow.code} 的 {plan.block.key} 配置了逃生舱 {write.operation}")])
                entities = catalog.entities_on_table(write.table)
                if entities:
                    intent = self._intent(write, entities, owner_of)
                    if intent is None:
                        results.append({**base, "status": "skipped", "reason": "记录已不存在"})
                    else:
                        intents.append(intent)
                        results.append({**base, "status": "written"})
                    continue
                results.append(self._table_write(uow, ctx, write, base))
        return intents

    def _intent(self, write: Any, entities: Sequence[Any], owner_of: Mapping[tuple[str, str], Any]) -> RowIntent | None:
        if write.action == "insert":
            # insertRows 写到注册过的表：主表实体为一张新单据（临时编号，主键由 write-pipeline 取序列），明细挂到值中的主单
            entity = entities[0]
            values = self._fields(entity.config, write.values)
            if entity.is_root:
                temp = f"tmp-{uuid.uuid4()}"
                return RowIntent(DocumentRef(entity.code, temp), entity.code, "add", None, temp, values)
            parent = values.get(entity.parent_key or "")
            return RowIntent(DocumentRef(entity.root, key_text(parent)), entity.code, "add", None, f"tmp-{uuid.uuid4()}", values)
        owner = owner_of.get((write.table.upper(), write.key or ""))
        if owner is None:
            return None
        values = self._fields(owner.entity.config, write.values) if write.action == "update" else {}
        return RowIntent(owner.document, owner.entity.code, "modify" if write.action == "update" else "delete", write.key, None, values)

    @staticmethod
    def _fields(entity: Any, values: Mapping[str, Any]) -> dict[str, Any]:
        types = {f.name: f.type for f in entity.fields}
        found = {}
        for column, value in values.items():
            name = column_field(entity, column)
            if name is not None:
                found[name] = coerce(types[name], value)
        return found

    def _table_write(self, uow: UnitOfWork, ctx: ExecutionContext, write: Any, base: dict[str, Any]) -> dict[str, Any]:
        """没注册的表：加行锁、做冻结检查后按主键写入，不重算（WP-19）。"""
        tables = self.deps.tables
        if tables is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, "没有接入 TableWriter，不能写没在平台注册的表")
        columns = self.deps.schema.columns(write.table) or {}
        numeric = {name.upper() for name, info in columns.items() if info.data_type.upper() in ("NUMBER", "FLOAT", "INTEGER")}
        values = {c: coerce("number", v) if c.upper() in numeric else v for c, v in write.values.items()}
        if write.action == "insert":
            key = tables.insert(uow, write.table, values)
            return {**base, "key": key, "status": "written"}
        if tables.lock_row(uow, write.table, write.key_column, write.key) is None:
            return {**base, "status": "skipped", "reason": "记录已不存在"}
        check_rows(self.deps.store, uow, ctx, write.table, [write.key])
        if write.action == "update":
            tables.update(uow, write.table, write.key_column, write.key, values)
        else:
            tables.delete(uow, write.table, write.key_column, write.key)
        return {**base, "status": "written"}

    # ---------------------------------------------------------------- 驳回、撤回

    def _close(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, record: ApprovalRecord, directory: Directory,
               kind: str, comment: str | None) -> None:
        who = ctx.identity
        is_member = directory.membership()
        if kind == "reject":
            if not pending_nodes(record.progress, who.user_id, is_member):
                raise PlatformError(ErrorCode.PERMISSION_DENIED, "当前用户不是本级尚未处理的审批人")
            if comment is None:
                raise PlatformError(ErrorCode.VALIDATION_FAILED, "驳回必须填写原因", [ErrorDetail(message="请填写驳回原因", field="comment")])
        action = Action("reject" if kind == "reject" else "withdraw", who.user_id, who.display_name, ctx.now, comment)
        decision = decide(record.progress, action, applicant_id=record.applicant_id, is_member=is_member,
                          next_nodes=lambda flow, level: [])
        if not decision.allowed:
            raise PlatformError(ErrorCode.PERMISSION_DENIED, decision.reason or "不能处理这个审批")
        level = record.progress.level
        # 结束那一刻的修改内容：按此时的数据和勾选算一次存下，以后数据再变也按它显示（C06 7.6）
        record.final_view = self.evaluator.compute(uow, ctx, record, self.deps.store.affected(uow, record.approval_id)).view
        record.progress = decision.progress
        record.pending_status = "void"
        record.finished_at = ctx.now
        self._record(uow, record, ProcessRecord(seq=0, level=level, user_id=who.user_id, user_name=who.display_name,
                                                action=action.kind, at=ctx.now, comment=comment))
        self.deps.store.release(uow, record.approval_id)
        self.deps.store.update(uow, record)
        state.notifications += notify.intents(record, "rejected" if kind == "reject" else "withdrawn", directory)

    def _record(self, uow: UnitOfWork, record: ApprovalRecord, item: ProcessRecord) -> None:
        item.seq = len(self.deps.store.records(uow, record.approval_id)) + 1
        self.deps.store.add_record(uow, record.approval_id, item)


__all__ = ["APPROVAL_OPERATIONS", "NextLevels", "ProcessStage", "ResolveStage", "apply_checked", "editable_blocks", "manual_for"]
