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

    def sql_detail_bind_case(self) -> Case:
        """绑定变量引用明细字段的关联 SQL：查找方式、来源单据和应找到的目标（C08 第 9 节）。

        绑定变量引用一个明细的字段，还引用主表的字段；来源单据中这个明细至少两行，绑定的字段值各不相同。每行都能找到
        别的行找不到的对象；至少一个正常对象、一个 `missing` 对象被两行都找到；结果中至少两个 `record_key` 为空、
        `display` 不同的 `missing` 对象。
        """
        ...

    def missing_record_key_case(self) -> tuple[SqlFinder, DocumentData]:
        """一个查出的行缺少 `recordKeyColumn` 的关联 SQL 和它的来源单据。"""
        ...

    def missing_row_key_column_case(self) -> tuple[SqlFinder, DocumentData]:
        """`rowKeyColumns` 不为空、查出的行却缺少其中一列的关联 SQL 和它的来源单据（保存后表或视图变了）。"""
        ...

    def lost_record_case(self) -> Case:
        """查出的行中有主键为空的关联 SQL（例如明细还在、所属单据已被删除），它的来源单据和应找到的目标。

        `rowKeyColumns` 不为空，`labelColumn` 不在 `displayColumns` 中；结果中至少一行各列都有值，至少一行主键完整而
        `labelColumn` 为空，至少一行 `recordKeyColumn` 为空，至少一行 `recordKeyColumn` 有值而 `rowKeyColumns` 中的列为空。
        """
        ...


def _sorted(targets: list[TargetObject]) -> list[TargetObject]:
    return sorted(targets, key=lambda o: (o.entity, o.record_key or "", o.row_keys, o.missing, sorted(map(str, o.display.items()))))


def _ids(targets: list[TargetObject]) -> set[tuple[str, str | None, tuple[str, ...]]]:
    return {(o.entity, o.record_key, o.row_keys) for o in targets}


def _identity(o: TargetObject) -> tuple[object, ...]:
    """同一对象的判断（C08 第 9 节）：按实体和主键；`missing` 的对象按 `record_key` 和 `display`。"""
    if o.missing:
        return (o.entity, o.record_key, True, tuple(sorted(o.display.items())))
    return (o.entity, o.record_key, o.row_keys, False)


def _with_rows(source: DocumentData, entity: str, rows: list[Row]) -> DocumentData:
    """来源单据的副本，明细 `entity` 只留下 `rows`。"""
    reduced = copy.deepcopy(source)
    reduced.details[entity] = copy.deepcopy(rows)
    return reduced


def _with_source_rows(finder: RelationKeyFinder, source: DocumentData, rows: list[Row]) -> DocumentData:
    """来源单据的副本，`sourceKey` 所指明细只留下 `rows`。"""
    return _with_rows(source, finder.source_key.split(".", 1)[0], rows)


def _bound_entities(finder: SqlFinder) -> set[str]:
    return {ref.split(".", 1)[0] for ref in finder.binds.values()}


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

    def test_sql_detail_bind_runs_once_per_row(self, harness: RelatedQueryHarness) -> None:
        """绑定变量引用明细字段时，按传入单据中这个明细的每一行各执行一次，主表字段取主表的值，结果合并，同一对象只出现
        一次；`missing` 的对象按 record_key 和 display 判断是否相同；这个明细没有行时不执行（C08 第 9 节）。"""
        finder, source, expected = harness.sql_detail_bind_case()
        assert isinstance(finder, SqlFinder), "harness 的查找方式不符合要求"
        details = _bound_entities(finder) - {source.master.entity}
        assert len(details) == 1 and source.master.entity in _bound_entities(finder), "harness 的绑定变量不符合要求"
        entity = details.pop()
        rows = source.details.get(entity, [])
        assert len(rows) >= 2, "harness 的来源单据不符合要求"
        expected_ids = [_identity(o) for o in expected]
        assert len(set(expected_ids)) == len(expected_ids), "harness 的应找到的目标中有重复"
        lost = {_identity(o) for o in expected if o.missing and o.record_key is None}
        assert len(lost) >= 2, "harness 的结果中没有两个 record_key 为空、display 不同的 missing 对象"

        found = harness.query.find(harness.uow, finder, source)
        assert _sorted(found) == _sorted(expected)
        assert len({_identity(o) for o in found}) == len(found)

        per_row = [{_identity(o) for o in harness.query.find(harness.uow, finder, _with_rows(source, entity, [row]))} for row in rows]
        assert set().union(*per_row) == set(expected_ids)
        for i, ids in enumerate(per_row):
            others: set[tuple[object, ...]] = set().union(*(p for j, p in enumerate(per_row) if j != i))
            assert ids - others, f"第 {i + 1} 行没有找到别的行找不到的对象"
        shared = [o for o in expected if sum(_identity(o) in p for p in per_row) >= 2]
        assert any(not o.missing for o in shared) and any(o.missing for o in shared), "harness 中没有被两行都找到的正常对象和 missing 对象"
        assert harness.query.find(harness.uow, finder, _with_rows(source, entity, [])) == []

    @pytest.mark.parametrize("case_name", ["relation_key_case", "sql_case", "sql_detail_bind_case"])
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
        assert any(not o.missing and None not in o.display.values() for o in expected), "harness 的结果中没有各列都有值的行"
        assert any(not o.missing and o.display.get(finder.label_column) is None for o in expected), \
            "harness 的结果中没有主键完整而 labelColumn 为空的行：只有主键为空才是记录已不存在"
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
# 含某个物料的其他成本单（C06 7.7 样例三的 freeze）：物料编号取原辅料明细，排除来源单据自己取主表
_SQL_DETAIL = SqlFinder(kind="sql", entity="COST_PINGGU",
                        sql="SELECT M.DOCID AS DOC_ID, M.GOODSNAME AS PRODUCT_NAME FROM T_COST_PINGGU_DTL D "
                        "LEFT JOIN T_COST_PINGGU M ON M.DOCID = D.DOCID WHERE D.GOODSID = :goodsId AND D.DOCID <> :docId",
                        binds={"goodsId": "COST_MATERIAL.GOODSID", "docId": "COST_PINGGU.DOCID"}, record_key_column="DOC_ID",
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
        # 预设的四行：各列都有值；主键完整、产品名为空（照常返回）；成本单号为空（明细还在、所属成本单已被删除）；
        # 成本单号有值、明细主键为空
        lost_rows = [{"DOC_ID": Decimal("2001"), "DTL_ID": Decimal("5001"), "PRODUCT_NAME": "甲"},
                     {"DOC_ID": Decimal("2004"), "DTL_ID": Decimal("5009"), "PRODUCT_NAME": None},
                     {"DOC_ID": None, "DTL_ID": Decimal("5007"), "PRODUCT_NAME": None},
                     {"DOC_ID": Decimal("2003"), "DTL_ID": None, "PRODUCT_NAME": "丁"}]
        self._lost = _LOST
        self._lost_expected = [
            TargetObject("COST_PINGGU", "2001", ("5001",), {"DOC_ID": Decimal("2001"), "PRODUCT_NAME": "甲"}, False),
            TargetObject("COST_PINGGU", "2004", ("5009",), {"DOC_ID": Decimal("2004"), "PRODUCT_NAME": None}, False),
            TargetObject("COST_PINGGU", None, (), {"DOC_ID": None, "PRODUCT_NAME": None}, True),
            TargetObject("COST_PINGGU", "2003", (), {"DOC_ID": Decimal("2003"), "PRODUCT_NAME": "丁"}, True)]
        self.query.respond_rows(_LOST, lost_rows, source=_GOODS.ref)
        # 绑定明细字段：来源成本单 1001 的物料 115、116 各执行一次。2002 两种物料都有；"丙"是两次都查到的已删除成本单的明细
        doc = lambda key, name: {"DOC_ID": None if key is None else Decimal(key), "PRODUCT_NAME": name}  # noqa: E731
        self.query.respond_rows(_SQL_DETAIL, [doc("2001", "甲"), doc("2002", "乙"), doc(None, "丙")],
                                binds={"goodsId": Decimal("115"), "docId": Decimal("1001")})
        self.query.respond_rows(_SQL_DETAIL, [doc("2002", "乙"), doc("2003", "丁"), doc(None, "丙"), doc(None, "戊")],
                                binds={"goodsId": Decimal("116"), "docId": Decimal("1001")})
        self._detail_expected = [
            TargetObject("COST_PINGGU", "2001", (), doc("2001", "甲"), False),
            TargetObject("COST_PINGGU", "2002", (), doc("2002", "乙"), False),
            TargetObject("COST_PINGGU", "2003", (), doc("2003", "丁"), False),
            TargetObject("COST_PINGGU", None, (), doc(None, "丙"), True),
            TargetObject("COST_PINGGU", None, (), doc(None, "戊"), True)]

    def close(self) -> None:
        self._stack.close()

    def relation_key_case(self) -> Case:
        return _RELATION, copy.deepcopy(_SOURCE), list(self._relation)

    def sql_case(self) -> Case:
        return _SQL, copy.deepcopy(_GOODS), list(self._sql)

    def sql_detail_bind_case(self) -> Case:
        return _SQL_DETAIL, copy.deepcopy(_SOURCE), list(self._detail_expected)

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
