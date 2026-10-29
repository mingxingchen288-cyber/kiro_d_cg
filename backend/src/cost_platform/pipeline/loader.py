"""确定涉及的单据（页面保存）和加锁读取（架构第 7 节第 3、4 步，WP-03、WP-05）。"""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Sequence

from cost_platform.contracts.ports import PermissionChecker, UnitOfWork
from cost_platform.contracts.types import (
    CommandState,
    DocumentData,
    DocumentRef,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    MasterAdd,
    PlatformError,
    SkippedRow,
)

from .document_store import DetailSource, RowStore


def is_new_key(key: str | None) -> bool:
    """还没有主键的行用前端的临时编号（`tmp-` 加 UUID，C01 第 5 节）。"""
    return key is None or key.startswith("tmp-")


def document_ref(entity: str, master: object) -> DocumentRef:
    """Patch 所属的单据：新增的单据在取得主键前，record_key 为主表行的 clientRowId（C08 第 6 节 RowChange）。"""
    key = master.client_row_id if isinstance(master, MasterAdd) else master.row_key  # type: ignore[attr-defined]
    return DocumentRef(entity=entity, record_key=key)


def _sort_key(ref: DocumentRef) -> tuple[str, int, object]:
    """按（实体、主键）排序；数字主键按数值。"""
    key = ref.record_key
    return (ref.entity, 0, int(key)) if key.lstrip("-").isdigit() else (ref.entity, 1, key)


class PageSaveInvolved:
    """管道阶段"确定涉及的单据"的页面保存部分（C08 第 6 节）：命令中每张单据一项，按（实体、主键）排序。
    只写 `involved`。按钮操作由 operations、审批处理由 approval 给出。"""

    name = "pipeline.involved"

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.command.documents)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        refs = {document_ref(p.entity, p.master) for p in state.command.documents}
        for ref in sorted(refs - set(state.involved), key=_sort_key):
            state.involved.append(ref)


class DocumentLoader:
    """加锁读取：主表行一个实体一条 `SELECT … FOR UPDATE WAIT n`（单据锁），明细一条语句读出，结果写入 `current`。"""

    def __init__(self, store: RowStore, permission: PermissionChecker) -> None:
        self._store = store
        self._permission = permission

    def lock(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext,
             refs: Sequence[DocumentRef] | None = None) -> list[DocumentRef]:
        """锁住并读入 `refs`（省略时为 `involved` 中还没有读入的已有单据），按（实体、主键）排序。

        单据已不存在时按操作的 `rowNotFound`：`skip` 写入 `skipped` 并从 `involved` 去掉，`reject` 返回 409 ROW_NOT_FOUND
        （WP-05）。用户发起的命令带出行权限判断列，超出时 403（WP-03）；来源为审批时不查行权限（C08 第 7 节）。
        返回读到的单据。"""
        wanted = refs if refs is not None else state.involved
        pending = sorted({r for r in wanted if not is_new_key(r.record_key) and r not in state.current}, key=_sort_key)
        by_entity: dict[str, list[DocumentRef]] = defaultdict(list)
        for ref in pending:
            by_entity[ref.entity].append(ref)
        command = state.command
        reject = ctx.config.operation(command.operation).row_not_found == "reject"
        loaded: list[DocumentRef] = []
        for code in sorted(by_entity):
            entity = ctx.config.entity(code)
            condition = None
            if ctx.origin.kind == "user" and command.page is not None:
                condition = self._permission.row_condition(ctx, command.page, code)
            keys = [r.record_key for r in by_entity[code]]
            masters = self._store.lock_load(uow, code, entity, keys, row_condition=condition)
            missing = [k for k in keys if k not in masters]
            if missing and reject:
                raise PlatformError(ErrorCode.ROW_NOT_FOUND, "要修改的数据已被删除",
                                    [ErrorDetail(message="记录已不存在", entity=code, row_key=k) for k in missing])
            for key in missing:
                state.skipped.append(SkippedRow(entity=code, row_key=key, reason="ROW_NOT_FOUND"))
                state.involved[:] = [r for r in state.involved if r != DocumentRef(code, key)]
            found = [k for k in keys if k in masters]
            sources = [DetailSource(link.entity, ctx.config.entity(link.entity), link.parent_key) for link in entity.details]
            details = self._store.load_details_many(uow, sources, found) if sources and found else {}
            for key in found:
                ref = DocumentRef(code, key)
                state.current[ref] = DocumentData(
                    ref=ref, master=masters[key],
                    details={s.entity_code: details[s.entity_code][key] for s in sources})
                loaded.append(ref)
        return loaded


def candidate_of(state: CommandState, ref: DocumentRef) -> DocumentData | None:
    """这张单据的候选数据：第一次取时由加锁读到的当前值复制而来。"""
    if ref not in state.candidate and ref in state.current:
        state.candidate[ref] = copy.deepcopy(state.current[ref])
    return state.candidate.get(ref)
