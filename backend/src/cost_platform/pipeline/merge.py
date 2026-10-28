"""把 Patch 合并到读到的当前数据（WP-04、WP-15）。目前开放主表和明细的修改；新增、删除还没有开放。

调用方按实体分别合并：`current` 是 `entity` 这个实体的行（主表为加锁读到的主表行，明细为这张单据的明细行），
`patch` 中只含要合并到这些行的修改：合并主表时 `details` 为空，合并明细时主表为 `none`。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from cost_platform.contracts.types import (
    BusinessValue,
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
        if master.op not in ("modify", "none"):
            raise PlatformError(ErrorCode.INVALID_REQUEST, "目前只能修改主表和明细")
        document = DocumentRef(entity=patch.entity, record_key=master.row_key)
        changes: list[RowChange] = []
        if master.op == "modify":
            changes += self._modify(entity, current[master.row_key], document, patch.entity, master.changes, writable)
        for detail in patch.details:
            if detail.op != "modify":
                raise PlatformError(ErrorCode.INVALID_REQUEST, "目前只能修改明细")
            changes += self._modify(entity, current[detail.row_key], document, detail.entity, detail.changes, writable)
        return changes

    @staticmethod
    def _modify(entity: EntityConfig, row: Row, document: DocumentRef, entity_code: str,
                patch: dict[str, BusinessValue], writable: frozenset[str]) -> list[RowChange]:
        """一行的修改：只改出现的字段，与当前值相同不算变化；新值写进 row 作为候选数据。"""
        types = {f.name: f.type for f in entity.fields}
        values: dict[str, Value] = {}
        old: dict[str, Value] = {}
        for name, wire in patch.items():
            if name not in writable:
                raise PlatformError(ErrorCode.FIELD_NOT_WRITABLE, f"字段 {name} 不可写",
                                    [ErrorDetail(entity=entity_code, row_key=row.row_key, field=name)])
            new = _stored(from_wire(types[name], wire))
            if same_value(types[name], new, row.values.get(name)):
                continue
            values[name], old[name] = new, row.values.get(name)
            row.values[name] = new
        if not values:
            return []
        return [RowChange(document=document, entity=entity_code, op="modify", row_key=row.row_key, client_row_id=None,
                          values=values, old=old)]
