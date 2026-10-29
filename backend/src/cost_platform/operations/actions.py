"""按钮通用动作的展开（C06 第 6 节，OP-01、OP-02、OP-07）：`recalculate`、`updateRecords`、`updateTargets`。

展开只生成 `RowIntent`，不加锁、不写候选数据；write-pipeline 取出 intents，所属单据不在 `involved` 中的先加锁读入、
做冻结检查，再合并、检查写权限并计算（WP-18）。下一个动作看到的是上一个动作合并、计算后的候选数据。

"目标"：按钮操作中能找到目标的只有 `updateRecords` 的 `find`。`updateTargets` 和 `recalculate`（`target` 为
`targets`）的目标，是本命令前面各 `updateRecords` 找到的对象（C06 v17 没有写明，见 contract-gaps.md 第 1 项）。
"""

from __future__ import annotations

from dataclasses import dataclass

from cost_platform.contracts.ports import RelatedQuery, UnitOfWork
from cost_platform.contracts.types import (
    CommandState,
    DocumentData,
    DocumentRef,
    EntityConfig,
    ErrorCode,
    ExecutionContext,
    OperationConfig,
    PlatformError,
    Recalculate,
    RelationKeyFinder,
    Row,
    RowIntent,
    SqlFinder,
    TargetFinderConfig,
    TargetObject,
    UpdateRecords,
    UpdateTargets,
    Value,
)
from cost_platform.contracts.values import same_value

from .mapping import WritePlan, check_writable, source_value, split_ref
from .memory import CommandMemory, Finding, Target


@dataclass
class Round:
    """展开一个动作时用到的数据。`sources` 为选中的、加锁后仍存在的单据，按选中的先后。"""

    uow: UnitOfWork
    state: CommandState
    ctx: ExecutionContext
    related: RelatedQuery
    operation_code: str
    operation: OperationConfig
    page_master: str | None
    sources: list[DocumentRef]
    memory: CommandMemory

    def find(self, finder: TargetFinderConfig, source: DocumentData) -> list[TargetObject]:
        return self.related.find(self.uow, finder, source)

    def data(self, ref: DocumentRef) -> DocumentData | None:
        """来源计算后的数据：前面动作合并、计算后的候选数据；没有时为加锁读到的当前数据（OP-02、OP-08）。"""
        return self.state.candidate.get(ref) or self.state.current.get(ref)

    def entity(self, code: str) -> EntityConfig:
        return self.ctx.config.entity(code)

    def master_of(self, detail: str) -> str:
        """明细实体所属的主表实体：在页面主表实体、操作的 `impact` 和来源单据的实体中找。"""
        candidates = [c for c in (self.page_master, *self.operation.impact, *(r.entity for r in self.sources)) if c]
        for code in dict.fromkeys(candidates):
            if any(link.entity == detail for link in self.entity(code).details):
                return code
        raise PlatformError(ErrorCode.INTERNAL_ERROR,
                            f"找不到明细实体 {detail} 所属的主表实体：操作 {self.operation_code} 的 impact 中应列出它的主表实体")


def _empty_intent(ref: DocumentRef) -> RowIntent:
    """主表行的空修改：单据进入候选数据，按各自的计算规则重算（WP-18、WP-08）。"""
    return RowIntent(document=ref, entity=ref.entity, op="modify", row_key=ref.record_key, client_row_id=None, values={})


def _target_documents(memory: CommandMemory) -> list[DocumentRef]:
    return list(dict.fromkeys(t.document for t in memory.targets.values()))


# ---------------------------------------------------------------- recalculate

def expand_recalculate(rnd: Round, action: Recalculate) -> list[RowIntent]:
    """`source`：选中的单据；`targets`：前面 updateRecords 找到的目标所在的单据。"""
    if action.target == "source":
        return [_empty_intent(ref) for ref in rnd.sources]
    return [_empty_intent(ref) for ref in _target_documents(rnd.memory)]


# ---------------------------------------------------------------- updateRecords

def _per_row_entity(finder: TargetFinderConfig, master: str) -> str | None:
    """按来源的哪个明细逐行查找（C08 第 9 节）：关联键的 sourceKey 指向明细、或关联 SQL 的绑定变量引用明细字段时为
    这个明细实体；只用主表时为 None，执行一次。"""
    if isinstance(finder, RelationKeyFinder):
        entity = split_ref(finder.source_key)[0]
        return None if entity == master else entity
    assert isinstance(finder, SqlFinder)
    details = [e for e in (split_ref(ref)[0] for ref in finder.binds.values()) if e != master]
    return details[0] if details else None


def find_targets(rnd: Round, finder: TargetFinderConfig) -> list[Target]:
    """按来源行分别调用 `RelatedQuery.find`，记下每个目标由哪几行找到（OP-07）。

    来源是选中单据的全部行（按钮命令不带修改，C08 第 9 节）。各次的结果按来源行的先后合并，同一对象只算一个；
    `missing` 的对象（记录已不存在）跳过，不更新也不报错。返回本次找到的目标，同时并入本命令的目标。"""
    found: dict[tuple[str, str, str], Target] = {}
    for ref in rnd.sources:
        source = rnd.data(ref)
        if source is None:
            continue
        detail = _per_row_entity(finder, source.master.entity)
        if detail is None:
            calls: list[tuple[Row, DocumentData]] = [(source.master, source)]
        else:
            calls = [(row, DocumentData(ref=source.ref, master=source.master, details={**source.details, detail: [row]}))
                     for row in source.details.get(detail, [])]
        for row, one in calls:
            for obj in rnd.find(finder, one):
                if obj.missing or obj.record_key is None:
                    continue
                if obj.row_keys:
                    document = DocumentRef(rnd.master_of(obj.entity), obj.record_key)
                    row_key, is_detail = obj.row_keys[0], True
                else:
                    document = DocumentRef(obj.entity, obj.record_key)
                    row_key, is_detail = obj.record_key, False
                key = (obj.entity, obj.record_key, row_key)
                target = found.get(key)
                if target is None:
                    target = found[key] = Target(obj.entity, document, row_key, is_detail)
                target.found_by.append(Finding(source, row))
    for key, target in found.items():
        known = rnd.memory.targets.get(key)
        if known is None:
            rnd.memory.targets[key] = Target(target.entity, target.document, target.row_key, target.is_detail,
                                             list(target.found_by))
        else:
            known.found_by.extend(target.found_by)
    return list(found.values())


def _current_row(state: CommandState, document: DocumentRef, entity: str, row_key: str) -> Row | None:
    """目标行加锁读到的当前值；所属单据还没有读入时为 None。"""
    doc = state.current.get(document)
    if doc is None:
        return None
    if entity == document.entity:
        return doc.master
    return next((r for r in doc.details.get(entity, []) if r.row_key == row_key), None)


def _intents(rnd: Round, plan: WritePlan) -> list[RowIntent]:
    entities = {row.entity: rnd.entity(row.entity) for row in plan.rows.values()}
    checks = []
    for row in plan.rows.values():
        current = _current_row(rnd.state, DocumentRef(row.document_entity, row.record_key), row.entity, row.row_key)
        checks.append((row.entity, row.row_key, list(row.values), None if current is None else current.values))
    check_writable(rnd.operation_code, rnd.operation, entities, checks)
    return [RowIntent(document=DocumentRef(row.document_entity, row.record_key), entity=row.entity, op="modify",
                      row_key=row.row_key, client_row_id=None, values=values)
            for row, values in plan.resolved(entities)]


def expand_update_records(rnd: Round, action: UpdateRecords) -> list[RowIntent]:
    """按 `find` 找到记录，把来源计算后的值按 `fieldMapping` 写进去（C06 第 6 节）。

    每个目标按找到它的那几行来源分别取值；同一目标行被写成不同的值时 422 VALIDATION_FAILED。`fieldMapping` 为空时
    只生成空修改，让 write-pipeline 把找到的单据加锁读入，供后面的 `updateTargets` 使用。"""
    targets = find_targets(rnd, action.find)
    plan = WritePlan()
    for target in targets:
        row = plan.row(target.document.entity, target.document.record_key, target.entity, target.row_key)
        for finding in target.found_by:
            for item in action.field_mapping:
                plan.put(row, item.to, source_value(item.from_, finding))
    return _intents(rnd, plan)


# ---------------------------------------------------------------- updateTargets

def _matches(entity: EntityConfig, row: Row, wanted: dict[str, Value]) -> bool:
    types = {f.name: f.type for f in entity.fields}
    return all(same_value(types.get(name, "text"), row.values.get(name), value) for name, value in wanted.items())  # type: ignore[arg-type]


def expand_update_targets(rnd: Round, action: UpdateTargets) -> list[RowIntent]:
    """把来源计算后的值写到前面 updateRecords 找到的目标（C06 第 6 节）。

    `targets` 每项对应一种目标实体：没有 `detailEntity` 时写找到的对象本身；有 `detailEntity` 时写这张目标单据中
    `match` 选出的明细行。`from` 和 `match` 引用来源明细字段时取找到这个目标的那一行，引用主表字段时取主表。
    冲突按实际要写的目标行判断：同一目标被几行找到、各自写不同的明细行时不冲突；同一行被写成不同的值时 422。"""
    plan = WritePlan()
    for spec in action.targets:
        for target in [t for t in rnd.memory.targets.values() if t.entity == spec.entity]:
            doc = rnd.data(target.document)
            if doc is None:
                continue  # 目标单据已不存在：加锁读取时已按 rowNotFound 处理（WP-05）
            if spec.detail_entity is None:
                rows: list[tuple[Finding, str, str]] = [(f, target.entity, target.row_key) for f in target.found_by]
            elif target.is_detail:
                continue  # 找到的是明细行，不再往下选明细
            else:
                detail = rnd.entity(spec.detail_entity)
                rows = []
                for finding in target.found_by:
                    wanted = {name: source_value(ref, finding) for name, ref in spec.match.items()}
                    rows += [(finding, spec.detail_entity, r.row_key) for r in doc.details.get(spec.detail_entity, [])
                             if r.row_key is not None and _matches(detail, r, wanted)]
            for finding, entity, row_key in rows:
                planned = plan.row(target.document.entity, target.document.record_key, entity, row_key)
                for item in spec.field_mapping:
                    plan.put(planned, item.to, source_value(item.from_, finding))
    return _intents(rnd, plan)
