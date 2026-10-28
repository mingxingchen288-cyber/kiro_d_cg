"""命令执行：按操作的 `kind` 取对应的流程执行，一个命令一个事务（架构 6.3、第 7 节）。

流程只调用端口：判重和命令记录（CommandRecorder）、权限（PermissionChecker）、加锁读取和写入（DocumentStore）、
合并（ChangeMerger）。新增一类操作时注册一个流程，不改已有流程。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from cost_platform.contracts.ports import (
    ChangeMerger,
    CommandRecorder,
    DocumentStore,
    PermissionChecker,
    UnitOfWork,
    UnitOfWorkFactory,
)
from cost_platform.contracts.types import (
    Command,
    CommandResult,
    EntityConfig,
    ErrorCode,
    ExecutionContext,
    PlatformError,
    ResultRow,
    Row,
    RowChange,
    SkippedRow,
)
from cost_platform.contracts.values import to_wire


class Flow(Protocol):
    def run(self, uow: UnitOfWork, command: Command, ctx: ExecutionContext) -> CommandResult:
        """在已插入命令记录的事务中执行；返回 outcome 为 unchanged 时调用方回滚。"""
        ...


def _result_row(entity: EntityConfig, row: Row) -> ResultRow:
    """WP-12：受影响行取自候选数据，含实体的全部字段。"""
    types = {f.name: f.type for f in entity.fields}
    values = {name: to_wire(types[name], value) for name, value in row.values.items()}
    return ResultRow(entity=row.entity, row_key=row.row_key or "", values=values, frozen=None)


class SaveFlow:
    """页面保存（operation.kind = save）：加锁读取 → 合并 → 写入。目前只开放修改主表。"""

    def __init__(self, store: DocumentStore, merger: ChangeMerger, permission: PermissionChecker,
                 log: CommandRecorder) -> None:
        self._store = store
        self._merger = merger
        self._permission = permission
        self._log = log

    def run(self, uow: UnitOfWork, command: Command, ctx: ExecutionContext) -> CommandResult:
        page = command.page or ""
        changes: list[RowChange] = []
        affected: list[tuple[EntityConfig, Row]] = []
        skipped: list[SkippedRow] = []
        entities: dict[str, EntityConfig] = {}
        for patch in sorted(command.documents, key=lambda p: (p.entity, p.master.row_key)):  # type: ignore[union-attr]
            entity = entities.setdefault(patch.entity, ctx.config.entity(patch.entity))
            row_key = patch.master.row_key  # type: ignore[union-attr]
            current = self._store.lock_load(uow, patch.entity, entity, [row_key])
            if row_key not in current:  # WP-05：默认跳过
                skipped.append(SkippedRow(entity=patch.entity, row_key=row_key, reason="ROW_NOT_FOUND"))
                continue
            writable = self._permission.writable_fields(ctx, page, patch.entity)
            found = self._merger.merge(entity, current, patch, writable)
            if found:
                changes += found
                affected.append((entity, current[row_key]))
        if not changes:
            return CommandResult(request_key=command.request_key, outcome="unchanged", rows=[], id_map={},
                                 prompts=[], skipped=skipped, approvals=[])
        for code, entity in entities.items():
            self._store.write(uow, entity, [c for c in changes if c.entity == code])
        result = CommandResult(request_key=command.request_key, outcome="saved",
                               rows=[_result_row(e, r) for e, r in affected], id_map={}, prompts=[],
                               skipped=skipped, approvals=[])
        audit = changes if ctx.config.page_view(page).audit else None
        self._log.finish(uow, ctx.identity.user_id, command, result, audit, ctx.now)
        return result


class CommandRunner:
    """`CommandExecutor`。"""

    def __init__(self, uow_factory: UnitOfWorkFactory, log: CommandRecorder, permission: PermissionChecker,
                 flows: Mapping[str, Flow]) -> None:
        self._uow = uow_factory
        self._log = log
        self._permission = permission
        self._flows = flows

    def execute(self, command: Command, ctx: ExecutionContext) -> CommandResult:
        operation = ctx.config.operation(command.operation)
        flow = self._flows.get(operation.kind)
        if flow is None:
            raise PlatformError(ErrorCode.INVALID_REQUEST, f"暂不支持这类操作：{operation.kind}")
        with self._uow.begin() as uow:
            replay = self._log.begin(uow, ctx.identity.user_id, command, ctx.now)
            if replay is not None:
                return replay
            if not self._permission.can_run(ctx, command.operation, command.page):
                raise PlatformError(ErrorCode.PERMISSION_DENIED, "没有执行这个操作的权限")
            result = flow.run(uow, command, ctx)
            if result.outcome != "unchanged":
                uow.commit()
            return result
