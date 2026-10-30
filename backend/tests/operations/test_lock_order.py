"""按钮找到别的单据时的加锁顺序（用户 2026-10-30 规则 3、4，模拟验证）。

成本核算的"同步单价"（测试里的按钮，d_cg 的种子配置中已去掉）：选中成本单 D（2550），`updateRecords` 按关联 SQL 找到含同一
物料的其他成本单 A（2551）、B（2552）、E（2553）的明细。找到的成本单与 D 同层（单据层），所以查找挪到加锁之前普通执行一次，
D 和找到的成本单按主键一次锁完（`ButtonInvolvedStage`）；展开动作时只认锁住的这一批。`FakeBusinessLocker` 按与真实实现
相同的规则检查顺序（排在已持有的锁之前时 500）。真实的 SQL 和并发见 write-pipeline 的 Oracle 测试。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cost_platform.contracts import types as t

from .support import (
    MASTER,
    MATERIAL,
    SYNC,
    A,
    B,
    Bench,
    D,
    E,
    command,
    cost_doc,
    detail_sql_finder,
    material,
    operation,
    ref,
    snapshot,
    writes,
)
from .test_actions import SYNC_DETAILS, preset_detail_rows

F = "2554"


def _bench() -> Bench:
    bench = Bench(snapshot({SYNC: operation([SYNC_DETAILS])}), locked=True)
    bench.docs[ref(F)] = cost_doc(F, [material("7101", F, 115, "60")])
    preset_detail_rows(bench)
    return bench


def _keys(targets: list[t.LockTarget]) -> list[str]:
    return [x.key for x in targets]


def test_same_layer_found_documents_locked_with_the_selected_one_before_any_action() -> None:
    """D 和找到的 A、B、E 在"确定涉及的单据"按主键一次锁完；动作轮次中不再追加加锁。"""
    bench = _bench()
    state = bench.run(command(SYNC, [(MASTER, D)]))
    assert bench.locks is not None
    assert [_keys(b) for b in bench.locks.batches if b] == [[D, A, B, E]]
    assert {i.document for i in bench.merged} == {ref(A), ref(B), ref(E)}
    assert state.involved[0] == ref(D)
    bench.close()


def test_documents_appearing_between_lookup_and_lock_are_not_counted() -> None:
    """范围查询和加锁之间，F（2554）也有了物料 115：它不在锁住的这一批中，不写，相当于那次修改发生在本命令之后。"""
    bench = _bench()
    finder = detail_sql_finder()

    def appear(_new: list[t.LockTarget]) -> None:
        bench.related.respond_rows(finder, [{"DOC_ID": Decimal(A), "DTL_ID": Decimal(6101)},
                                            {"DOC_ID": Decimal(E), "DTL_ID": Decimal(7001)},
                                            {"DOC_ID": Decimal(F), "DTL_ID": Decimal(7101)}],
                                   binds={"goodsId": Decimal(115), "docId": Decimal(D)})

    assert bench.locks is not None
    bench.locks.before_lock = appear
    bench.run(command(SYNC, [(MASTER, D)]))
    assert ref(F) not in {i.document for i in bench.merged}
    assert (A, MATERIAL, "6101", {"PRICE": Decimal(80)}) in writes(bench.merged)
    assert all(F not in _keys(b) for b in bench.locks.batches)
    bench.close()


def test_selected_document_changed_before_lock_rolls_back() -> None:
    """规则 4：查找用的是 D 加锁前的数据；锁住时 D 已被别人改了，抛 LockScopeChanged（编排回滚整个事务后重来）。"""
    bench = _bench()

    def changed(_new: list[t.LockTarget]) -> None:
        bench.docs[ref(D)].details[MATERIAL][0].values["PRICE"] = Decimal(81)

    assert bench.locks is not None
    bench.locks.before_lock = changed
    with pytest.raises(t.LockScopeChanged):
        bench.run(command(SYNC, [(MASTER, D)]))
    bench.close()
