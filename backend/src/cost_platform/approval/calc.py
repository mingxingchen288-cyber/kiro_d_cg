"""审批详情和最终批准时的重算：当前数据加上待审修改或勾选的行要写的值，经 rules-core 的 commit 阶段求值（C07），
得到"修改后"（AP-08、C06 7.6）。计算只在 rules-core 中实现，这里只组装求值请求、解释结果（架构第 4 节）。

规则包按主表实体一份（C07 第 1 节 `packId`），取自执行上下文的配置快照。规则没有数据项（C06 v27 去掉），
求值请求的 `data` 为空，与保存时相同。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from cost_platform.contracts.ports import RulesEngine
from cost_platform.contracts.types import (
    BusinessValue,
    ChangedRow,
    DocumentData,
    EntityConfig,
    ErrorCode,
    EvalComputed,
    EvalContext,
    EvalDocument,
    EvalFailure,
    EvalRow,
    EvaluationRequest,
    EvaluationResult,
    ExecutionContext,
    FieldType,
    PlatformError,
    Row,
    Value,
    dump_wire,
    parse_wire,
)
from cost_platform.contracts.values import from_wire, to_wire

from .patch import Applied, Change


def wire(field_type: FieldType, value: object) -> BusinessValue:
    """后端内部的值转为 JSON 中的值；SQL 取值得到的文本等先按字段类型转换。"""
    return to_wire(field_type, coerce(field_type, value))


def coerce(field_type: FieldType, value: object) -> Value:
    """SQL 取值得到的值按字段类型转成后端内部的值（取值表达式的结果类型由数据库决定，例如 NVL 的第一个参数为空时是文本）。"""
    if value is None:
        return None
    if field_type == "number":
        if isinstance(value, bool):
            return Decimal(int(value))
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if field_type == "boolean":
        return value if isinstance(value, bool) else bool(int(str(value)))
    if field_type == "date":
        if isinstance(value, datetime):
            return value.date()
        return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    if field_type == "datetime":
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return value if isinstance(value, str) else str(value)


class Recalculator:
    """`rules` 为空时不计算（没有接入 rules-core 时，修改后只含待审修改本身）。"""

    def __init__(self, rules: RulesEngine | None) -> None:
        self._rules = rules

    def compute(self, ctx: ExecutionContext, applied: Applied, *, page: str | None, operation: str | None,
                user_id: str, department_id: str | None) -> DocumentData:
        document = applied.document
        if self._rules is None or applied.master_deleted:
            return document
        master_code = document.ref.entity
        entities: dict[str, EntityConfig] = {master_code: ctx.config.entity(master_code)}
        for code in document.details:
            entities[code] = ctx.config.entity(code)
        types = {code: {f.name: f.type for f in e.fields} for code, e in entities.items()}
        changes = {(c.entity, c.row_key): c for c in applied.changes}

        def eval_row(row: Row) -> EvalRow:
            fields = types[row.entity]
            change = changes.get((row.entity, row.row_key or ""))
            old = None
            if change is not None and change.op == "modify":
                old = {k: wire(fields[k], v) for k, v in change.old.items() if k in fields}
            values = {k: wire(fields[k], v) for k, v in row.values.items() if k in fields}
            if row.row_key:
                return EvalRow(row_key=row.row_key, values=values, old=old)
            return EvalRow(client_row_id=row.client_row_id, values=values, old=old)

        deleted = {(r.entity, r.row_key) for r in applied.deleted}
        details = {code: [eval_row(r) for r in rows] for code, rows in document.details.items()}
        for row in applied.deleted:
            if row.entity != master_code:
                details.setdefault(row.entity, []).append(eval_row(row))
        request = EvaluationRequest(
            purpose="operation", operation=operation, page=page, phase="commit",
            context=EvalContext(user_id=user_id, department_id=department_id, role=ctx.identity.role_code,
                                today=ctx.now.date(), origin="approval"),
            document=EvalDocument(entity=master_code, master=eval_row(document.master), details=details),
            changed=[ChangedRow(entity=c.entity, row_key=c.row_key, op=c.op, fields=list(c.fields)) for c in applied.changes],
            data={},
        )
        handle = ctx.config.rules_pack(master_code)
        raw = self._rules.evaluate(handle, json.dumps(dump_wire(EvaluationRequest, request), ensure_ascii=False))
        result = parse_wire(EvaluationResult, json.loads(raw))
        if isinstance(result, EvalFailure):
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"计算失败：{result.error.message}")
        assert isinstance(result, EvalComputed)
        index: dict[tuple[str, str], Row] = {(document.master.entity, document.master.row_key or ""): document.master}
        for code, rows in document.details.items():
            for row in rows:
                index[(code, row.row_key or row.client_row_id or "")] = row
        for item in result.rows:
            key = (item.entity, item.row_key or item.client_row_id or "")
            row = index.get(key)
            if row is None or key in deleted:
                continue
            fields = types[item.entity]
            row.values.update({k: from_wire(fields[k], v) for k, v in item.computed.items() if k in fields})
        return document


__all__ = ["Change", "Recalculator", "coerce", "wire"]
