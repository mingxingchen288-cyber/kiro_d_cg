"""强制审批检查（AP-18）：对每个命令执行，位置在触发审批之后、写入变更之前（架构第 7 节第 8 步）。

对命令中每一行写入，按实体的 `approvalRequired`（C06 第 2 节）判断是否命中：修改了 `fields` 中的字段，或者删除了满足
`when` 的行，或者新增了满足 `when` 且填写了 `fields` 的行；修改前或修改后的行满足 `when` 都算命中，省略 `when` 时所有行
都满足。命中时：
- 这一行所在的单据在本命令中进入了审批，且命令来自规则 `sourcePages` 中的页面：放行；
- 执行上下文的来源是某个审批（审批流的操作，或应用待审修改）：放行；
- 其他情况拒绝整个命令，返回 409 APPROVAL_REQUIRED，`details` 给出实体、行和字段。

这个阶段在 C08 阶段表中归在"触发审批"一行（架构第 7 节第 8 步"触发审批，以及强制审批检查"），不写 `CommandState`。
对照旧系统 `ApprovalRequiredFieldPolicy`（`requiresApproval`、`guardApprovedSave`）和 `requireApprovalRoute` 的提示。
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    ApprovalRequiredRule,
    CommandState,
    EntityConfig,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    PlatformError,
    RequiredCondition,
    RowChange,
    Value,
)

from .rows import find_row


def _equal(value: Value, expected: str | None) -> bool:
    if value is None or expected is None:
        return value is None and expected is None
    if isinstance(value, bool):
        return expected.lower() in (("1", "true") if value else ("0", "false"))
    if isinstance(value, Decimal):
        try:
            return value == Decimal(expected)
        except InvalidOperation:
            return False
    return str(value) == expected


def when_holds(condition: RequiredCondition | None, values: Mapping[str, Value]) -> bool:
    if condition is None:
        return True
    results = []
    for item in condition.conditions:
        value = values.get(item.field)
        if item.op == "eq":
            results.append(_equal(value, item.value))
        elif item.op == "ne":
            results.append(not _equal(value, item.value))
        elif item.op == "isNull":
            results.append(value is None or value == "")
        else:
            results.append(value is not None and value != "")
    return all(results) if condition.logic == "AND" else any(results)


def hit_fields(rule: ApprovalRequiredRule, change: RowChange, old: Mapping[str, Value], new: Mapping[str, Value]) -> list[str | None]:
    """命中这条规则的字段；没命中为空。删除行命中时为 `[None]`（整行）。"""
    if change.op == "modify":
        changed = [f for f in rule.fields if f in change.values]
        return list(changed) if changed and (when_holds(rule.when, old) or when_holds(rule.when, new)) else []
    if change.op == "delete":
        return [None] if when_holds(rule.when, old) else []
    filled = [f for f in rule.fields if new.get(f) not in (None, "")]
    return list(filled) if filled and when_holds(rule.when, new) else []


class ApprovalRequiredStage:
    name = "强制审批检查"

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.changes.rows)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        if ctx.origin.kind == "approval":
            return
        entities: dict[str, EntityConfig] = {}
        denied: list[ErrorDetail] = []
        for change in state.changes.rows:
            entity = entities.setdefault(change.entity, ctx.config.entity(change.entity))
            if not entity.approval_required:
                continue
            before = find_row(state.current.get(change.document), change.entity, change.row_key, None)
            after = find_row(state.candidate.get(change.document), change.entity, change.row_key, change.client_row_id)
            old = dict(before.values) if before is not None else dict(change.old)
            new = {} if change.op == "delete" else {**old, **(dict(after.values) if after else {}), **change.values}
            labels = {f.name: f.label for f in entity.fields}
            for rule in entity.approval_required:
                fields = hit_fields(rule, change, old, new)
                if not fields:
                    continue
                if change.document in state.pending_documents and state.command.page in rule.source_pages:
                    continue
                for name in fields:
                    what = labels.get(name, name) if name else "这一行"
                    denied.append(ErrorDetail(message=f"{what}的修改必须审批，没有进入审批，或不是从允许的页面保存",
                                              entity=change.entity, row_key=change.row_key, client_row_id=change.client_row_id,
                                              field=name))
        if denied:
            raise PlatformError(ErrorCode.APPROVAL_REQUIRED, "本次修改必须审批，但没有进入审批", denied)
