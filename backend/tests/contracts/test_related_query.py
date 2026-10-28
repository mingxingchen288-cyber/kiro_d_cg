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
        """按只引用主表字段的关联 SQL 查找：查找方式、来源单据和应找到的目标，目标按 SQL 返回的顺序给出，至少两个。

        SQL 必须带 `ORDER BY`，使返回顺序确定（下面按顺序比较的用例都一样）。
        """
        ...

    def relation_key_detail_case(self) -> Case:
        """按关联键查找、`finder.entity` 为明细实体：查找方式、来源单据和应找到的目标（C08 第 9 节）。

        应找到的目标中至少有同一张单据的两行明细：`record_key` 都是所属单据的主键，`row_keys` 是各自明细的主键，
        明细主键与所属单据主键的值不同。
        """
        ...

    def sql_detail_bind_case(self) -> Case:
        """绑定变量引用明细字段的关联 SQL：查找方式、来源单据和应找到的目标，目标按应返回的顺序给出（C08 第 9 节）。
        SQL 必须带 `ORDER BY`。

        - 绑定变量引用一个明细的字段，还引用一个主表字段；这个主表字段在该明细的行中也有同名字段，值与主表不同。
        - 来源单据中这个明细至少两行，绑定的字段值各不相同；每行都能找到别的行找不到的对象。
        - 至少一个正常对象被两行都找到，两次查到的 `display` 不同（应保留先查到的）。
        - 同一次执行中，至少一个正常对象查出两次、两行的 `display` 不同（应保留第一行）；至少一个 `missing` 对象查出
          两次、`display` 相同（只算一个）。
        - 结果中至少两个 `record_key` 为空、`display` 不同的 `missing` 对象。
        - 数据能区分主表字段取主表还是取明细行的同名字段：把来源单据主表的这个字段换成明细行同名字段的值后，按这一行
          查找的结果不同。
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

        应找到的目标按 SQL 返回的顺序给出，SQL 必须带 `ORDER BY`。`finder.entity` 为明细实体，`rowKeyColumns` 不为空，
        `labelColumn` 和 `recordKeyColumn` 都不在 `displayColumns` 中；结果中至少一行各列都有值，至少一行主键完整而
        `labelColumn` 为空，至少一行 `recordKeyColumn` 为空，至少一行
        `recordKeyColumn` 有值而 `rowKeyColumns` 中的列为空。另外：同一张单据的两行明细（`record_key` 相同、`row_keys`
        不同）；两个 `display` 相同、`record_key` 不同且都不为空的 `missing` 对象；同一行查出两次（只算一个）。
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
        if case_name == "sql_case":
            assert len(expected) >= 2, "harness 的应找到的目标少于两个，检查不了顺序"
            assert found == expected  # 只引用主表字段的关联 SQL 执行一次，按 SQL 返回的顺序（C08 第 9 节）
        else:
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

    def test_relation_key_detail_entity(self, harness: RelatedQueryHarness) -> None:
        """`finder.entity` 为明细实体时，每行明细一个对象：`record_key` 为所属单据的主键，`row_keys` 为明细主键；
        同一张单据的几行明细是不同的对象（C08 第 9 节）。"""
        finder, source, expected = harness.relation_key_detail_case()
        assert isinstance(finder, RelationKeyFinder), "harness 的查找方式不符合要求"
        docs = [o.record_key for o in expected]
        assert any(docs.count(k) >= 2 for k in docs), "harness 的应找到的目标中没有同一张单据的两行明细"
        assert all(len(o.row_keys) == 1 and o.row_keys[0] != o.record_key for o in expected), "harness 的明细主键不符合要求"
        found = harness.query.find(harness.uow, finder, source)
        assert _sorted(found) == _sorted(expected)

    def test_sql_detail_bind_runs_once_per_row(self, harness: RelatedQueryHarness) -> None:
        """绑定变量引用明细字段时，按传入单据中这个明细的每一行各执行一次，主表字段取主表的值；结果按执行先后合并，
        同一对象只保留第一次出现的那一个，同一次执行查出的重复行也只算一个；这个明细没有行时不执行（C08 第 9 节）。"""
        finder, source, expected = harness.sql_detail_bind_case()
        assert isinstance(finder, SqlFinder), "harness 的查找方式不符合要求"
        master = source.master
        details = _bound_entities(finder) - {master.entity}
        assert len(details) == 1 and master.entity in _bound_entities(finder), "harness 的绑定变量不符合要求"
        entity = details.pop()
        rows = source.details.get(entity, [])
        assert len(rows) >= 2, "harness 的来源单据不符合要求"
        master_fields = [ref.split(".", 1)[1] for ref in finder.binds.values() if ref.split(".", 1)[0] == master.entity]
        assert any(all(r.values.get(f) is not None and r.values.get(f) != master.values.get(f) for r in rows) for f in master_fields), \
            "harness 的明细行中没有与绑定的主表字段同名而值不同的字段"
        expected_ids = [_identity(o) for o in expected]
        assert len(set(expected_ids)) == len(expected_ids), "harness 的应找到的目标中有重复"
        assert len({_identity(o) for o in expected if o.missing and o.record_key is None}) >= 2, \
            "harness 的结果中没有两个 record_key 为空、display 不同的 missing 对象"

        found = harness.query.find(harness.uow, finder, source)
        assert found == expected

        first = _with_rows(source, entity, rows[:1])
        swapped = copy.deepcopy(first)
        for f in master_fields:
            if f in rows[0].values:
                swapped.master.values[f] = rows[0].values[f]
        assert harness.query.find(harness.uow, finder, swapped) != harness.query.find(harness.uow, finder, first), \
            "主表字段取主表的值和取明细行同名字段的值，查找结果相同：harness 的数据区分不了，或实现取错了值"

        per_row = [harness.query.find(harness.uow, finder, _with_rows(source, entity, [row])) for row in rows]
        per_ids = [{_identity(o) for o in one} for one in per_row]
        assert all(len(ids) == len(one) for ids, one in zip(per_ids, per_row, strict=True)), "一次执行的结果中有重复的对象"
        assert set().union(*per_ids) == set(expected_ids)
        for i, ids in enumerate(per_ids):
            others: set[tuple[object, ...]] = set().union(*(p for j, p in enumerate(per_ids) if j != i))
            assert ids - others, f"第 {i + 1} 行没有找到别的行找不到的对象"
        displays: dict[tuple[object, ...], list[dict[str, object]]] = {}
        for one in per_row:
            for o in one:
                if not o.missing:
                    displays.setdefault(_identity(o), []).append(dict(o.display))
        assert any(len(ds) >= 2 and ds[0] != ds[1] for ds in displays.values()), \
            "harness 中没有被两行都找到、两次 display 不同的正常对象"
        assert harness.query.find(harness.uow, finder, _with_rows(source, entity, [])) == []

    @pytest.mark.parametrize("case_name", ["relation_key_case", "relation_key_detail_case", "sql_case", "sql_detail_bind_case"])
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
        assert finder.record_key_column not in finder.display_columns, "harness 的查找方式不符合要求"
        normal_docs = [o.record_key for o in expected if not o.missing]
        assert any(normal_docs.count(k) >= 2 for k in normal_docs), "harness 的结果中没有同一张单据的两行明细"
        keyed_lost = [o for o in expected if o.missing and o.record_key is not None]
        assert any(a.display == b.display and a.record_key != b.record_key for a in keyed_lost for b in keyed_lost), \
            "harness 的结果中没有 display 相同、record_key 不同的两个 missing 对象"
        found = harness.query.find(harness.uow, finder, source)
        assert found == expected
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
                 "WHERE EXISTS (SELECT 1 FROM T_COST_PINGGU_DTL D WHERE D.DOCID = M.DOCID AND D.GOODSID = :goodsId) "
                 "ORDER BY M.DOCID",
                 binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", label_column="PRODUCT_NAME",
                 display_columns=["DOC_ID", "PRODUCT_NAME"])
# 找原辅料明细（明细实体）：成本单已删除时 DOC_ID 为空，明细已删除时 DTL_ID 为空。替代实现的预设行不受 SQL 文本约束；
# 真实实现的 harness 要让同一行查出两次，需另写能查出重复行的 SQL（例如 UNION ALL）
_LOST = SqlFinder(kind="sql", entity="COST_MATERIAL",
                  sql="SELECT M.DOCID AS DOC_ID, D.DTLID AS DTL_ID, M.GOODSNAME AS PRODUCT_NAME FROM T_COST_PINGGU_DTL D "
                  "FULL JOIN T_COST_PINGGU M ON M.DOCID = D.DOCID WHERE D.GOODSID = :goodsId OR M.GOODSID = :goodsId "
                  "ORDER BY M.DOCID, D.DTLID",
                  binds={"goodsId": "COST_GOODS_PRICE.GOODSID"}, record_key_column="DOC_ID", row_key_columns=["DTL_ID"],
                  label_column="PRODUCT_NAME", display_columns=["DTL_ID"])
_RELATION_DETAIL = RelationKeyFinder(kind="relationKey", entity="COST_MATERIAL", target_key="GOODSID",
                                     source_key="COST_GOODS_PRICE.GOODSID", rows="all")
# 含某个物料、产品不同的成本单：物料编号取原辅料明细，产品取主表（主表和原辅料都有 GOODSID，值不同）；
# DTL_DOC 取明细一侧，所属成本单已被删除时仍有值。替代实现的预设行不受 SQL 文本约束；这条 SQL 每行明细最多查出一次，
# 真实实现的 harness 要让同一个 missing 对象在一次执行中出现两次，需另写能查出重复行的 SQL（例如 UNION ALL）
_SQL_DETAIL = SqlFinder(kind="sql", entity="COST_PINGGU",
                        sql="SELECT D.DOCID AS DTL_DOC, M.DOCID AS DOC_ID, D.GOODSID AS HIT, D.DTLID AS DTL_ID "
                        "FROM T_COST_PINGGU_DTL D LEFT JOIN T_COST_PINGGU M ON M.DOCID = D.DOCID "
                        "WHERE D.GOODSID = :goodsId AND NVL(M.GOODSID, 0) <> :productId ORDER BY D.DOCID, D.DTLID",
                        binds={"goodsId": "COST_MATERIAL.GOODSID", "productId": "COST_PINGGU.GOODSID"},
                        record_key_column="DOC_ID", label_column="DTL_DOC", display_columns=["HIT", "DTL_ID"])
_COST_DOC = DocumentData(
    ref=DocumentRef(entity="COST_PINGGU", record_key="1001"),
    master=Row(entity="COST_PINGGU", row_key="1001", client_row_id=None,
               values={"DOCID": Decimal("1001"), "GOODSID": Decimal("900")}),
    details={"COST_MATERIAL": [
        Row(entity="COST_MATERIAL", row_key="5001", client_row_id=None,
            values={"DOCID": Decimal("1001"), "GOODSID": Decimal("115"), "PRICE": Decimal("80")}),
        Row(entity="COST_MATERIAL", row_key="5002", client_row_id=None,
            values={"DOCID": Decimal("1001"), "GOODSID": Decimal("116"), "PRICE": Decimal("12")}),
    ]},
)
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
        self._missing_row_key = _SQL.model_copy(update={"sql": _SQL.sql.replace(" ORDER BY", " AND 1 = 1 ORDER BY"),
                                                        "row_key_columns": ["DTL_ID"]})
        self.query.respond_rows(self._missing_row_key, [{**rows[0], "DTL_ID": Decimal("5001")}, rows[1]])
        # 预设的七行：各列都有值（第一行查出两次）；同一张成本单的另一行明细；主键完整、产品名为空（照常返回）；
        # 成本单号为空（明细还在、所属成本单已被删除）；两张成本单号不同、明细主键为空、展示数据相同的行
        lost_row = lambda doc, dtl, name: {"DOC_ID": None if doc is None else Decimal(doc),  # noqa: E731
                                           "DTL_ID": None if dtl is None else Decimal(dtl), "PRODUCT_NAME": name}
        lost_rows = [lost_row("2001", "5001", "甲"), lost_row("2001", "5001", "甲"), lost_row("2001", "5002", "甲"),
                     lost_row("2004", "5009", None), lost_row(None, "5007", None), lost_row("2003", None, "丁"),
                     lost_row("2005", None, "丁")]
        lost_shown = lambda dtl, name: {"PRODUCT_NAME": name, "DTL_ID": None if dtl is None else Decimal(dtl)}  # noqa: E731
        self._lost = _LOST
        self._lost_expected = [
            TargetObject("COST_MATERIAL", "2001", ("5001",), lost_shown("5001", "甲"), False),
            TargetObject("COST_MATERIAL", "2001", ("5002",), lost_shown("5002", "甲"), False),
            TargetObject("COST_MATERIAL", "2004", ("5009",), lost_shown("5009", None), False),
            TargetObject("COST_MATERIAL", None, (), lost_shown("5007", None), True),
            TargetObject("COST_MATERIAL", "2003", (), lost_shown(None, "丁"), True),
            TargetObject("COST_MATERIAL", "2005", (), lost_shown(None, "丁"), True)]
        self.query.respond_rows(_LOST, lost_rows, source=_GOODS.ref)
        # 按关联键找原辅料明细：成本单 2001 有两行物料 115
        self._relation_detail = [TargetObject("COST_MATERIAL", "2001", ("6001",), {"GOODSID": Decimal("115")}, False),
                                 TargetObject("COST_MATERIAL", "2001", ("6003",), {"GOODSID": Decimal("115")}, False),
                                 TargetObject("COST_MATERIAL", "2002", ("6004",), {"GOODSID": Decimal("115")}, False)]
        for target in self._relation_detail:
            self.query.add_target("COST_MATERIAL", "GOODSID", Decimal("115"), target)
        # 绑定明细字段：来源成本单 1001（产品 900）的物料 115、116 各执行一次。2002 两种物料都有，两次的 HIT 不同；
        # 2003 有两行 116，在 116 那次查出两次、DTL_ID 不同；2008、2009 是已删除成本单留下的明细，2008 的同一行在
        # 115 那次查出两次
        hit = lambda dtl_doc, doc, goods, dtl: {  # noqa: E731
            "DTL_DOC": Decimal(dtl_doc), "DOC_ID": None if doc is None else Decimal(doc), "HIT": Decimal(goods), "DTL_ID": Decimal(dtl)}
        self.query.respond_rows(_SQL_DETAIL, [hit("2001", "2001", "115", "7001"), hit("2002", "2002", "115", "7002"),
                                              hit("2008", None, "115", "7008"), hit("2008", None, "115", "7008")],
                                binds={"goodsId": Decimal("115"), "productId": Decimal("900")})
        self.query.respond_rows(_SQL_DETAIL, [hit("2002", "2002", "116", "7003"), hit("2003", "2003", "116", "7004"),
                                              hit("2003", "2003", "116", "7005"), hit("2009", None, "116", "7009")],
                                binds={"goodsId": Decimal("116"), "productId": Decimal("900")})
        shown = lambda dtl_doc, goods, dtl: {"DTL_DOC": Decimal(dtl_doc), "HIT": Decimal(goods), "DTL_ID": Decimal(dtl)}  # noqa: E731
        self._detail_expected = [
            TargetObject("COST_PINGGU", "2001", (), shown("2001", "115", "7001"), False),
            TargetObject("COST_PINGGU", "2002", (), shown("2002", "115", "7002"), False),
            TargetObject("COST_PINGGU", None, (), shown("2008", "115", "7008"), True),
            TargetObject("COST_PINGGU", "2003", (), shown("2003", "116", "7004"), False),
            TargetObject("COST_PINGGU", None, (), shown("2009", "116", "7009"), True)]

    def close(self) -> None:
        self._stack.close()

    def relation_key_case(self) -> Case:
        return _RELATION, copy.deepcopy(_SOURCE), list(self._relation)

    def sql_case(self) -> Case:
        return _SQL, copy.deepcopy(_GOODS), list(self._sql)

    def relation_key_detail_case(self) -> Case:
        return _RELATION_DETAIL, copy.deepcopy(_GOODS), list(self._relation_detail)

    def sql_detail_bind_case(self) -> Case:
        return _SQL_DETAIL, copy.deepcopy(_COST_DOC), list(self._detail_expected)

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


def test_fake_binds_must_name_every_variable() -> None:
    """替代实现：按绑定值预设时必须正好给出全部绑定变量，漏写或多写是准备数据的错误，不能静默对不上。"""
    query = FakeRelatedQuery()
    with pytest.raises(ValueError):
        query.respond_rows(_SQL_DETAIL, [], binds={"goodsId": Decimal("115")})
    with pytest.raises(ValueError):
        query.respond_rows(_SQL_DETAIL, [], binds={"goodsId": Decimal("115"), "productId": Decimal("900"), "x": Decimal("1")})


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
