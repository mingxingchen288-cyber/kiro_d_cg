"""确定涉及的单据（页面保存）和加锁读取（架构第 7 节第 3、4 步，WP-03、WP-05）。"""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Callable, Sequence

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
from .locks import LockBook, document_target


def is_new_key(key: str | None) -> bool:
    """还没有主键的行用前端的临时编号（`tmp-` 加 UUID，C01 第 5 节）。"""
    return key is None or key.startswith("tmp-")


def document_ref(entity: str, master: object) -> DocumentRef:
    """Patch 所属的单据：新增的单据在取得主键前，record_key 为主表行的 clientRowId（C08 第 6 节 RowChange）。"""
    key = master.client_row_id if isinstance(master, MasterAdd) else master.row_key  # type: ignore[attr-defined]
    return DocumentRef(entity=entity, record_key=key)


def sort_key(ref: DocumentRef) -> tuple[str, int, object]:
    """按（实体、主键）排序；数字主键按数值。"""
    key = ref.record_key
    return (ref.entity, 0, int(key)) if key.lstrip("-").isdigit() else (ref.entity, 1, key)


APPROVAL_OPERATIONS = frozenset({"approval.pass", "approval.reject", "approval.withdraw"})
"""审批处理命令的操作编码（C02 第 1 节）：不是配置中的操作，配置快照取不到它们的 `rowNotFound`。"""


def rejects_missing(state: CommandState, ctx: ExecutionContext) -> bool:
    """要处理的行已不存在时是否整个命令返回 409（操作的 `rowNotFound` 为 reject，WP-05）。审批处理命令按 skip：
    最终批准时已不存在的行由 approval 记为跳过（AP-10）。"""
    code = state.command.operation
    return code not in APPROVAL_OPERATIONS and ctx.config.operation(code).row_not_found == "reject"


def is_new_document(state: CommandState, ref: DocumentRef) -> bool:
    """这张单据是本命令新增的，库里还没有，不加锁读取：前端新增、还没有主键的（`tmp-`）；或主表行由意图新增、带着送审时
    预留的主键（新建的单据整张进入审批，最终批准时插入，AP-02、AP-10）。"""
    if is_new_key(ref.record_key):
        return True
    adds = any(i.op == "add" and i.entity == ref.entity and i.row_key == ref.record_key for i in state.intents)
    return adds or any(c.op == "add" and c.entity == ref.entity and c.row_key == ref.record_key for c in state.changes.rows)


def known_missing(state: CommandState, ref: DocumentRef) -> bool:
    """这张单据在本命令中加锁读取时已不存在、按 `rowNotFound: skip` 记入了 `skipped`（WP-05）：不再加锁读取一次。"""
    return any(s.entity == ref.entity and s.row_key == ref.record_key and s.reason == "ROW_NOT_FOUND" for s in state.skipped)


class PageSaveInvolved:
    """管道阶段"确定涉及的单据"的页面保存部分（C08 第 6 节）：命令中每张单据一项，按（实体、主键）排序。
    只写 `involved`。按钮操作由 operations、审批处理由 approval 给出。"""

    name = "确定涉及的单据"

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.command.documents)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        refs = {document_ref(p.entity, p.master) for p in state.command.documents}
        for ref in sorted(refs - set(state.involved), key=sort_key):
            state.involved.append(ref)


class DocumentLoader:
    """加锁读取：按统一顺序（`locks.py`）锁住主表行（单据锁），明细一条语句读出，结果写入 `current`。

    `book` 为本事务已持有的锁（与 `TableWriter`、`BusinessLocker` 共用，plugin.py 接线）；省略时用自己的。"""

    def __init__(self, store: RowStore, permission: PermissionChecker, book: LockBook | None = None) -> None:
        self._store = store
        self._permission = permission
        self._book = book or LockBook()

    def lock(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext,
             refs: Sequence[DocumentRef] | None = None,
             needs_details: Callable[[DocumentRef], bool] | None = None) -> list[DocumentRef]:
        """锁住并读入 `refs`（省略时为 `involved` 中还没有读入的已有单据），按统一顺序：层级 → 表 → 主键（WP-03）。
        要锁的单据排在本事务已持有的锁之前时 500（`LockBook.claim`）：往前、同层找到的单据应在"确定涉及的单据"
        一起锁住。本事务已持有锁的单据（例如审批处理在"确定涉及的单据"已锁住）再锁一次并读出。
        `state.defer_lock` 为 True 时只普通读取、不加锁（由"触发审批"按顺序一次锁完并核对，AP-02）。

        `needs_details` 给出哪些单据要读明细（页面保存用 `calc.patch_needs_details`，WP-08、WP-10）；省略时都读。
        不读明细的单据 `details` 为空，这张单据不会求值（`calc.needs_recalculation`）。

        单据已不存在时按操作的 `rowNotFound`：`skip` 写入 `skipped` 并从 `involved` 去掉，`reject` 返回 409 ROW_NOT_FOUND
        （WP-05）。用户发起的命令带出行权限判断列，超出时 403（WP-03）；来源为审批时不查行权限（C08 第 7 节）。
        返回读到的单据。"""
        wanted = refs if refs is not None else state.involved
        targets = {r: document_target(ctx, r) for r in wanted if not is_new_key(r.record_key) and r not in state.current}
        pending = sorted(targets, key=lambda r: targets[r].order())
        if not state.defer_lock:
            self._book.claim(uow, targets.values())
        read = self._store.read_masters if state.defer_lock else self._store.lock_load
        by_entity: dict[str, list[DocumentRef]] = defaultdict(list)
        for ref in pending:
            by_entity[ref.entity].append(ref)
        command = state.command
        reject = rejects_missing(state, ctx)
        loaded: list[DocumentRef] = []
        for code in by_entity:  # 按统一顺序第一次出现的先后：层级、表名
            entity = ctx.config.entity(code)
            condition = None
            if ctx.origin.kind == "user" and command.page is not None:
                condition = self._permission.row_condition(ctx, command.page, code)
            keys = [r.record_key for r in by_entity[code]]
            masters = read(uow, code, entity, keys, row_condition=condition)
            missing = [k for k in keys if k not in masters]
            if missing and reject:
                raise PlatformError(ErrorCode.ROW_NOT_FOUND, "要修改的数据已被删除",
                                    [ErrorDetail(message="记录已不存在", entity=code, row_key=k) for k in missing])
            for key in missing:
                state.skipped.append(SkippedRow(entity=code, row_key=key, reason="ROW_NOT_FOUND"))
                state.involved[:] = [r for r in state.involved if r != DocumentRef(code, key)]
            found = [k for k in keys if k in masters]
            with_details = [k for k in found if needs_details is None or needs_details(DocumentRef(code, k))]
            sources = [DetailSource(link.entity, ctx.config.entity(link.entity), link.parent_key) for link in entity.details]
            details = self._store.load_details_many(uow, sources, with_details) if sources and with_details else {}
            for key in found:
                ref = DocumentRef(code, key)
                state.current[ref] = DocumentData(
                    ref=ref, master=masters[key],
                    details={s.entity_code: details[s.entity_code][key] for s in sources} if key in with_details else {})
                loaded.append(ref)
        return loaded


def candidate_of(state: CommandState, ref: DocumentRef) -> DocumentData | None:
    """这张单据的候选数据：第一次取时由加锁读到的当前值复制而来。"""
    if ref not in state.candidate and ref in state.current:
        state.candidate[ref] = copy.deepcopy(state.current[ref])
    return state.candidate.get(ref)
