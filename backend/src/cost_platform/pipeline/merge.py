"""把修改合并到加锁读到的当前数据，生成只含有变化的列的变更计划（WP-04–WP-06、WP-14–WP-16、WP-18）。

- `DocumentMerger`：页面保存的 Patch（主表和明细的新增、修改、删除），由管道阶段"合并修改"调用（`stages.py`）。
- `IntentMerger`：动作展开出的 `intents`，由管道阶段"合并意图"调用；所属单据不在 `involved` 中的先加锁读取、做冻结检查，
  再合并（WP-18）。经管道阶段执行时，加锁读取和冻结检查已由编排在这一轮做过（"加锁读取"阶段），这里不再重复。
- `PatchMerger`：原端口 `ChangeMerger`（C08 第 5a 节，2026-10-29 起不是端口）的按实体合并修改，保留原有行为。

候选数据（`CommandState.candidate`）由当前值复制而来，合并后的新值写在其中；当前值（`current`）保持命令开始时读到的值，
作为修改的旧值和判断 ERP 行的依据。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping
from typing import Protocol

from cost_platform.contracts.ports import PermissionChecker, PipelineStage, UnitOfWork
from cost_platform.contracts.types import (
    BusinessValue,
    CommandState,
    DetailAdd,
    DetailDelete,
    DocumentData,
    DocumentPatch,
    DocumentRef,
    EntityConfig,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    MasterAdd,
    MasterDelete,
    MasterModify,
    PlatformError,
    Row,
    RowChange,
    RowIntent,
    SkippedRow,
    Value,
)
from cost_platform.contracts.values import from_wire, same_value

from .copies import SourceRows, source_of
from .entity_rules import EntityRules
from .loader import (
    DocumentLoader,
    candidate_of,
    document_ref,
    is_new_document,
    is_new_key,
    known_missing,
    rejects_missing,
)
from .plan import find_change, note_modify, row_id
from .values import NoScales, stored_value


class Scales(Protocol):
    """列的小数位来源（`values.ColumnScales` 或 `values.NoScales`）。"""

    def scale(self, table: str, column: str | None) -> int | None: ...


RowRef = tuple[str, str]
"""（实体，主键或 clientRowId）。"""


def _detail(row_key: str | None, client_row_id: str | None, entity: str, field: str, message: str) -> ErrorDetail:
    return ErrorDetail(message=message, entity=entity, row_key=row_key, client_row_id=client_row_id, field=field)


class _Rows:
    """一个实体的行级合并：取值、检查、小数位。"""

    def __init__(self, rules: EntityRules, scales: Scales) -> None:
        self.rules = rules
        self._scales = scales
        self._fields = rules.fields

    def value(self, name: str, raw: BusinessValue | Value, row_key: str | None, client_row_id: str | None, *,
              wire: bool = True) -> Value:
        """转为后端的值并按 WP-15 处理。`wire` 为 True 时是 Patch 中 JSON 的值（C01，前端按页面视图的字段类型给出）；
        为 False 时是动作给出的后端的值，其中的文本按字段类型转换。格式不合法的值（前端不会发出）上线后再补 422 的映射。"""
        field = self._fields[name]
        value: Value = raw  # type: ignore[assignment]
        if wire or isinstance(raw, str) and field.type != "text":
            value = from_wire(field.type, raw)  # type: ignore[arg-type]
        return self.stored(name, value)

    def stored(self, name: str, value: Value) -> Value:
        field = self._fields[name]
        return stored_value(field.type, value, self._scales.scale(self.rules.config.table, field.column))

    def check(self, names: list[str], current: dict[str, Value] | None, writable: frozenset[str] | None,
              row_key: str | None, client_row_id: str | None) -> None:
        """WP-04、WP-14：字段不可写时 422 FIELD_NOT_WRITABLE，列出每个字段。`writable` 为 None 时只按实体规则判断。"""
        problems = []
        for name in names:
            reason = self.rules.not_writable_reason(name, current)
            if reason is None and writable is not None and name not in writable:
                reason = f"没有修改 {self._fields[name].label} 的权限"
            if reason is not None:
                problems.append(_detail(row_key, client_row_id, self.rules.code, name, reason))
        if problems:
            raise PlatformError(ErrorCode.FIELD_NOT_WRITABLE, "有字段不能修改", problems)

    def new_values(self, provided: Mapping[str, BusinessValue | Value], writable: frozenset[str] | None,
                   ctx: ExecutionContext | None, client_row_id: str | None, row_key: str | None = None, *,
                   wire: bool = True, source: Mapping[str, Value] | None = None,
                   readable: Collection[str] = ()) -> dict[str, Value]:
        """新增行要写入的值：填写的值、默认值（WP-16）、erpRow 列设为 localValue（WP-14）。不含主键和关联字段。
        不可编辑字段的 builtin 默认值按执行上下文取，前端传来的值不用（E28）。复制出的行（`source` 为源行）见
        `_copied_values`。"""
        if source is not None:
            return self._copied_values(provided, writable, source, readable, client_row_id, row_key, wire=wire)
        builtin_locked = {n for n in self.rules.builtin_names() if writable is not None and n not in writable}
        given = {n: v for n, v in provided.items() if n not in builtin_locked}
        self.check(sorted(given), None, writable, row_key, client_row_id)
        values = {n: self.value(n, v, row_key, client_row_id, wire=wire) for n, v in given.items()}
        for name, value in self.rules.defaults(set(given), writable if writable is not None else self._fields, ctx).items():
            values[name] = self.stored(name, value)
        local = self.rules.local_erp_value()
        if local is not None:
            values[local[0]] = local[1]
        return values

    def _copied_values(self, provided: Mapping[str, BusinessValue | Value], writable: frozenset[str] | None,
                       source: Mapping[str, Value], readable: Collection[str], client_row_id: str | None,
                       row_key: str | None, *, wire: bool) -> dict[str, Value]:
        """复制出的行（C02 `copyOf`，WP-21）：可写的字段取命令中的值（复制后用户可能改过）；不可写、但在页面上可见、
        能写进表的字段（例如成本单的币种、项目号）取源行的值，不用命令中的值；只在视图中的字段和计算字段不写（旧系统插入
        跳过虚拟列，计算字段由计算规则算出）；其余不可写的字段照常 422。不补默认值（WP-16）；erpRow 列设为 localValue。"""
        allowed = writable if writable is not None else frozenset(self._fields)
        taken: set[str] = set()
        dropped: set[str] = set()
        for name in provided:
            field = self._fields.get(name)
            if field is None or name in allowed:
                continue
            if field.column is None or field.role == "calculated":
                dropped.add(name)
            elif name in readable and self.rules.not_writable_reason(name, None) is None:
                taken.add(name)
        given = [n for n in provided if n not in taken and n not in dropped]
        self.check(sorted(given), None, writable, row_key, client_row_id)
        values = {n: self.value(n, provided[n], row_key, client_row_id, wire=wire) for n in given}
        values.update({n: self.stored(n, source.get(n)) for n in taken})
        local = self.rules.local_erp_value()
        if local is not None:
            values[local[0]] = local[1]
        return values


class DocumentMerger:
    """页面保存：把命令中各单据的 Patch 合并进候选数据，写入变更计划（动作执行阶段中 write-pipeline 的部分）。"""

    def __init__(self, permission: PermissionChecker, scales: Scales | None = None) -> None:
        self._permission = permission
        self._scales = scales or NoScales()

    def _writable(self, ctx: ExecutionContext, page: str | None, rules: EntityRules,
                  current: dict[str, Value] | None) -> frozenset[str]:
        """用户发起时为 authz 的可写字段；来源为审批时不看个人权限（C08 第 7 节）。"""
        if ctx.origin.kind == "user" and page is not None:
            return self._permission.writable_fields(ctx, page, rules.code)
        return rules.structural_writable(current)

    def merge_patches(self, state: CommandState, ctx: ExecutionContext, sources: SourceRows | None = None) -> set[RowRef]:
        """合并 `command.documents`，返回本次新增和修改的行（必填检查用，WP-07）。`sources` 为复制出的行的源行
        （`copies.CopySources` 读出，WP-21）。

        加锁读取时已不存在的单据已按 `rowNotFound` 处理，这里跳过；单据中要修改或删除的明细行已不存在时，
        同样按 `rowNotFound` 跳过并写入 `skipped`，或返回 409 ROW_NOT_FOUND（WP-05）。"""
        page = state.command.page
        reject = rejects_missing(state, ctx)
        patched: set[RowRef] = set()
        for patch in state.command.documents:
            self._merge(state, ctx, page, reject, patch, patched, sources or {})
        return patched

    @staticmethod
    def _readable(ctx: ExecutionContext, page: str | None, entity: str) -> frozenset[str]:
        """用户在这个页面上能看到的字段（页面视图中 visible 的字段）：复制出的行只取这些字段的源行值（WP-21）。"""
        if page is None:
            return frozenset()
        view = ctx.config.page_view(page)
        area = next((a for a in [view.master, *view.details] if a.entity == entity), None)
        return frozenset(f.name for f in area.fields if f.visible) if area is not None else frozenset()

    def _merge(self, state: CommandState, ctx: ExecutionContext, page: str | None, reject: bool, patch: DocumentPatch,
               patched: set[RowRef], sources: SourceRows) -> None:
        entity = ctx.config.entity(patch.entity)
        master_rules = EntityRules(patch.entity, entity)
        master_rows = _Rows(master_rules, self._scales)
        ref = document_ref(patch.entity, patch.master)
        master = patch.master
        if isinstance(master, MasterAdd):
            values = master_rows.new_values(master.values, self._writable(ctx, page, master_rules, None), ctx,
                                            master.client_row_id, source=source_of(sources, patch.entity, master.copy_of),
                                            readable=self._readable(ctx, page, patch.entity))
            row = Row(entity=patch.entity, row_key=None, client_row_id=master.client_row_id,
                      values={**{f.name: None for f in entity.fields}, **values})
            doc = DocumentData(ref=ref, master=row, details={link.entity: [] for link in entity.details})
            state.candidate[ref] = doc
            state.changes.rows.append(RowChange(document=ref, entity=patch.entity, op="add", row_key=None,
                                                client_row_id=master.client_row_id, values=values, old={}))
            patched.add(row_id(row))
        else:
            if ref not in state.current:
                return
            doc = candidate_of(state, ref)  # type: ignore[assignment]
            assert doc is not None
            current = state.current[ref].master.values
            if isinstance(master, MasterModify):
                if self._modify(state, ref, master_rows, doc.master, current, master.changes,
                                self._writable(ctx, page, master_rules, current)):
                    patched.add(row_id(doc.master))
            elif isinstance(master, MasterDelete):
                delete_document(state, ref)
                return
        links = {link.entity: link.parent_key for link in entity.details}
        for detail in patch.details:
            rules = EntityRules(detail.entity, ctx.config.entity(detail.entity), links[detail.entity])
            rows = _Rows(rules, self._scales)
            if isinstance(detail, DetailAdd):
                values = rows.new_values(detail.values, self._writable(ctx, page, rules, None), ctx, detail.client_row_id,
                                         source=source_of(sources, detail.entity, detail.copy_of),
                                         readable=self._readable(ctx, page, detail.entity))
                add_detail(state, doc, rules, values, client_row_id=detail.client_row_id, row_key=None)
                patched.add((detail.entity, detail.client_row_id))
                continue
            found = _find_row(state.current[ref].details.get(detail.entity, []), detail.row_key)
            if found is None:
                _row_not_found(state, reject, detail.entity, detail.row_key)
                continue
            target = _find_row(doc.details[detail.entity], detail.row_key)
            assert target is not None
            if isinstance(detail, DetailDelete):
                _note_delete(state, ref, found)
            elif self._modify(state, ref, rows, target, found.values, detail.changes,
                              self._writable(ctx, page, rules, found.values)):
                patched.add(row_id(target))

    @staticmethod
    def _modify(state: CommandState, ref: DocumentRef, rows: _Rows, target: Row, current: dict[str, Value],
                changes: Mapping[str, BusinessValue], writable: frozenset[str]) -> bool:
        """一行的修改：只改出现的字段，与当前值相同不算变化（WP-04）。返回这一行是否有变化。"""
        rows.check(list(changes), current, writable, target.row_key, None)
        changed = False
        for name, raw in changes.items():
            new = rows.value(name, raw, target.row_key, None)
            changed |= note_modify(state, ref, target, name, rows.rules.fields[name].type, new, current.get(name))
        return changed


class IntentMerger:
    """动作执行中 write-pipeline 的部分（WP-18）：取出 `intents` 合并进候选数据并清空。

    所属单据不在 `involved` 中的（例如按钮的 `updateRecords` 找到的单据），先加入 `involved`，按（实体、主键）排序加锁读入
    `current`，再只对这些单据执行一次冻结检查阶段，都通过后才合并。intents 由配置展开（operations、approval），
    只按实体规则检查：不能写计算字段、ERP 行的 ERP 列、主键、关联字段和 erpRow 列（C06 7.5）。"""

    def __init__(self, loader: DocumentLoader, scales: Scales | None = None) -> None:
        self._loader = loader
        self._scales = scales or NoScales()

    def absorb(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext,
               freeze: PipelineStage | None = None) -> None:
        intents = list(state.intents)
        if not intents:
            return
        outside = sorted({i.document for i in intents if i.document not in state.involved and not is_new_document(state, i.document)
                          and not known_missing(state, i.document)},
                         key=lambda r: (r.entity, r.record_key))
        if outside:
            state.involved.extend(outside)
            loaded = self._loader.lock(uow, state, ctx, outside)
            if freeze is not None and loaded:
                scoped = dataclasses.replace(state, involved=list(loaded))
                if freeze.applies(scoped, ctx):
                    freeze.run(uow, scoped, ctx)
        reject = rejects_missing(state, ctx)
        for intent in intents:
            self._apply(state, ctx, intent, reject)
        state.intents.clear()

    def _apply(self, state: CommandState, ctx: ExecutionContext, intent: RowIntent, reject: bool) -> None:
        ref = intent.document
        master_entity = ctx.config.entity(ref.entity)
        if intent.entity == ref.entity:
            rules = EntityRules(ref.entity, master_entity)
        else:
            links = {link.entity: link.parent_key for link in master_entity.details}
            rules = EntityRules(intent.entity, ctx.config.entity(intent.entity), links[intent.entity])
        rows = _Rows(rules, self._scales)
        if intent.op == "add":
            self._add(state, ctx, intent, rules, rows, master_entity)
            return
        if ref not in state.current:
            return  # 单据已不存在，加锁读取时已按 rowNotFound 处理
        doc = candidate_of(state, ref)
        assert doc is not None
        current_doc = state.current[ref]
        if intent.entity == ref.entity:
            current, target = current_doc.master, doc.master
        else:
            current = _find_row(current_doc.details.get(intent.entity, []), intent.row_key)  # type: ignore[assignment]
            target = _find_row(doc.details.get(intent.entity, []), intent.row_key)  # type: ignore[assignment]
        if current is None or target is None:
            _row_not_found(state, reject, intent.entity, intent.row_key or "")
            return
        if intent.op == "delete":
            if intent.entity == ref.entity:
                delete_document(state, ref)
            else:
                _note_delete(state, ref, current)
            return
        rows.check(list(intent.values), current.values, None, target.row_key, None)
        for name, raw in intent.values.items():
            new = rows.value(name, raw, target.row_key, None, wire=False)
            note_modify(state, ref, target, name, rules.fields[name].type, new, current.values.get(name))

    @staticmethod
    def _add(state: CommandState, ctx: ExecutionContext, intent: RowIntent, rules: EntityRules, rows: _Rows,
             master_entity: EntityConfig) -> None:
        """新增行：审批通过时写入的新增行带着提交审批时取得的主键（`row_key`，AP-02）。明细的关联字段取所属单据的主键
        （`add_detail`）：approval 展开的待审新增明细在值中也带着它（AP-10、E24），这里不用意图中的这个值。"""
        given = {name: value for name, value in intent.values.items() if name != rules.parent_key}
        values = rows.new_values(given, None, ctx, intent.client_row_id, intent.row_key, wire=False)
        ref = intent.document
        if intent.entity == ref.entity:
            row = Row(entity=ref.entity, row_key=intent.row_key, client_row_id=intent.client_row_id,
                      values={**{f.name: None for f in master_entity.fields}, **values})
            state.candidate[ref] = DocumentData(ref=ref, master=row, details={link.entity: [] for link in master_entity.details})
            if ref not in state.involved:
                state.involved.append(ref)
            state.changes.rows.append(RowChange(document=ref, entity=ref.entity, op="add", row_key=intent.row_key,
                                                client_row_id=intent.client_row_id, values=values, old={}))
            return
        doc = candidate_of(state, ref)
        if doc is None:
            return
        add_detail(state, doc, rules, values, client_row_id=intent.client_row_id, row_key=intent.row_key)


def add_detail(state: CommandState, doc: DocumentData, rules: EntityRules, values: dict[str, Value], *,
               client_row_id: str | None, row_key: str | None) -> None:
    """在单据中新增一行明细；关联字段取主单主键，新单据在主表取得主键后由写入填上（`ChangeWriter`）。"""
    assert rules.parent_key is not None
    parent = rules.fields[rules.parent_key]
    master_key = doc.master.row_key
    values = {rules.parent_key: None if is_new_key(master_key) else from_wire(parent.type, master_key), **values}
    row = Row(entity=rules.code, row_key=row_key, client_row_id=client_row_id,
              values={**{f.name: None for f in rules.config.fields}, **values})
    if row_key is not None:
        row.values[rules.primary_key.name] = from_wire(rules.primary_key.type, row_key)
    doc.details.setdefault(rules.code, []).append(row)
    state.changes.rows.append(RowChange(document=doc.ref, entity=rules.code, op="add", row_key=row_key,
                                        client_row_id=client_row_id, values=values, old={}))


def delete_document(state: CommandState, ref: DocumentRef) -> None:
    """删除主表行，连同它的全部明细（WP-06）：主表和每一行明细都记入计划，旧值为删除前的整行（审计用）。"""
    current = state.current[ref]
    _note_delete(state, ref, current.master)
    for rows in current.details.values():
        for row in rows:
            _note_delete(state, ref, row)


def _note_delete(state: CommandState, ref: DocumentRef, current: Row) -> None:
    change = find_change(state.changes, current.entity, current.row_key or "")
    if change is not None:
        state.changes.rows.remove(change)
    state.changes.rows.append(RowChange(document=ref, entity=current.entity, op="delete", row_key=current.row_key,
                                        client_row_id=None, values={}, old=dict(current.values)))


def _find_row(rows: list[Row], key: str | None) -> Row | None:
    return next((r for r in rows if r.row_key == key and key is not None), None)


def _row_not_found(state: CommandState, reject: bool, entity: str, key: str) -> None:
    if reject:
        raise PlatformError(ErrorCode.ROW_NOT_FOUND, "要修改的数据已被删除",
                            [ErrorDetail(message="记录已不存在", entity=entity, row_key=key)])
    state.skipped.append(SkippedRow(entity=entity, row_key=key, reason="ROW_NOT_FOUND"))


class PatchMerger:
    """原端口 `ChangeMerger`（C08 第 5a 节，2026-10-29 起不是端口，管道阶段不用它）：按实体合并修改。

    调用方按实体分别合并：`current` 是 `entity` 这个实体的行，`patch` 中只含要合并到这些行的修改（合并主表时 `details`
    为空，合并明细时主表为 `none`）。只合并修改：新增和删除要用到执行上下文（默认值）、所属单据的明细（级联删除）
    和变更计划，由 `DocumentMerger` 处理；这里遇到时返回 400 INVALID_REQUEST，与原来的行为相同。"""

    def __init__(self, scales: Scales | None = None) -> None:
        self._scales = scales or NoScales()

    def merge(self, entity: EntityConfig, current: dict[str, Row], patch: DocumentPatch,
              writable: frozenset[str], *, parent_key: str | None = None) -> list[RowChange]:
        master = patch.master
        if master.op not in ("modify", "none") or any(d.op != "modify" for d in patch.details):
            raise PlatformError(ErrorCode.INVALID_REQUEST, "新增、删除由 DocumentMerger 合并")
        document = DocumentRef(entity=patch.entity, record_key=master.row_key)  # type: ignore[union-attr]
        found: list[RowChange] = []
        if isinstance(master, MasterModify):
            found += self._modify(EntityRules(patch.entity, entity), current[master.row_key], document, master.changes, writable)
        for detail in patch.details:
            rules = EntityRules(detail.entity, entity, parent_key)
            found += self._modify(rules, current[detail.row_key], document, detail.changes, writable)  # type: ignore[union-attr]
        return found

    def _modify(self, rules: EntityRules, row: Row, document: DocumentRef, changes: Mapping[str, BusinessValue],
                writable: frozenset[str]) -> list[RowChange]:
        rows = _Rows(rules, self._scales)
        rows.check(list(changes), row.values, writable, row.row_key, None)
        values: dict[str, Value] = {}
        old: dict[str, Value] = {}
        for name, raw in changes.items():
            new = rows.value(name, raw, row.row_key, None)
            if same_value(rules.fields[name].type, new, row.values.get(name)):
                continue
            values[name], old[name] = new, row.values.get(name)
            row.values[name] = new
        if not values:
            return []
        return [RowChange(document=document, entity=rules.code, op="modify", row_key=row.row_key, client_row_id=None,
                          values=values, old=old)]

