"""write-pipeline 的 `CommandExecutor`、`BusinessLocker` 和管道阶段的替代实现（C08 第 5、5b、6 节）。"""

from __future__ import annotations

import copy
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from ..ports import UnitOfWork
from ..types import (
    Command,
    CommandResult,
    CommandState,
    DocumentData,
    DocumentRef,
    ErrorCode,
    ExecutionContext,
    LockLayer,
    LockScopeChanged,
    LockTarget,
    PlatformError,
)
from ._script import Scripted

Responder = Callable[[Command, ExecutionContext], CommandResult]


def unchanged(command: Command, ctx: ExecutionContext) -> CommandResult:
    """默认的结果：没有写入任何内容。"""
    return CommandResult(request_key=command.request_key, outcome="unchanged", rows=[], id_map={}, prompts=[], skipped=[],
                         approvals=[])


class FakeCommandExecutor(Scripted):
    """`CommandExecutor`：结果由 `respond` 给出，默认为 `unchanged`。

    按 C02 第 3 节判重：同一用户、同一请求键已完成且内容摘要相同时返回原结果，不再调用 `respond`；
    摘要不同时抛 422 IDEMPOTENCY_KEY_REUSED。执行失败（预设的错误，或 `respond` 抛出的 PlatformError）
    时不留下结果，同一请求键可以重新提交（write-pipeline 的 WP-02）。`executed` 记录真正执行过的命令。
    """

    scriptable = ('execute',)

    def __init__(self, respond: Responder = unchanged) -> None:
        super().__init__()
        self.respond = respond
        self._done: dict[tuple[str, str], tuple[str, CommandResult]] = {}
        self.executed: list[tuple[Command, ExecutionContext]] = []

    def execute(self, command: Command, ctx: ExecutionContext) -> CommandResult:
        self._record("execute", command, ctx)
        key = (ctx.identity.user_id, command.request_key)
        digest = command.content_digest()
        if key in self._done:
            done_digest, result = self._done[key]
            if done_digest != digest:
                raise PlatformError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "同一请求键提交了不同的内容")
            return result
        result = self.respond(command, ctx)
        self._done[key] = (digest, result)
        self.executed.append((command, ctx))
        return result


class FakeCommandMonitor(Scripted):
    """`CommandMonitor`：`watched` 按结束的先后记下（请求键、错误码），成功的命令错误码为 None，不是 PlatformError 的异常
    记为 INTERNAL_ERROR。异常照常抛出。"""

    scriptable = ('watch',)

    def __init__(self) -> None:
        super().__init__()
        self.watched: list[tuple[str, ErrorCode | None]] = []

    @contextmanager
    def watch(self, command: Command, ctx: ExecutionContext) -> Iterator[None]:
        self._record("watch", command, ctx)
        try:
            yield
        except PlatformError as error:
            self.watched.append((command.request_key, error.code))
            raise
        except BaseException:
            self.watched.append((command.request_key, ErrorCode.INTERNAL_ERROR))
            raise
        self.watched.append((command.request_key, None))


StageEffect = Callable[[UnitOfWork, CommandState, ExecutionContext], None]


class FakeStage(Scripted):
    """`PipelineStage`：`applies` 的结论和 `run` 对 `CommandState` 的修改由参数给出。

    `effect` 只应写 C08 第 6 节表中该阶段负责的字段；阶段失败时预设错误，例如
    `fail("run", PlatformError(ErrorCode.FROZEN_BY_APPROVAL, "单据已被冻结"))`。
    """

    scriptable = ('applies', 'run')

    def __init__(self, name: str, *, applies: bool | Callable[[CommandState, ExecutionContext], bool] = True,
                 effect: StageEffect | None = None) -> None:
        super().__init__()
        self.name = name
        self._applies = applies
        self._effect = effect

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        self._record("applies", state, ctx)
        return self._applies(state, ctx) if callable(self._applies) else self._applies

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        self._record("run", uow, state, ctx)
        if self._effect is not None:
            self._effect(uow, state, ctx)


DocumentSource = Callable[[DocumentRef], DocumentData | None]
"""按单据读出当前数据（主表和全部明细）；不存在时为 None。"""


def _numeric(key: str) -> bool:
    try:
        Decimal(key)
    except InvalidOperation:
        return False
    return True


def same_document(now: DocumentData | None, expected: DocumentData) -> bool:
    """锁住后重读的数据与加锁前读到的是否相同：比较主表和 `expected` 中读过的明细实体。"""
    if now is None or now.master != expected.master:
        return False
    return all(now.details.get(entity, []) == rows for entity, rows in expected.details.items())


class FakeBusinessLocker(Scripted):
    """`BusinessLocker`：不连数据库，按与真实实现相同的规则记下每个事务加锁的先后（C08 第 5b 节）。

    - `documents`：`read` 和 `expected` 核对时读单据当前数据的来源（例如测试中的内存业务表）；不给时 `read` 返回空，
      `expected` 中的单据都算已不存在；
    - `before_lock`：每次真正加锁之前调用，参数为这次新加的锁，测试用它模拟"加锁前读取和加锁之间别人改了单据"；
    - `acquired` 按先后记下加上的每个锁（所有事务），`batches` 为每次 `lock` 调用新加的锁。

    主键是否按数值比较：单据按主键字段的类型；没注册的表的行按主键文本是不是数字（真实实现取列的类型）。
    要锁的对象排在本事务已持有的锁之前时与真实实现一样抛 500 INTERNAL_ERROR；`expected` 与 `documents` 读到的不同时抛
    `LockScopeChanged`。"""

    scriptable = ('document', 'row', 'approval', 'layer', 'read', 'lock', 'held')

    def __init__(self, documents: DocumentSource | None = None, *,
                 before_lock: Callable[[list[LockTarget]], None] | None = None) -> None:
        super().__init__()
        self.documents = documents
        self.before_lock = before_lock
        self.acquired: list[LockTarget] = []
        self.batches: list[list[LockTarget]] = []
        self._held: weakref.WeakKeyDictionary[UnitOfWork, list[LockTarget]] = weakref.WeakKeyDictionary()

    def _layer(self, ctx: ExecutionContext, entity: str) -> LockLayer:
        return "document" if ctx.config.entity(entity).details else "base"

    def document(self, ctx: ExecutionContext, ref: DocumentRef) -> LockTarget:
        self._record("document", ctx, ref)
        entity = ctx.config.entity(ref.entity)
        pk = next(f for f in entity.fields if f.name == entity.primary_key)
        return LockTarget(self._layer(ctx, ref.entity), entity.table.upper(), str(pk.column or pk.name).upper(), ref.record_key,
                          pk.type == "number")

    def row(self, table: str, key_column: str, key: str) -> LockTarget:
        self._record("row", table, key_column, key)
        return LockTarget("base", table.upper(), key_column.upper(), key, _numeric(key))

    def approval(self, approval_id: str) -> LockTarget:
        self._record("approval", approval_id)
        return LockTarget("approval", "PF_APPROVAL", "APPROVAL_ID", approval_id, True)

    def layer(self, ctx: ExecutionContext, entity: str) -> LockLayer:
        self._record("layer", ctx, entity)
        return self._layer(ctx, entity)

    def read(self, uow: UnitOfWork, ctx: ExecutionContext, refs: list[DocumentRef]) -> dict[DocumentRef, DocumentData]:
        self._record("read", uow, ctx, refs)
        found = {ref: self.documents(ref) for ref in refs} if self.documents is not None else {}
        return {ref: copy.deepcopy(doc) for ref, doc in found.items() if doc is not None}

    def lock(self, uow: UnitOfWork, ctx: ExecutionContext, targets: list[LockTarget],
             expected: dict[DocumentRef, DocumentData] | None = None) -> None:
        self._record("lock", uow, ctx, targets, expected)
        held = self._held.setdefault(uow, [])
        new = sorted(set(targets) - set(held), key=LockTarget.order)
        if new and held:
            top = max(held, key=LockTarget.order)
            early = [t for t in new if t.order() < top.order()]
            if early:
                raise PlatformError(ErrorCode.INTERNAL_ERROR, f"加锁顺序错误：{early[0]} 排在已持有的 {top} 之前")
        if new and self.before_lock is not None:
            self.before_lock(new)
        held.extend(new)
        self.acquired.extend(new)
        self.batches.append(new)
        for ref, data in (expected or {}).items():
            now = self.documents(ref) if self.documents is not None else None
            if not same_document(now, data):
                raise LockScopeChanged(f"{ref.entity} {ref.record_key} 在加锁前读取之后被修改")

    def held(self, uow: UnitOfWork) -> frozenset[LockTarget]:
        self._record("held", uow)
        return frozenset(self._held.get(uow, []))
