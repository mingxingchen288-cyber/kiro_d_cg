""""触发审批"阶段（AP-01、AP-02、AP-06、AP-13、AP-14、AP-17、AP-21 中提交时的部分、AP-22）。

保存时（执行上下文的来源不是审批），对所属页面为本页面的每个启用审批流，按单据分别判断：只取这张单据中、`operations`
选中的表格里做了选中操作的行，逐行代入第 1 级每个启用节点的入口条件；有一行成立就进入这个节点，在任一第 1 级节点
成立的行是这个审批流的"触发本审批的行"。一张单据命中的审批流中，第 1 级有节点进入的都进入这张单据的审批（几个合成
一个，AP-09）；一个都没有时按普通保存写入。

进入审批的单据：新增行从序列取得正式主键；保存提交时命中的审批流定义、待审修改和触发行；按 `freeze` 对每个触发行找出
还要冻结的数据（普通查询），按 write-pipeline 的统一顺序把它们锁住（用户 2026-10-30 规则 2、3：排在本单据之后的这时再锁；
排在之前或同层的，`TriggerScopeStage` 已让本单据推迟加锁，这时和本单据一起锁），锁住后连同来源单据检查它们是否已在
别的审批中（AP-06，单独一条语句），登记冻结记录；按 `affected` 块对每个触发行查出受影响单据的行（锁后读），按修改表的
主键合并、默认勾选，并检查同一记录会不会被写成两个值（AP-22）；生成给第 1 级审批人的通知意图。
这些单据记入 `pending_documents`，write-pipeline 不写它们；同一命令中其余单据照常写入。

对照旧系统 `ConfiguredApprovalRuntime.beforeSave`（逐个候选流程判断入口、合成一个审批、送审时给新增行取号、保存
待审快照）、`ApprovalObjectService.capture`（审批对象按键合并）、`ApprovalFreezeService.acquire`（冻结冲突即拒绝）。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    ApprovalRef,
    CommandState,
    DocumentPatch,
    DocumentRef,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    FlowLevel,
    FlowNode,
    LOCK_LAYERS,
    FreezeEntry,
    LockTarget,
    MasterAdd,
    PlatformError,
    RecordRef,
    UpdateFields,
)

from . import notify
from .approvers import Directory, resolve
from .catalog import ApprovalCatalog, NamedFlow
from .deps import ApprovalDeps
from .freeze import check_documents, frozen_detail
from .model import AffectedRow, ApprovalRecord, FlowSnapshot, TriggerRow
from .patch import assign_keys, bill_key, key_value, patch_ref, resolved_patch
from .routing import Node, start
from .rows import ChangedRow, changed_rows, first_text, owners
from .sql import RowScope, binds_for, display_sql, exists, freeze_sql, key_text, scalar
from .view import Evaluator, cell


def level_of(levels: Sequence[FlowLevel], level: int) -> FlowLevel | None:
    return next((item for item in levels if item.level == level), None)


@dataclass
class _FlowHit:
    flow: NamedFlow
    nodes: list[tuple[int, FlowNode]]
    triggered: list[int]


@dataclass
class _Hit:
    ref: DocumentRef
    patch: DocumentPatch
    rows: list[ChangedRow]
    scopes: list[RowScope]
    flows: list[_FlowHit]


@dataclass
class _Prepared:
    """进入审批的一张单据在加锁前算出的部分：取得的主键、触发行的参数、触发行和冻结范围（普通查询）。"""

    hit: _Hit
    key_map: dict[str, str]
    bill: str
    scopes: list[RowScope]
    triggers: list[TriggerRow]
    freezes: list[tuple[str, str]]
    locks: list[LockTarget]


@dataclass
class _Submission:
    ref: DocumentRef
    record: ApprovalRecord
    affected: list[AffectedRow]
    freezes: list[tuple[str, str]]


def node_entered(node: FlowNode, ctx_department: str | None) -> bool:
    """节点启用，且发起部门限制满足（为空表示不限）。"""
    return node.enabled and (node.department is None or node.department == ctx_department)


def is_page_save(state: CommandState, ctx: ExecutionContext) -> bool:
    """页面保存、执行上下文不带传播来源时（C04：来源为审批的写入不再触发审批）。"""
    return ctx.origin.kind == "user" and state.command.page is not None and bool(state.command.documents)


class TriggerScopeStage:
    """"确定涉及的单据"中触发审批的部分（用户 2026-10-30 规则 3）：本页面启用的审批流要冻结排在本单据之前或同层的数据时
    （冻结表注册过的按所属主表实体的层级，没注册的为基础数据层；例如物料清单改价要冻结含这个物料的成本单），设
    `CommandState.defer_lock`：加锁读取只普通读取本单据，合并、计算、入口条件和冻结的 SQL 都在加锁前执行一次，"触发审批"
    再把本单据和要冻结的数据按统一顺序一次锁完并核对本单据（AP-02）。只看配置，不执行 SQL；要冻结的都排在本单据之后时
    （成本核算改价冻结物料清单）照常先锁本单据，冻结前再锁要冻结的（规则 2）。"""

    name = "确定涉及的单据"

    def __init__(self, deps: ApprovalDeps) -> None:
        self.deps = deps

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return is_page_save(state, ctx)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        page = state.command.page or ""
        catalog = self.deps.catalog(ctx)
        flows = catalog.flows(page)
        if not flows:
            return
        locks = self.deps.locker()
        own = LOCK_LAYERS.index(locks.layer(ctx, ctx.config.page_view(page).master.entity))
        for flow in flows:
            for item in flow.config.freeze:
                if not item.enabled:
                    continue
                entities = catalog.entities_on_table(item.table)
                layer = locks.layer(ctx, entities[0].root) if entities else "base"
                if LOCK_LAYERS.index(layer) <= own:
                    state.defer_lock = True
                    return


class TriggerStage:
    name = "触发审批"

    def __init__(self, deps: ApprovalDeps) -> None:
        self.deps = deps
        self.evaluator = Evaluator(deps)

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return is_page_save(state, ctx)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        """入口条件和冻结范围在加锁前用普通查询算出；冻结前按统一顺序一次锁完（规则 2、3），之后才读受影响单据、
        检查冲突、单独一条语句查冻结（规则 6）、登记冻结。"""
        catalog = self.deps.catalog(ctx)
        flows = catalog.flows(state.command.page or "")
        if not flows:
            return
        hits = []
        for patch in state.command.documents:
            ref = patch_ref(patch)
            rows = changed_rows(state, ref)
            if rows:
                hit = self._entered(uow, state, ctx, flows, ref, patch, rows)
                if hit is not None:
                    hits.append(hit)
        prepared = [self._prepare(uow, state, ctx, catalog, hit) for hit in hits]
        self._lock(uow, state, ctx, [target for p in prepared for target in p.locks])
        if not prepared:
            return
        directory = Directory(self.deps.directory)
        submissions = [self._submission(uow, state, ctx, directory, p) for p in prepared]
        self._exclusive(uow, submissions)
        for submission in submissions:
            record = submission.record
            record.approval_id = self.deps.store.next_id(uow)
            self.deps.store.insert(uow, record, submission.affected)
            self.deps.store.freeze(uow, [FreezeEntry(record.approval_id, table, key) for table, key in submission.freezes])
            state.approvals.append(ApprovalRef(approval_id=record.approval_id,
                                               document=RecordRef(entity=record.source.entity, record_key=record.source.record_key),
                                               status="pending", level=1, flows=[f.code for f in record.flows]))
            state.pending_documents.add(submission.ref)
            state.notifications += notify.intents(record, "submitted", directory)
        state.outcome = "approvalSubmitted"

    # ---------------------------------------------------------------- 第 1 级入口条件（AP-01）

    def _entered(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, flows: Sequence[NamedFlow], ref: DocumentRef,
                 patch: DocumentPatch, rows: list[ChangedRow]) -> _Hit | None:
        master_entity = ctx.config.entity(ref.entity)
        candidate, current = state.candidate.get(ref), state.current.get(ref)
        master_new = dict(candidate.master.values) if candidate is not None else {}
        master_old = dict(current.master.values) if current is not None else {}
        pk = master_entity.primary_key
        bill = master_old.get(pk) or master_new.get(pk) or ref.record_key
        who = ctx.identity
        scopes = [RowScope(r.op, r.new, r.old, master_new, master_old, bill, who.user_id, who.department_id) for r in rows]
        found = []
        for flow in flows:
            ops = flow.config.operations
            candidates = [i for i, r in enumerate(rows) if r.op in ops.get(r.entity, [])]
            first = level_of(flow.config.levels, 1)
            if not candidates or first is None:
                continue
            nodes: list[tuple[int, FlowNode]] = []
            triggered: set[int] = set()
            for index, node in enumerate(first.nodes):
                if not node_entered(node, who.department_id):
                    continue
                if node.condition_type == "always":
                    hit = candidates
                else:
                    hit = [i for i in candidates if exists(self.deps.sql, uow, node.condition or "", scopes[i])]
                if hit:
                    nodes.append((index, node))
                    triggered.update(hit)
            if nodes:
                found.append(_FlowHit(flow, nodes, sorted(triggered)))
        return _Hit(ref, patch, rows, scopes, found) if found else None

    # ---------------------------------------------------------------- 加锁（WP-03 的统一顺序）

    def _lock(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, targets: list[LockTarget]) -> None:
        """冻结前加锁。`defer_lock` 时本命令的单据还没锁（`TriggerScopeStage`）：和要冻结的数据合在一起按统一顺序一次锁完，
        锁住后核对本单据与加锁前读到的相同（不同时整个事务回滚重来，规则 4），再查本单据的冻结（AP-03，锁后单独一条）。
        否则本单据已在加锁读取锁住，要冻结的都排在它之后，这时再锁（规则 2）。"""
        own = [ref for ref in state.involved if ref in state.current] if state.defer_lock else []
        if not own and not targets:
            return
        locks = self.deps.locker()
        expected = {ref: state.current[ref] for ref in own}
        locks.lock(uow, ctx, [*(locks.document(ctx, ref) for ref in own), *targets], expected or None)
        if own:
            check_documents(self.deps.store, uow, ctx, own)

    # ---------------------------------------------------------------- 进入审批（AP-02）

    def _prepare(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, catalog: ApprovalCatalog,
                 hit: _Hit) -> _Prepared:
        """加锁前的部分：取主键、触发行和冻结范围（普通查询）。"""
        config = ctx.config
        master_entity = config.entity(hit.ref.entity)
        key_map = assign_keys(uow, self.deps.keys, config, hit.patch)
        bill = bill_key(hit.patch, key_map)
        scopes = list(hit.scopes)
        if isinstance(hit.patch.master, MasterAdd):
            bill_value = key_value(master_entity, bill)
            scopes = [dataclasses.replace(s, bill_id=bill_value, master_new={**s.master_new, master_entity.primary_key: bill_value})
                      for s in scopes]
        parent_keys = {link.entity: link.parent_key for link in master_entity.details}
        for i, row in enumerate(hit.rows):
            if row.op == "add" and row.client_row_id in key_map:
                entity = config.entity(row.entity)
                new = {**scopes[i].new, entity.primary_key: key_value(entity, key_map[row.client_row_id])}
                if row.entity in parent_keys:
                    new[parent_keys[row.entity]] = scopes[i].bill_id
                scopes[i] = dataclasses.replace(scopes[i], new=new)

        triggers = [TriggerRow(id=i, entity=r.entity, op=r.op, row_key=r.row_key or key_map.get(r.client_row_id or ""),
                               client_row_id=r.client_row_id,
                               flows=[f.flow.code for f in hit.flows if i in f.triggered]) for i, r in enumerate(hit.rows)]
        freezes, locks = self._freezes(uow, ctx, catalog, master_entity.table, bill, hit, scopes)
        return _Prepared(hit, key_map, bill, scopes, triggers, freezes, locks)

    def _submission(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext, directory: Directory,
                    prepared: _Prepared) -> _Submission:
        """锁住之后的部分：受影响单据（读到的是锁后的值）、写入冲突、第 1 级审批人和审批记录。"""
        config = ctx.config
        hit, scopes, bill = prepared.hit, prepared.scopes, prepared.bill
        master_entity = config.entity(hit.ref.entity)
        affected = self._affected(uow, hit, scopes)
        self._conflicts(uow, hit, scopes, affected)

        entered: dict[str, list[Node]] = {}
        for flow_hit in hit.flows:
            scope = scopes[flow_hit.triggered[0]]
            entered[flow_hit.flow.code] = [resolve(node, flow=flow_hit.flow.code, level=1, index=index, uow=uow, sql=self.deps.sql,
                                                   directory=self.deps.directory, scope=scope) for index, node in flow_hit.nodes]
        candidate = state.candidate.get(hit.ref) or state.current.get(hit.ref)
        master_values = candidate.master.values if candidate is not None else {}
        label = first_text(master_values, [f.name for f in master_entity.fields if f.type == "text" and f.role != "system"])
        record = ApprovalRecord(
            approval_id="", page=state.command.page or "", page_title=config.page_view(state.command.page or "").title,
            operation=state.command.operation, operation_label=config.operation(state.command.operation).label,
            source=DocumentRef(hit.ref.entity, bill), source_label=label, applicant_id=ctx.identity.user_id,
            applicant_name=ctx.identity.display_name, applicant_department=ctx.identity.department_id, submitted_at=ctx.now,
            flows=[FlowSnapshot(f.flow.code, f.flow.name, f.flow.config) for f in hit.flows], triggers=prepared.triggers,
            patch=resolved_patch(hit.patch, state.changes.rows, config), key_map=prepared.key_map,
            progress=start([f.flow.code for f in hit.flows], entered),
        )
        return _Submission(hit.ref, record, affected, prepared.freezes)

    def _freezes(self, uow: UnitOfWork, ctx: ExecutionContext, catalog: ApprovalCatalog, root_table: str, bill: str, hit: _Hit,
                 scopes: Sequence[RowScope]) -> tuple[list[tuple[str, str]], list[LockTarget]]:
        """要冻结的数据（C06 7.4）和它们的锁对象：触发审批的单据总是整张冻结（它由加锁读取或 `_lock` 锁住）；冻结表注册过的，
        查到的行所属的整张单据冻结，锁这张单据；没注册的，只冻结、只锁查到的那一行。查找用普通查询（加锁之前）。"""
        locks = self.deps.locker()
        targets: list[LockTarget] = []
        found: dict[tuple[str, str], None] = {(root_table, bill): None}
        for flow_hit in hit.flows:
            for item in flow_hit.flow.config.freeze:
                if not item.enabled:
                    continue
                entities = catalog.entities_on_table(item.table)
                pk = self.deps.schema.primary_key(item.table)
                if pk is None and entities:
                    entity = entities[0].config
                    pk = next((f.column for f in entity.fields if f.name == entity.primary_key), None)
                if pk is None:
                    raise PlatformError(ErrorCode.INTERNAL_ERROR, f"冻结表 {item.table} 没有单列主键")
                statement = freeze_sql(item.table, [pk], item.condition)
                keys: list[str] = []
                for i in flow_hit.triggered:
                    keys += [key_text(r[pk.upper()]) for r in self.deps.sql.rows(uow, statement, binds_for(statement, scopes[i]))
                             if r.get(pk.upper()) is not None]
                keys = list(dict.fromkeys(keys))
                if entities:
                    for owner in owners(self.deps.sql, uow, catalog, item.table, keys).values():
                        entry = (owner.entity.root_config.table, owner.document.record_key)
                        if entry not in found:
                            found[entry] = None
                            targets.append(locks.document(ctx, owner.document))
                else:
                    for key in keys:
                        if (item.table, key) not in found:
                            found[(item.table, key)] = None
                            targets.append(locks.row(item.table, pk, key))
        return list(found), targets

    def _affected(self, uow: UnitOfWork, hit: _Hit, scopes: Sequence[RowScope]) -> list[AffectedRow]:
        """受影响单据的行（C06 7.5）：每个触发行执行一次关联条件，结果按修改表的主键合并，记下找到它的全部触发行，默认都
        勾选；`keyColumn` 为空的行记录已不存在，照常记为这一块的一行，不能勾选（AP-21）。查找只在提交时进行。"""
        found: list[AffectedRow] = []
        for flow_hit in hit.flows:
            for block in flow_hit.flow.config.display:
                if block.region != "affected":
                    continue
                key_column = self.evaluator.key_column(block).upper()
                target = block.target_table or block.source
                merged: dict[str, AffectedRow] = {}
                missing: dict[tuple[tuple[str, str], ...], AffectedRow] = {}
                statement = display_sql(block.source, block.condition or "1 = 1")
                for i in flow_hit.triggered:
                    for row in self.deps.sql.rows(uow, statement, binds_for(statement, scopes[i])):
                        value = row.get(key_column)
                        if value is None:
                            ident = tuple(sorted((k, repr(v)) for k, v in row.items()))
                            missing.setdefault(ident, AffectedRow(flow_hit.flow.code, block.key, 0, target, None, True, [i], False,
                                                                  dict(row)))
                            continue
                        key = key_text(value)
                        if key in merged:
                            if i not in merged[key].triggers:
                                merged[key].triggers.append(i)
                        else:
                            merged[key] = AffectedRow(flow_hit.flow.code, block.key, 0, target, key, False, [i], True, dict(row))
                for seq, row in enumerate([*merged.values(), *missing.values()], start=1):
                    row.seq = seq
                    found.append(row)
        return found

    def _conflicts(self, uow: UnitOfWork, hit: _Hit, scopes: Sequence[RowScope], affected: Sequence[AffectedRow]) -> None:
        """AP-22：同一修改表的同一行、同一列，用找到它的每个触发行各算一次取值，得到不同的值时拒绝整个命令。"""
        flows = {f.flow.code: f.flow for f in hit.flows}
        values: dict[tuple[str, str, str], list[tuple[object, str]]] = {}  # （修改表、主键、列）-> 各触发行算出的值
        names: dict[tuple[str, str, str], str] = {}
        for row in affected:
            if row.missing or row.key is None:
                continue
            flow = flows[row.flow]
            block = next(b for b in flow.config.display if b.key == row.block)
            updates = [a for a in block.actions if isinstance(a, UpdateFields)]
            if not updates:
                continue
            key_column = self.evaluator.key_column(block)
            target = block.target_table or block.source
            snapshot = FlowSnapshot(flow.code, flow.name, flow.config)
            target_key = self.deps.schema.primary_key(target) or key_column
            target_row = self.evaluator.target_rows(uow, block, target, target_key, [row.key]).get(row.key, {})
            label = first_text(row.data, [c.field.upper() for c in block.columns
                                          if not c.field.startswith("master.") and c.field.upper() != key_column.upper()]) or row.key
            for i in row.triggers:
                local = scopes[i].with_row(target_row, self.evaluator.params(uow, snapshot, scopes[i], {}))
                for action in updates:
                    for item in action.fields:
                        slot = (target.upper(), row.key, item.column.upper())
                        values.setdefault(slot, []).append((scalar(self.deps.sql, uow, item.value, local), block.title))
                        names[slot] = f"{block.title} {label}（{key_column} {row.key}）的 {item.column}"
        details = []
        for slot, written in values.items():
            distinct = list(dict.fromkeys(str(cell(v)) for v, _ in written))
            if len(distinct) > 1:
                details.append(ErrorDetail(message=f"{names[slot]} 会被写成 {' 和 '.join(distinct)}", row_key=slot[1], field=slot[2]))
        if details:
            raise PlatformError(ErrorCode.VALIDATION_FAILED, "同一条记录会被写成不同的值", details)

    # ---------------------------------------------------------------- 同一份数据只属于一个审批（AP-06）

    def _exclusive(self, uow: UnitOfWork, submissions: Sequence[_Submission]) -> None:
        owner: dict[tuple[str, str], int] = {}
        details: list[ErrorDetail] = []
        for index, submission in enumerate(submissions):
            for entry in submission.freezes:
                other = owner.setdefault(entry, index)
                if other != index:
                    table, key = entry
                    details.append(ErrorDetail(
                        message=f"{table} 中主键为 {key} 的数据在本次保存中要被两个审批冻结"
                                f"（来源单据 {submissions[other].record.source.record_key} 和 {submission.record.source.record_key}）",
                        row_key=key))
        by_table: dict[str, list[str]] = {}
        for table, key in owner:
            by_table.setdefault(table, []).append(key)
        for table, keys in by_table.items():
            for key, entry in self.deps.store.frozen(uow, table, keys).items():
                details.append(frozen_detail(None, key, entry))
        if details:
            raise PlatformError(ErrorCode.FROZEN_BY_APPROVAL, "要冻结的数据已在另一个未结束的审批中，不能发起审批", details)
