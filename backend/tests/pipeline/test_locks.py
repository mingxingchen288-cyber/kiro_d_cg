"""统一加锁顺序（WP-03，用户 2026-10-30 同意"固定加锁层级"，模拟验证）：`locks.py` 的 `LockBook`、`PipelineLocks`，以及
加锁读取（`DocumentLoader`）、`TableWriter.lock_row` 共用同一份已持有的锁。

数据同 support.py：成本单 1001、1002（成本核算，有明细，单据层）；物料 115、116（物料清单，没有明细，基础数据层）。
`MemoryStore.lock_order` 按先后记下加上的每个行锁。真实 SQL 见 `test_document_store_sql.py`，Oracle 上的并发见
`test_oracle_lock_order.py`。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from cost_platform.contracts import types as t
from cost_platform.pipeline.loader import DocumentLoader
from cost_platform.pipeline.locks import LockBook, PipelineLocks
from cost_platform.pipeline.table_writer import OracleTableWriter

from ..contracts.test_business_locker import BusinessLockerContract
from .recording import RecordingUnitOfWork
from .support import GOODS, MASTER, MemoryStore, Setup, command, master_none, scales_inspector

DOC_1001, DOC_1002, GOODS_115 = t.DocumentRef(MASTER, "1001"), t.DocumentRef(MASTER, "1002"), t.DocumentRef(GOODS, "115")


class PipelineLocksHarness:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.locker = PipelineLocks(LockBook(), self.store, scales_inspector())  # type: ignore[arg-type]
        self.uow = RecordingUnitOfWork()
        self.ctx = Setup().context()
        self.first, self.second, self.base = DOC_1001, DOC_1002, GOODS_115

    def modify(self, ref: t.DocumentRef) -> None:
        self.store.rows[ref.entity][ref.record_key]["MEMO" if ref.entity == MASTER else "ZX_PRICE"] = "别人改了"


class TestPipelineLocks(BusinessLockerContract):
    @pytest.fixture
    def harness(self) -> Iterator[PipelineLocksHarness]:
        yield PipelineLocksHarness()


def _state(defer: bool = False) -> t.CommandState:
    return t.CommandState(command=command([master_none("1001", [])]), defer_lock=defer)


def test_loader_locks_in_unified_order_whatever_the_input_order() -> None:
    """一次锁成本单 1002、物料 115、成本单 1001：先单据层（按主键），后基础数据层，一行一个锁。"""
    store, setup = MemoryStore(), Setup()
    state = _state()
    DocumentLoader(store, setup.permission).lock(RecordingUnitOfWork(), state, setup.context(),  # type: ignore[arg-type]
                                                 [DOC_1002, GOODS_115, DOC_1001])
    assert store.lock_order == [("T_COST_PINGGU", "1001"), ("T_COST_PINGGU", "1002"), ("T_COST_GOODS", "115")]
    assert set(state.current) == {DOC_1001, DOC_1002, GOODS_115}


def test_loader_later_lock_must_sort_after_held() -> None:
    """往后找可以执行到一半再锁（成本单 → 物料清单）；反过来先锁物料清单、再锁成本单是实现错误，500。"""
    store, setup = MemoryStore(), Setup()
    uow, ctx = RecordingUnitOfWork(), setup.context()
    loader = DocumentLoader(store, setup.permission)
    loader.lock(uow, _state(), ctx, [DOC_1001])  # type: ignore[arg-type]
    loader.lock(uow, _state(), ctx, [GOODS_115])  # type: ignore[arg-type]
    other = RecordingUnitOfWork()
    loader.lock(other, _state(), ctx, [GOODS_115])  # type: ignore[arg-type]
    with pytest.raises(t.PlatformError) as caught:
        loader.lock(other, _state(), ctx, [DOC_1002])  # type: ignore[arg-type]
    assert caught.value.code is t.ErrorCode.INTERNAL_ERROR


def test_loader_relocks_documents_already_held() -> None:
    """审批处理已在"确定涉及的单据"锁住成本单 1001 和物料 115，加锁读取再锁 1001 一次并读出，不检查顺序。"""
    store, setup = MemoryStore(), Setup()
    uow, ctx, book = RecordingUnitOfWork(), setup.context(), LockBook()
    locks = PipelineLocks(book, store, scales_inspector())  # type: ignore[arg-type]
    locks.lock(uow, ctx, [locks.document(ctx, DOC_1001), locks.document(ctx, GOODS_115)])  # type: ignore[arg-type]
    state = _state()
    DocumentLoader(store, setup.permission, book).lock(uow, state, ctx, [DOC_1001])  # type: ignore[arg-type]
    assert DOC_1001 in state.current
    assert store.lock_order == [("T_COST_PINGGU", "1001"), ("T_COST_GOODS", "115"), ("T_COST_PINGGU", "1001")]


def test_lock_with_expected_reads_own_documents_in_the_lock_statements() -> None:
    """规则 3、4：物料清单改价要冻结成本单 1001，物料 115 推迟加锁、加锁前已普通读到。按统一顺序先锁 1001（只锁），再锁住
    115 并读出数据，用它核对；锁住后不再整批重读（原来多一次 `read_documents`）。"""
    store, setup = MemoryStore(), Setup()
    uow, ctx = RecordingUnitOfWork(), setup.context()
    locks = PipelineLocks(LockBook(), store, scales_inspector())  # type: ignore[arg-type]
    expected = locks.read(uow, ctx, [GOODS_115])  # type: ignore[arg-type]
    locks.lock(uow, ctx, [locks.document(ctx, GOODS_115), locks.document(ctx, DOC_1001)], expected)  # type: ignore[arg-type]
    assert store.lock_order == [("T_COST_PINGGU", "1001"), ("T_COST_GOODS", "115")]
    assert store.document_locks == [GOODS_115]
    assert store.document_reads == [[GOODS_115]]  # 只有加锁前的那一次


def test_lock_with_expected_changed_meanwhile_raises() -> None:
    """规则 4：加锁前读到物料 115 之后别人改了它，锁住并读出的数据与加锁前不同，抛 `LockScopeChanged`。"""
    store, setup = MemoryStore(), Setup()
    uow, ctx = RecordingUnitOfWork(), setup.context()
    locks = PipelineLocks(LockBook(), store, scales_inspector())  # type: ignore[arg-type]
    expected = locks.read(uow, ctx, [GOODS_115])  # type: ignore[arg-type]
    store.rows[GOODS]["115"]["ZX_PRICE"] = "别人改了"
    with pytest.raises(t.LockScopeChanged):
        locks.lock(uow, ctx, [locks.document(ctx, GOODS_115)], expected)  # type: ignore[arg-type]


def test_loader_defer_lock_reads_without_locking() -> None:
    """`defer_lock`（触发审批要往前冻结）：加锁读取只普通读取，不加锁，也不记为已持有。"""
    store, setup = MemoryStore(), Setup()
    uow, book = RecordingUnitOfWork(), LockBook()
    state = _state(defer=True)
    DocumentLoader(store, setup.permission, book).lock(uow, state, setup.context(), [GOODS_115])  # type: ignore[arg-type]
    assert GOODS_115 in state.current and store.lock_order == [] and book.held(uow) == frozenset()  # type: ignore[arg-type]


def test_table_writer_shares_the_order() -> None:
    """`TableWriter.lock_row` 纳入统一顺序：物料清单 T_COST_GOODS 115 已锁住时，再锁同一张表主键 25 的行是实现错误。"""
    book, uow = LockBook(), RecordingUnitOfWork()
    uow.connection.results = [[{"GOODSID": 116}]]
    writer = OracleTableWriter(5, scales_inspector(), book)
    store = MemoryStore()
    ctx = Setup().context()
    locks = PipelineLocks(book, store, scales_inspector())  # type: ignore[arg-type]
    locks.lock(uow, ctx, [locks.document(ctx, GOODS_115)])  # type: ignore[arg-type]
    assert writer.lock_row(uow, "T_COST_GOODS", "GOODSID", "116") is not None  # type: ignore[arg-type]
    with pytest.raises(t.PlatformError) as caught:
        writer.lock_row(uow, "T_COST_GOODS", "GOODSID", "25")  # type: ignore[arg-type]
    assert caught.value.code is t.ErrorCode.INTERNAL_ERROR
    assert uow.connection.sql == ["SELECT * FROM T_COST_GOODS WHERE GOODSID = :k FOR UPDATE WAIT 5"]
