"""冻结（AP-03、AP-06）：`FreezeReader`（C08 第 13 节）和"冻结检查"阶段（C08 第 6 节）。

冻结记录按（根表、主键）登记：注册过的表为所属单据主表实体的 table，冻结整张单据（主表和全部明细，含之后要新增的明细）；
单表页和没注册的表为这一行（C08 第 1 节 `FreezeEntry`）。命令涉及的单据（`involved`）总是主表实体和主单主键，明细按实体的
`details.parentKey` 归到所属主单，从哪个页面写入都一样。来源为本审批的命令可以写本审批冻结的数据。

对照旧系统 `ApprovalFreezeService.guardSave`：按表和主键查 WF_APPROVAL_LOCK 中有效的范围，不是本审批的就拒绝
（旧系统按字段范围判断，新平台按 C06 7.4 整单冻结）。
"""

from __future__ import annotations

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    CommandState,
    DocumentRef,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    FreezeEntry,
    PlatformError,
)

from .store import ApprovalStore

FROZEN_MESSAGE = "数据已被审批冻结，审批结束前不能修改"


def own_approval(ctx: ExecutionContext) -> str | None:
    """执行上下文的来源为审批时，这个审批可以写自己冻结的数据。"""
    return ctx.origin.approval_id if ctx.origin.kind == "approval" else None


class ApprovalFreezeReader:
    """`FreezeReader`：按根表主键返回冻结记录，只读，不加锁。"""

    def __init__(self, store: ApprovalStore) -> None:
        self._store = store

    def find(self, uow: UnitOfWork, table: str, record_keys: list[str]) -> dict[str, FreezeEntry]:
        if not record_keys:
            return {}
        return self._store.frozen(uow, table, record_keys)


def frozen_detail(entity: str | None, key: str, entry: FreezeEntry) -> ErrorDetail:
    return ErrorDetail(message=f"{entry.table} 中主键为 {key} 的数据已被审批 {entry.approval_id} 冻结，审批结束前不能修改",
                       entity=entity, row_key=key, approval_id=entry.approval_id)


def check_rows(store: ApprovalStore, uow: UnitOfWork, ctx: ExecutionContext, table: str, keys: list[str],
               entity: str | None = None) -> None:
    """写没注册的表（或按根表）之前的冻结检查：被别的审批冻结时返回 409 FROZEN_BY_APPROVAL。"""
    own = own_approval(ctx)
    found = store.frozen(uow, table, keys) if keys else {}
    blocked = [frozen_detail(entity, key, entry) for key, entry in found.items() if entry.approval_id != own]
    if blocked:
        raise PlatformError(ErrorCode.FROZEN_BY_APPROVAL, FROZEN_MESSAGE, blocked)


class FreezeCheckStage:
    """"冻结检查"阶段：在加锁之后，按命令涉及的单据查询冻结记录；动作执行中新找到的单据由 write-pipeline 加锁后再执行
    一次（WP-18）。实体的 `freezable` 为 false 时不检查。只读，不写 `CommandState`。"""

    name = "冻结检查"

    def __init__(self, store: ApprovalStore) -> None:
        self._store = store

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.involved)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        by_table: dict[str, list[DocumentRef]] = {}
        for ref in dict.fromkeys(state.involved):
            entity = ctx.config.entity(ref.entity)
            if entity.freezable:
                by_table.setdefault(entity.table, []).append(ref)
        own = own_approval(ctx)
        blocked: list[ErrorDetail] = []
        for table, refs in by_table.items():
            found = self._store.frozen(uow, table, [r.record_key for r in refs])
            for ref in refs:
                entry = found.get(ref.record_key)
                if entry is not None and entry.approval_id != own:
                    blocked.append(frozen_detail(ref.entity, ref.record_key, entry))
        if blocked:
            raise PlatformError(ErrorCode.FROZEN_BY_APPROVAL, FROZEN_MESSAGE, blocked)
