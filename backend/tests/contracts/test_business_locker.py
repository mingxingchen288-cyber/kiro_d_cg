"""`BusinessLocker` 的契约测试（C08 第 5b 节，用户 2026-10-30 同意"固定加锁层级"）。

真实实现（write-pipeline 的 `PipelineLocks`）的测试继承 `BusinessLockerContract`，提供 `harness` fixture，实现
`BusinessLockerHarness`：两张有明细的单据（单据层，`first` 的主键小于 `second`）、一张没有明细的单据（基础数据层），
以及在"加锁前读取"之后改一张单据的办法。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal
from typing import Protocol

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeBusinessLocker, FakeConfigSnapshot, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import BusinessLocker, UnitOfWork

D = Decimal


class BusinessLockerHarness(Protocol):
    locker: BusinessLocker
    uow: UnitOfWork
    ctx: t.ExecutionContext
    first: t.DocumentRef
    second: t.DocumentRef
    base: t.DocumentRef

    def modify(self, ref: t.DocumentRef) -> None:
        """别人改了这张单据的主表（已提交）。"""
        ...


class BusinessLockerContract:
    @pytest.fixture
    def harness(self) -> BusinessLockerHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_layers(self, harness: BusinessLockerHarness) -> None:
        """有 details 的主表实体为单据层，没有的为基础数据层，审批记录排在最前。"""
        h = harness
        assert h.locker.layer(h.ctx, h.first.entity) == "document"
        assert h.locker.layer(h.ctx, h.base.entity) == "base"
        assert h.locker.document(h.ctx, h.first).layer == "document"
        assert h.locker.document(h.ctx, h.base).layer == "base"
        assert h.locker.approval("203").layer == "approval"
        assert h.locker.row("T_NOT_REGISTERED", "ID", "1").layer == "base"

    def test_order_approval_document_base_then_key(self, harness: BusinessLockerHarness) -> None:
        h = harness
        targets = [h.locker.document(h.ctx, h.base), h.locker.document(h.ctx, h.second), h.locker.approval("9"),
                   h.locker.document(h.ctx, h.first)]
        ordered = sorted(targets, key=t.LockTarget.order)
        assert [x.layer for x in ordered] == ["approval", "document", "document", "base"]
        assert ordered[1].key == h.first.record_key and ordered[2].key == h.second.record_key

    def test_lock_once_in_any_input_order_then_held(self, harness: BusinessLockerHarness) -> None:
        h = harness
        targets = [h.locker.document(h.ctx, r) for r in (h.base, h.second, h.first)]
        h.locker.lock(h.uow, h.ctx, targets)
        assert h.locker.held(h.uow) == frozenset(targets)
        h.locker.lock(h.uow, h.ctx, targets[:1])  # 已持有的再锁不检查顺序

    def test_later_lock_must_sort_after_held(self, harness: BusinessLockerHarness) -> None:
        """往后找可以执行到一半再锁；排在已持有的锁之前时 500（违反加锁顺序）。"""
        h = harness
        h.locker.lock(h.uow, h.ctx, [h.locker.document(h.ctx, h.second)])
        h.locker.lock(h.uow, h.ctx, [h.locker.document(h.ctx, h.base)])
        with pytest.raises(t.PlatformError) as caught:
            h.locker.lock(h.uow, h.ctx, [h.locker.document(h.ctx, h.first)])
        assert caught.value.code is t.ErrorCode.INTERNAL_ERROR

    def test_read_then_lock_with_expected_unchanged(self, harness: BusinessLockerHarness) -> None:
        h = harness
        found = h.locker.read(h.uow, h.ctx, [h.first, h.base])
        assert set(found) == {h.first, h.base} and found[h.first].details
        h.locker.lock(h.uow, h.ctx, [h.locker.document(h.ctx, r) for r in (h.first, h.base)], found)

    def test_changed_between_read_and_lock_raises(self, harness: BusinessLockerHarness) -> None:
        """规则 4：锁住后核对，加锁前读到的本命令单据已被别人改了。"""
        h = harness
        found = h.locker.read(h.uow, h.ctx, [h.first])
        h.modify(h.first)
        with pytest.raises(t.LockScopeChanged):
            h.locker.lock(h.uow, h.ctx, [h.locker.document(h.ctx, h.first)], found)


# ---------------------------------------------------------------- 替代实现

def _field(name: str, type_: str = "number") -> t.EntityField:
    return t.parse_wire(t.EntityField, {"name": name, "column": name, "label": name, "type": type_, "source": "own",
                                        "role": "input"})


ENTITIES = {
    "DOC": t.EntityConfig(table="T_DOC", primary_key="DOCID", freezable=True, fields=[_field("DOCID"), _field("MEMO", "text")],
                          details=[t.DetailLink(entity="DTL", parent_key="DOCID")]),
    "DTL": t.EntityConfig(table="T_DTL", primary_key="DTLID", freezable=True, fields=[_field("DTLID"), _field("DOCID")]),
    "GOODS": t.EntityConfig(table="T_GOODS", primary_key="GOODSID", freezable=True, fields=[_field("GOODSID"), _field("PRICE")]),
}


def _doc(entity: str, key: str, **values: object) -> t.DocumentData:
    ref = t.DocumentRef(entity, key)
    details = {"DTL": [t.Row("DTL", "5001", None, {"DTLID": D(5001), "DOCID": D(key)})]} if entity == "DOC" else {}
    return t.DocumentData(ref, t.Row(entity, key, None, dict(values)), details)


class FakeBusinessLockerHarness:
    def __init__(self) -> None:
        self._stack = ExitStack()
        self.uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())
        self.first, self.second, self.base = t.DocumentRef("DOC", "2"), t.DocumentRef("DOC", "10"), t.DocumentRef("GOODS", "25")
        self.docs = {r: _doc(r.entity, r.record_key, MEMO=None) for r in (self.first, self.second, self.base)}
        self.locker = FakeBusinessLocker(self.docs.get)
        snapshot = FakeConfigSnapshot(version=1, role_code="R", role=t.RoleConfig(name="R", admin=False, pages={}),
                                      entities=ENTITIES)
        who = t.Identity(user_id="1", username="u1", display_name="张三", department_id=None, role_code="R", session_id="s")
        self.ctx = t.ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=who, config=snapshot,
                                      config_version=1, origin=t.Origin(kind="user", approval_id=None),
                                      now=datetime(2026, 10, 30, 9, 0))

    def modify(self, ref: t.DocumentRef) -> None:
        self.docs[ref].master.values["MEMO"] = "别人改了"

    def close(self) -> None:
        self._stack.close()


class TestFakeBusinessLocker(BusinessLockerContract):
    @pytest.fixture
    def harness(self) -> Iterator[FakeBusinessLockerHarness]:
        harness = FakeBusinessLockerHarness()
        yield harness
        harness.close()


def test_fake_records_batches_and_before_lock() -> None:
    """替代实现：`batches` 为每次新加的锁（已按顺序），`before_lock` 在真正加锁之前调用。"""
    h = FakeBusinessLockerHarness()
    seen: list[list[t.LockTarget]] = []
    h.locker.before_lock = seen.append
    targets = [h.locker.document(h.ctx, r) for r in (h.base, h.first)]
    h.locker.lock(h.uow, h.ctx, targets)
    h.locker.lock(h.uow, h.ctx, targets)
    assert h.locker.batches == [sorted(targets, key=t.LockTarget.order), []]
    assert seen == [sorted(targets, key=t.LockTarget.order)]
    h.close()
