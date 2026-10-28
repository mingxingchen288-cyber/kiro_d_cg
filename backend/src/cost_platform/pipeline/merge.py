"""把 Patch 合并到加锁读到的当前数据（WP-04、WP-15）。目前只开放主表的修改（链路 0）。"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from cost_platform.contracts.types import (
    DocumentPatch,
    DocumentRef,
    EntityConfig,
    ErrorCode,
    ErrorDetail,
    PlatformError,
    Row,
    RowChange,
    Value,
)
from cost_platform.contracts.values import from_wire, same_value

_MAX_PLACES = Decimal("0.00000001")


def _stored(value: Value) -> Value:
    """写入数据库后的值：数值最多保留 8 位小数，第 9 位四舍五入（WP-15，负数按绝对值，与 Oracle 相同）；
    Oracle 把空文本存为空值。"""
    if isinstance(value, Decimal) and value.as_tuple().exponent < -8:  # type: ignore[operator]
        return value.quantize(_MAX_PLACES, rounding=ROUND_HALF_UP)
    if value == "":
        return None
    return value


class PatchMerger:
    def merge(self, entity: EntityConfig, current: dict[str, Row], patch: DocumentPatch,
              writable: frozenset[str]) -> list[RowChange]:
        master = patch.master
        if master.op != "modify" or patch.details:
            raise PlatformError(ErrorCode.INVALID_REQUEST, "目前只能修改主表")
        row = current[master.row_key]
        types = {f.name: f.type for f in entity.fields}
        values: dict[str, Value] = {}
        old: dict[str, Value] = {}
        for name, wire in master.changes.items():
            if name not in writable:
                raise PlatformError(ErrorCode.FIELD_NOT_WRITABLE, f"字段 {name} 不可写",
                                    [ErrorDetail(entity=patch.entity, row_key=master.row_key, field=name)])
            new = _stored(from_wire(types[name], wire))
            if same_value(types[name], new, row.values.get(name)):
                continue
            values[name], old[name] = new, row.values.get(name)
            row.values[name] = new
        if not values:
            return []
        document = DocumentRef(entity=patch.entity, record_key=master.row_key)
        return [RowChange(document=document, entity=patch.entity, op="modify", row_key=master.row_key,
                          client_row_id=None, values=values, old=old)]
