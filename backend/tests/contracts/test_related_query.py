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
        """按关联键查找（`rows` 为 `all`）：查找方式、来源单据和应找到的目标。

        `sourceKey` 指向明细；来源单据中这个明细至少两行，键值各不相同，每行都能找到别的行找不到的目标。
        """
        ...

    def sql_case(self) -> Case:
        """按关联 SQL 查找：查找方式、来源单据和应找到的目标。"""
        ...

    def missing_record_key_case(self) -> tuple[SqlFinder, DocumentData]:
        """一个查出的行缺少 `recordKeyColumn` 的关联 SQL 和它的来源单据。"""
        ...

    def missing_row_key_column_case(self) -> tuple[SqlFinder, DocumentData]:
        """`rowKeyColumns` 不为空、查出的行却缺少其中一列的关联 SQL 和它的来源单据（保存后表或视图变了）。"""
        ...

    def lost_record_case(self) -> Case:
        """查出的行中有主键为空的关联 SQL（例如明细还在、所属单据已被删除），它的来源单据和应找到的目标。

        `rowKeyColumns` 不为空，`labelColumn` 不在 `displayColumns` 中；结果中至少一行完整，至少一行
        `recordKeyColumn` 为空，至少一行 `recordKeyColumn` 有值而 `rowKeyColumns` 中的列为空。
        """
        ...


def _sorted(targets: list[TargetObject]) -> list[TargetObject]:
    return sorted(targets, key=lambda o: (o.entity, o.record_key or "", o.row_keys, o.missing, sorted(map(str, o.display.items()))))


def _ids(targets: list[TargetObject]) -> set[tuple[str, str | None, tuple[str, ...]]]:
    return {(o.entity, o.record_key, o.row_keys) for o in targets}


def _with_source_rows(finder: RelationKeyFinder, source: DocumentData, rows: list[Row]) -> DocumentData:
    """来源单据的副本，`sourceKey` 所指明细只留下 `rows`。"""
    entity = finder.source_key.split(".", 1)[0]
    reduced = copy.deepcopy(source)
    reduced.details[entity] = copy.deepcopy(rows)
    return reduced


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
        assert not any(o.missing for o in found) and all(o.record_key is not None for o in found)

    def test_relation_key_uses_every_source_row(self, harness: RelatedQueryHarness) -> None:
        """按关联键时用传入单据中 sourceKey 所指实体的全部行：只留一行时找到的更少，一行都没有时找不到（C08 第 9 节）。"""
        finder, source, expected = harness.relation_key_case()
        assert isinstance(finder, RelationKeyFinder)
        entity = finder.source_key.split(".", 1)[0]
        assert entity != source.master.entity and len(source.details[entity]) >= 2, "harness 的来源单据不符合要求"
        first_only = harness.query.find(harness.uow, finder, _with_source_rows(finder, source, source.details[entity][:1]))
        assert first_only and _ids(first_only) < _ids(expected)
        assert harness.query.find(harness.uow, finder, _with_source_rows(finder, source, [])) == []

    def test_rows_changed_does_not_filter(self, harness: RelatedQueryHarness) -> None:
        """`rows` 为 changed 时，来源行由调用方准备，端口照常用传入的全部行查找。"""
        finder, source, expected = harness.relation_key_case()
        changed = finder.model_copy(update={"rows": "changed"})
        assert _sorted(harness.query.find(harness.uow, changed, source)) == _sorted(expected)

    @pytest.mark.parametrize("case_name", ["relation_key_case", "sql_case"])
    def test_source_not_modified(self, harness: RelatedQueryHarness, case_name: str) -> None:
        finder, source, _ = getattr(harness, case_name)()
        before = copy.deepcopy(source)
        harness.query.find(harness.uow, finder, source)
        assert source == before

    @pytest.mark.parametrize("case_name", ["missing_record_key_case", "missing_row_key_column_case"])
    def test_missing_key_column_fails_whole_query(self, harness: RelatedQueryHarness, case_name: str) -> None:
        """结果缺少 recordKeyColumn 或 rowKeyColumns 中的列时整个查找失败（500 INTERNAL_ERROR），不返回部分结果，
        也不当成记录已不存在（C08 第 9 节）。"""
        finder, source = getattr(harness, case_name)()
        if case_name == "missing_row_key_column_case":
            assert finder.row_key_columns, "harness 的查找方式不符合要求"
        with pytest.raises(PlatformError) as caught:
            harness.query.find(harness.uow, finder, source)
        assert caught.value.code is ErrorCode.INTERNAL_ERROR

    def test_lost_record_is_returned_as_missing(self, harness: RelatedQueryHarness) -> None:
        """主键为空的行返回为 missing 的对象，不报错，其余行照常返回（C08 第 9 节）。"""
        finder, source, expected = harness.lost_record_case()
        assert isinstance(finder, SqlFinder) and finder.row_key_columns, "harness 的查找方式不符合要求"
        assert finder.label_column is not None and finder.label_column not in finder.display_columns, "harness 的查找方式不符合要求"
        assert any(not o.missing for o in expected), "harness 的结果中没有完整的行"
        assert any(o.missing and o.record_key is None for o in expected), "harness 的结果中没有单据主键为空的行"
        assert any(o.missing and o.record_key is not None for o in expected), "harness 的结果中没有只有明细主键为空的行"
        found = harness.query.find(harness.uow, finder, source)
        assert _sorted(found) == _sorted(expected)
        for o in found:
            assert finder.label_column in o.display and set(finder.display_columns) <= set(o.display)
            if o.missing:
                assert o.row_keys == ()
            else:
                assert o.record_key is not None and len(o.row_keys) == len(finder.row_key_columns)


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
_LOST = SqlFinder(kind="sql", entity="COST_PINGGU",
                  sql="SELECT M.DOCID AS DOC_ID, D.DTLID AS DTL_ID, M.GOODSNAME AS PRODUCT_NAME FROM T_COST_PINGGU_DTL D "
                  "LEFT JOIN T_COST_PINGGU M ON M.DOCID = D.DOCID WHERE D.GOODSID = :goodsId",
                  binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", row_key_columns=["DTL_ID"],
                  label_column="PRODUCT_NAME", display_columns=["DOC_ID"])
_GOODS = DocumentData(ref=DocumentRef(entity="COST_GOODS_PRICE", record_key="115"),
                      master=Row(entity="COST_GOODS_PRICE", row_key="115", client_row_id=None, values={"GOODSID": Decimal("115")}),
                      details={})


class FakeRelatedQueryHarness:
    def __init__(self) -> None:
        self._stack = ExitStack()
        self.uow = self._stack.enter_context(FakeUnitOfWorkFactory().begin())
        self.query = FakeRelatedQuery()
        self._relation = [TargetObject("COST_GOODS_PRICE", "115", (), {"GOODSID": Decimal("115")}, False),
                          TargetObject("COST_GOODS_PRICE", "116", (), {"GOODSID": Decimal("116")}, False)]
        for target in self._relation:
            self.query.add_target("COST_GOODS_PRICE", "GOODSID", target.display["GOODSID"], target)
        rows = [{"DOC_ID": Decimal("2001"), "PRODUCT_NAME": "甲"}, {"DOC_ID": Decimal("2002"), "PRODUCT_NAME": "乙"}]
        self._sql = [TargetObject("COST_PINGGU", "2001", (), rows[0], False), TargetObject("COST_PINGGU", "2002", (), rows[1], False)]
        self.query.respond_rows(_SQL, rows, source=_GOODS.ref)
        self._missing = _SQL.model_copy(update={"sql": _SQL.sql.replace("M.DOCID AS DOC_ID, ", "")})
        self.query.respond_rows(self._missing, [rows[0], {"PRODUCT_NAME": "乙"}])
        self._missing_row_key = _SQL.model_copy(update={"sql": _SQL.sql + " AND 1 = 1", "row_key_columns": ["DTL_ID"]})
        self.query.respond_rows(self._missing_row_key, [{**rows[0], "DTL_ID": Decimal("5001")}, rows[1]])
        # 预设的三行：完整的一行；成本单号为空（明细还在、所属成本单已被删除）；成本单号有值、明细主键为空
        lost_rows = [{"DOC_ID": Decimal("2001"), "DTL_ID": Decimal("5001"), "PRODUCT_NAME": "甲"},
                     {"DOC_ID": None, "DTL_ID": Decimal("5007"), "PRODUCT_NAME": None},
                     {"DOC_ID": Decimal("2003"), "DTL_ID": None, "PRODUCT_NAME": "丁"}]
        self._lost = _LOST
        self._lost_expected = [
            TargetObject("COST_PINGGU", "2001", ("5001",), {"DOC_ID": Decimal("2001"), "PRODUCT_NAME": "甲"}, False),
            TargetObject("COST_PINGGU", None, (), {"DOC_ID": None, "PRODUCT_NAME": None}, True),
            TargetObject("COST_PINGGU", "2003", (), {"DOC_ID": Decimal("2003"), "PRODUCT_NAME": "丁"}, True)]
        self.query.respond_rows(_LOST, lost_rows, source=_GOODS.ref)

    def close(self) -> None:
        self._stack.close()

    def relation_key_case(self) -> Case:
        return _RELATION, copy.deepcopy(_SOURCE), list(self._relation)

    def sql_case(self) -> Case:
        return _SQL, copy.deepcopy(_GOODS), list(self._sql)

    def missing_record_key_case(self) -> tuple[SqlFinder, DocumentData]:
        return self._missing, copy.deepcopy(_GOODS)

    def missing_row_key_column_case(self) -> tuple[SqlFinder, DocumentData]:
        return self._missing_row_key, copy.deepcopy(_GOODS)

    def lost_record_case(self) -> Case:
        return self._lost, copy.deepcopy(_GOODS), list(self._lost_expected)


class TestFakeRelatedQuery(RelatedQueryContract):
    @pytest.fixture
    def harness(self) -> Iterator[FakeRelatedQueryHarness]:
        harness = FakeRelatedQueryHarness()
        yield harness
        harness.close()


# ---------------------------------------------------------------- 只针对替代实现

def test_fake_without_data_finds_nothing() -> None:
    harness = FakeRelatedQueryHarness()
    assert harness.query.find(harness.uow, _RELATION, _GOODS) == []
    harness.close()


def test_fake_relation_key_targets_exist() -> None:
    """替代实现：按关联键找到的对象都存在，登记 missing 的对象是准备数据的错误。"""
    harness = FakeRelatedQueryHarness()
    with pytest.raises(ValueError):
        harness.query.add_target("COST_GOODS_PRICE", "GOODSID", "117", TargetObject("COST_GOODS_PRICE", None, (), {}, True))
    harness.close()


def test_fake_records_source_as_received() -> None:
    """调用记录保存参数的副本：调用方之后修改传入的单据，记录不变。"""
    harness = FakeRelatedQueryHarness()
    source = copy.deepcopy(_SOURCE)
    harness.query.find(harness.uow, _RELATION, source)
    source.details["COST_MATERIAL"].clear()
    recorded = harness.query.calls_to("find")[0].args[2]
    assert len(recorded.details["COST_MATERIAL"]) == 2
    assert harness.query.calls_to("find")[0].args[0] is harness.uow
    harness.close()
