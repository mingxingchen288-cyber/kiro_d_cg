"""`RelatedQuery` 的契约测试（C08 第 9 节；查找方式见 C06 7.2，规则见 queries-export 的 QE-08）。

真实实现（queries-export）的测试继承 `RelatedQueryContract`，提供 `harness` fixture，实现 `RelatedQueryHarness`。
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import ExitStack
from decimal import Decimal
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeRelatedQuery, FakeUnitOfWorkFactory
from cost_platform.contracts.ports import RelatedQuery, UnitOfWork
from cost_platform.contracts.types import (
    DocumentData,
    DocumentRef,
    ErrorCode,
    PlatformError,
    RelationKeyFinder,
    Row,
    SqlFinder,
    TargetFinderConfig,
    TargetObject,
)

Case = tuple[TargetFinderConfig, DocumentData, list[TargetObject]]


class RelatedQueryHarness(Protocol):
    query: RelatedQuery
    uow: UnitOfWork

    def relation_key_case(self) -> Case:
        """按关联键查找（`rows` 为 `all`）：查找方式、来源单据和应找到的目标。"""
        ...

    def sql_case(self) -> Case:
        """按关联 SQL 查找：查找方式、来源单据和应找到的目标。"""
        ...

    def missing_record_key_case(self) -> tuple[SqlFinder, DocumentData]:
        """一个查出的行缺少 `recordKeyColumn` 的关联 SQL 和它的来源单据。"""
        ...


def _sorted(targets: list[TargetObject]) -> list[TargetObject]:
    return sorted(targets, key=lambda o: (o.entity, o.record_key, o.row_keys))


class RelatedQueryContract:
    @pytest.fixture
    def harness(self) -> RelatedQueryHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    @pytest.mark.parametrize("case_name", ["relation_key_case", "sql_case"])
    def test_finds_expected_targets(self, harness: RelatedQueryHarness, case_name: str) -> None:
        finder, source, expected = getattr(harness, case_name)()
        found = harness.query.find(harness.uow, finder, source)
        assert all(isinstance(o, TargetObject) for o in found)
        assert _sorted(found) == _sorted(expected)

    @pytest.mark.parametrize("case_name", ["relation_key_case", "sql_case"])
    def test_source_not_modified(self, harness: RelatedQueryHarness, case_name: str) -> None:
        finder, source, _ = getattr(harness, case_name)()
        before = copy.deepcopy(source)
        harness.query.find(harness.uow, finder, source)
        assert source == before

    def test_missing_record_key_fails_whole_query(self, harness: RelatedQueryHarness) -> None:
        """结果缺少 recordKeyColumn 时整个查找失败（500 INTERNAL_ERROR），不返回部分结果。"""
        finder, source = harness.missing_record_key_case()
        with pytest.raises(PlatformError) as caught:
            harness.query.find(harness.uow, finder, source)
        assert caught.value.code is ErrorCode.INTERNAL_ERROR


_SOURCE = DocumentData(
    ref=DocumentRef(entity="COST_PINGGU", record_key="1001"),
    master=Row(entity="COST_PINGGU", row_key="1001", client_row_id=None, values={"DOCID": Decimal("1001")}),
    details={"COST_MATERIAL": [
        Row(entity="COST_MATERIAL", row_key="5001", client_row_id=None, values={"GOODSID": Decimal("115"), "PRICE": Decimal("3.5")}),
        Row(entity="COST_MATERIAL", row_key="5002", client_row_id=None, values={"GOODSID": Decimal("116"), "PRICE": Decimal("1.2")}),
    ]},
)
_RELATION = RelationKeyFinder(kind="relationKey", entity="COST_GOODS_PRICE", target_key="GOODSID", source_key="COST_MATERIAL.GOODSID",
                              rows="all")
_SQL = SqlFinder(kind="sql", entity="COST_PINGGU", sql="SELECT M.DOCID AS DOC_ID, M.GOODSNAME AS PRODUCT_NAME FROM T_COST_PINGGU M "
                 "WHERE EXISTS (SELECT 1 FROM T_COST_PINGGU_DTL D WHERE D.DOCID = M.DOCID AND D.GOODSID = :goodsId)",
                 binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", label_column="PRODUCT_NAME",
                 display_columns=["DOC_ID", "PRODUCT_NAME"])
_GOODS = DocumentData(ref=DocumentRef(entity="COST_GOODS_PRICE", record_key="115"),
                      master=Row(entity="COST_GOODS_PRICE", row_key="115", client_row_id=None, values={"GOODSID": Decimal("115")}),
                      details={})


class FakeRelatedQueryHarness:
    def __init__(self) -> None:
        self._stack = ExitStack()
        self.uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())
        self.query = FakeRelatedQuery()
        self._relation = [TargetObject("COST_GOODS_PRICE", "115", (), {"GOODSID": Decimal("115")}),
                          TargetObject("COST_GOODS_PRICE", "116", (), {"GOODSID": Decimal("116")})]
        rows = [{"DOC_ID": Decimal("2001"), "PRODUCT_NAME": "甲"}, {"DOC_ID": Decimal("2002"), "PRODUCT_NAME": "乙"}]
        self._sql = [TargetObject("COST_PINGGU", "2001", (), rows[0]), TargetObject("COST_PINGGU", "2002", (), rows[1])]
        self.query.respond(_RELATION, self._relation, source=_SOURCE.ref)
        self.query.respond_rows(_SQL, rows, source=_GOODS.ref)
        self._missing = _SQL.model_copy(update={"sql": _SQL.sql.replace("M.DOCID AS DOC_ID, ", "")})
        self.query.respond_rows(self._missing, [rows[0], {"PRODUCT_NAME": "乙"}])

    def close(self) -> None:
        self._stack.close()

    def relation_key_case(self) -> Case:
        return _RELATION, copy.deepcopy(_SOURCE), list(self._relation)

    def sql_case(self) -> Case:
        return _SQL, copy.deepcopy(_GOODS), list(self._sql)

    def missing_record_key_case(self) -> tuple[SqlFinder, DocumentData]:
        return self._missing, copy.deepcopy(_GOODS)


class TestFakeRelatedQuery(RelatedQueryContract):
    @pytest.fixture
    def harness(self) -> Iterator[FakeRelatedQueryHarness]:
        harness = FakeRelatedQueryHarness()
        yield harness
        harness.close()


def test_fake_without_preset_finds_nothing() -> None:
    harness = FakeRelatedQueryHarness()
    assert harness.query.find(harness.uow, _RELATION, _GOODS) == []
    harness.close()
