"""字段映射：取值、`to` 的可写检查、同一目标行的取值冲突（C06 第 6 节，OP-02）。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from cost_platform.contracts.decimal_text import format_decimal
from cost_platform.contracts.types import (
    EntityConfig,
    ErrorCode,
    ErrorDetail,
    OperationConfig,
    PlatformError,
    Value,
)
from cost_platform.contracts.values import same_value

from .memory import Finding


def split_ref(ref: str) -> tuple[str, str]:
    """`实体.字段` → (实体, 字段)。"""
    entity, sep, name = ref.partition(".")
    if not sep or not entity or not name:
        raise PlatformError(ErrorCode.INTERNAL_ERROR, f"字段引用 {ref} 不是“实体.字段”的写法")
    return entity, name


def source_value(ref: str, finding: Finding) -> Value:
    """`from` 或 `match` 引用的来源字段的值（C06 第 6 节）：

    - 引用来源主表的字段时取主表的值（主表和明细有同名字段时也一样）；
    - 引用明细字段时取找到这个目标的那一行的值。
    取的都是来源计算后的数据（前面各动作合并、计算后的候选数据，没有时为加锁读到的当前数据）。"""
    entity, name = split_ref(ref)
    if entity == finding.source.master.entity:
        return finding.source.master.values.get(name)
    if entity == finding.row.entity:
        return finding.row.values.get(name)
    raise PlatformError(ErrorCode.INTERNAL_ERROR,
                        f"字段映射引用了 {ref}，但找到目标的来源行是 {finding.row.entity}，取不到这个字段的值")


def is_erp_row(entity: EntityConfig, values: dict[str, Value]) -> bool:
    """按当前值判断是否为 ERP 行（C06 第 2 节 `erpRow`，WP-14 的判断方法）。"""
    erp = entity.erp_row
    if erp is None:
        return False
    field_ = next((f for f in entity.fields if f.name == erp.column), None) or \
        next((f for f in entity.fields if f.column == erp.column), None)
    if field_ is None:
        return False
    current = values.get(field_.name)
    if current is None:
        return False
    if field_.type == "number":
        try:
            return Decimal(str(current)) == Decimal(erp.value)
        except ArithmeticError:
            return False
    return str(current) == erp.value


def not_writable(operation_code: str, operation: OperationConfig, entity_code: str, entity: EntityConfig, name: str,
                 current: dict[str, Value] | None) -> str | None:
    """`to` 不能写的原因；可以写时为 None（C06 第 6 节）。

    - 必须在操作的 `writableFields` 中；
    - 不能是计算字段；
    - 不能是只读的 ERP 列：没有 `erpRow` 的实体在所有行上只读；有 `erpRow` 的只在 ERP 行上只读。目标行的当前值
      还没有读入时（`current` 为 None，例如 updateRecords 刚找到、还没加锁读取的单据），由 write-pipeline 加锁读取后
      按 WP-14 判断。"""
    if name not in operation.writable_fields.get(entity_code, []):
        return f"{name} 不在操作 {operation_code} 允许写入的字段内"
    field_ = next((f for f in entity.fields if f.name == name), None)
    if field_ is None:
        return f"{name} 不是 {entity_code} 的字段"
    if field_.role == "calculated":
        return f"{field_.label}（{name}）是计算字段，由计算规则得出"
    if field_.source == "erp":
        if entity.erp_row is None:
            return f"{field_.label}（{name}）是 ERP 列，不能写"
        if current is not None and is_erp_row(entity, current):
            return f"{field_.label}（{name}）是 ERP 行的 ERP 列，不能写"
    return None


@dataclass
class PlannedRow:
    """一行要写的目标：每个字段收到的值，按来源行的先后。"""

    document_entity: str
    record_key: str
    entity: str
    row_key: str
    values: dict[str, list[Value]] = field(default_factory=dict)


class WritePlan:
    """一个动作要写的全部目标行。同一目标行（实体、主键）在一个动作中只出现一次，几行来源的值都记在它下面。"""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], PlannedRow] = {}

    def row(self, document_entity: str, record_key: str, entity: str, row_key: str) -> PlannedRow:
        key = (entity, row_key)
        found = self.rows.get(key)
        if found is None:
            found = PlannedRow(document_entity, record_key, entity, row_key)
            self.rows[key] = found
        return found

    def put(self, row: PlannedRow, name: str, value: Value) -> None:
        row.values.setdefault(name, []).append(value)

    def resolved(self, entities: dict[str, EntityConfig]) -> list[tuple[PlannedRow, dict[str, Value]]]:
        """每一行最终要写的值。同一行的同一字段被写成不同的值时，422 VALIDATION_FAILED，列出每一处（OP-02）。"""
        conflicts: list[ErrorDetail] = []
        result: list[tuple[PlannedRow, dict[str, Value]]] = []
        for row in self.rows.values():
            types = {f.name: f.type for f in entities[row.entity].fields}
            labels = {f.name: f.label for f in entities[row.entity].fields}
            values: dict[str, Value] = {}
            for name, given in row.values.items():
                distinct = _distinct(types.get(name, "text"), given)
                if len(distinct) > 1:
                    conflicts.append(ErrorDetail(
                        message=f"{row.entity}（{row.row_key}）的 {labels.get(name, name)}（{name}）会被写成 {_join(distinct)}",
                        entity=row.entity, row_key=row.row_key, field=name))
                values[name] = given[0]
            result.append((row, values))
        if conflicts:
            raise PlatformError(ErrorCode.VALIDATION_FAILED, "同一条记录会被写成不同的值", conflicts)
        return result


def _distinct(field_type: str, values: Iterable[Value]) -> list[Value]:
    found: list[Value] = []
    for value in values:
        if not any(same_value(field_type, value, seen) for seen in found):  # type: ignore[arg-type]
            found.append(value)
    return found


def _join(values: list[Value]) -> str:
    texts = [format_decimal(v) if isinstance(v, Decimal) else ("空" if v is None else str(v)) for v in values]
    return "、".join(texts[:-1]) + " 和 " + texts[-1]


def check_writable(operation_code: str, operation: OperationConfig, entities: dict[str, EntityConfig],
                   rows: Iterable[tuple[str, str, Iterable[str], dict[str, Value] | None]]) -> None:
    """检查每一行要写的字段：(实体、行主键、字段、这一行的当前值)。有不能写的字段时 422 FIELD_NOT_WRITABLE，逐项列出。"""
    problems: list[ErrorDetail] = []
    for entity_code, row_key, names, current in rows:
        for name in names:
            reason = not_writable(operation_code, operation, entity_code, entities[entity_code], name, current)
            if reason is not None:
                problems.append(ErrorDetail(message=reason, entity=entity_code, row_key=row_key, field=name))
    if problems:
        raise PlatformError(ErrorCode.FIELD_NOT_WRITABLE, "有字段不能写", problems)
