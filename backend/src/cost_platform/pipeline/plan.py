"""变更计划（`CommandState.changes`）的维护：只含有变化的列（WP-04、WP-08）。

一行在一个命令中只有一个 `RowChange`：Patch、各动作和计算带出的变化都并入它。修改的旧值始终取命令开始时加锁读到的
当前值（WP-08），新值改回旧值时这一列从计划中去掉。
"""

from __future__ import annotations

from cost_platform.contracts.types import ChangePlan, CommandState, DocumentRef, FieldType, Row, RowChange, Value
from cost_platform.contracts.values import same_value


def row_id(row: Row | RowChange) -> tuple[str, str]:
    """行在命令中的标识：（实体，新增行为 clientRowId、已保存的行为主键），取得主键后不变（C01 第 5 节）。"""
    return row.entity, row.client_row_id or row.row_key or ""


def find_change(plan: ChangePlan, entity: str, key: str) -> RowChange | None:
    """按（实体、主键或 clientRowId）找到计划中的行。"""
    for change in plan.rows:
        if change.entity == entity and key in (change.row_key, change.client_row_id):
            return change
    return None


def note_modify(state: CommandState, document: DocumentRef, row: Row, field: str, field_type: FieldType,
                new: Value, original: Value) -> bool:
    """把一列的新值记入计划，并写进候选行；`original` 为这一列在命令开始时的值。返回这一列现在是否有变化。"""
    row.values[field] = new
    key = row.row_key if row.row_key is not None else row.client_row_id or ""
    change = find_change(state.changes, row.entity, key)
    if change is not None and change.op == "add":
        change.values[field] = new
        return True
    if change is not None and change.op == "delete":
        return False
    if same_value(field_type, new, original):
        if change is not None and field in change.values:
            del change.values[field]
            change.old.pop(field, None)
            if not change.values:
                state.changes.rows.remove(change)
        return False
    if change is None:
        change = RowChange(document=document, entity=row.entity, op="modify", row_key=row.row_key, client_row_id=None,
                           values={}, old={})
        state.changes.rows.append(change)
    change.values[field] = new
    change.old.setdefault(field, original)
    return True
