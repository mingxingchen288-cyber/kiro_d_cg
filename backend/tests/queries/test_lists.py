"""T-QE-1 的模拟验证：列表、按主键取行和单据加载（QE-01–QE-05、QE-12，业务例子 E30）。

SQL 在 contracts 的 SQLite 替代事务上真实执行；权限、冻结和配置快照用 contracts 的替代实现。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from cost_platform.contracts.fakes import FakeFreezeReader, FakePermissionChecker
from cost_platform.contracts.types import (
    ByKeysRequest,
    ErrorCode,
    FreezeEntry,
    ListRequest,
    PlatformError,
    SqlCondition,
    parse_wire,
)
from cost_platform.queries.catalog import ItemsCatalog
from cost_platform.queries.lists import PageQueries

from .support import MASTER, MATERIAL, PAGE, context, database, keys


def request(**body: Any) -> ListRequest:
    return parse_wire(ListRequest, {"startRow": 0, "endRow": 100, **body})


@pytest.fixture
def permission() -> FakePermissionChecker:
    return FakePermissionChecker()


@pytest.fixture
def freeze() -> FakeFreezeReader:
    return FakeFreezeReader()


@pytest.fixture
def queries(permission: FakePermissionChecker, freeze: FakeFreezeReader) -> PageQueries:
    catalog = ItemsCatalog(sums={(PAGE, "master"): ["TOTAL_COST"]})
    return PageQueries(database(), permission, freeze=freeze, catalog=lambda ctx: catalog)


def test_assembly_constructor_still_works() -> None:
    """assembly 现在的用法：只传事务工厂和权限；没有汇总字段，冻结为空。"""
    result = PageQueries(database(), FakePermissionChecker()).list(context(), PAGE, request())
    assert result.total == 5 and result.aggregates == {} and all(r.frozen is None for r in result.rows)


def test_without_sort_rows_are_ordered_by_primary_key(queries: PageQueries) -> None:
    result = queries.list(context(), PAGE, request())
    assert keys(result.rows) == ["1001", "1002", "1003", "1004", "1005"]
    assert result.total == 5


def test_rows_contain_every_field_including_invisible(queries: PageQueries) -> None:
    """QE-02：返回的行包含实体的全部字段，不按可见性过滤（创建人对当前角色不可见）。"""
    row = queries.list(context(), PAGE, request()).rows[0]
    assert row.values == {"DOCID": "1001", "GOODSID": "900", "GOODSNAME": "胶囊A", "TOTAL_COST": "10.5", "MEMO": "甲",
                          "CREATE_BY": "zhang"}


def test_start_row_equal_to_total_returns_no_rows(queries: PageQueries) -> None:
    result = queries.list(context(), PAGE, request(startRow=5, endRow=10))
    assert result.rows == [] and result.total == 5


def test_paging_start_row_included_end_row_excluded(queries: PageQueries) -> None:
    assert keys(queries.list(context(), PAGE, request(startRow=1, endRow=3)).rows) == ["1002", "1003"]


def test_equal_sort_values_are_ordered_by_primary_key(queries: PageQueries) -> None:
    """QE-04：1001 和 1003 的总成本都是 10.5，按主键排在一起，翻页时不重复、不遗漏。"""
    not_blank = {"TOTAL_COST": {"filterType": "number", "type": "notBlank"}}
    asc = [{"colId": "TOTAL_COST", "sort": "asc"}]
    first = queries.list(context(), PAGE, request(startRow=0, endRow=2, sortModel=asc, filterModel=not_blank))
    second = queries.list(context(), PAGE, request(startRow=2, endRow=4, sortModel=asc, filterModel=not_blank))
    assert keys(first.rows) + keys(second.rows) == ["1004", "1001", "1003", "1002"]
    desc = queries.list(context(), PAGE, request(sortModel=[{"colId": "TOTAL_COST", "sort": "desc"}], filterModel=not_blank))
    assert keys(desc.rows) == ["1002", "1003", "1001", "1004"]


@pytest.mark.parametrize("body", [
    {"filterModel": {"CREATE_BY": {"filterType": "text", "type": "equals", "filter": "zhang"}}},
    {"filterModel": {"NOT_A_FIELD": {"filterType": "text", "type": "equals", "filter": "x"}}},
    {"sortModel": [{"colId": "CREATE_BY", "sort": "asc"}]},
    {"sortModel": [{"colId": "NOT_A_FIELD", "sort": "asc"}]},
    {"advanced": {"op": "and", "conditions": [{"field": "CREATE_BY", "operator": "=", "value": "zhang"}]}},
])
def test_invisible_or_unknown_field_is_rejected(queries: PageQueries, body: dict[str, Any]) -> None:
    """QE-02：筛选、排序和高级查询引用不可见或不存在的字段时为 422。"""
    with pytest.raises(PlatformError) as caught:
        queries.list(context(), PAGE, request(**body))
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert caught.value.details[0].field in ("CREATE_BY", "NOT_A_FIELD")


def test_row_permission_limits_list_and_record(queries: PageQueries, permission: FakePermissionChecker) -> None:
    """QE-01：行权限条件与筛选条件用 AND 组合；行权限范围外的单据按不存在处理。"""
    permission.set_rows(PAGE, MASTER, SqlCondition(sql="CREATE_BY = :rp_user", binds={"rp_user": "zhang"}))
    contains = {"GOODSNAME": {"filterType": "text", "type": "contains", "filter": "胶囊"}}
    result = queries.list(context(), PAGE, request(filterModel=contains))
    assert keys(result.rows) == ["1001", "1003"] and result.total == 2
    with pytest.raises(PlatformError) as caught:
        queries.record(context(), PAGE, "1002")
    assert caught.value.code is ErrorCode.NOT_FOUND
    assert queries.record(context(), PAGE, "1003").master.row_key == "1003"


def test_text_filters_ignore_case(queries: PageQueries) -> None:
    """与旧系统相同，文本列不区分大小写比较。"""
    def found(model: dict[str, Any]) -> list[str]:
        return keys(queries.list(context(), PAGE, request(filterModel={"GOODSNAME": model})).rows)

    assert found({"filterType": "text", "type": "contains", "filter": "胶囊"}) == ["1001", "1003", "1005"]
    assert found({"filterType": "text", "type": "startsWith", "filter": "GRANULE"}) == ["1004"]
    assert found({"filterType": "text", "type": "equals", "filter": "granule D"}) == ["1004"]
    assert found({"filterType": "text", "type": "notContains", "filter": "胶囊"}) == ["1002", "1004"]


def test_number_set_and_combined_filters(queries: PageQueries) -> None:
    def found(model: dict[str, Any]) -> list[str]:
        return keys(queries.list(context(), PAGE, request(filterModel=model)).rows)

    assert found({"TOTAL_COST": {"filterType": "number", "type": "inRange", "filter": 6, "filterTo": 20.25}}) == ["1001", "1002", "1003"]
    assert found({"TOTAL_COST": {"filterType": "number", "type": "greaterThan", "filter": 10.5}}) == ["1002"]
    assert found({"TOTAL_COST": {"filterType": "number", "type": "blank"}}) == ["1005"]
    assert found({"MEMO": {"filterType": "set", "values": ["甲", "丁"]}}) == ["1001", "1004"]
    either = {"filterType": "number", "operator": "OR",
              "conditions": [{"type": "equals", "filter": 5}, {"type": "equals", "filter": 20.25}]}
    assert found({"TOTAL_COST": either}) == ["1002", "1004"]
    both = {"GOODSNAME": {"filterType": "text", "type": "contains", "filter": "胶囊"},
            "TOTAL_COST": {"filterType": "number", "type": "lessThan", "filter": 11}}
    assert found(both) == ["1001", "1003"]


def test_e30_detail_conditions_are_met_by_the_same_detail_row(queries: PageQueries) -> None:
    """E30：原辅料明细的物料为 115 且价格大于 3：只查出有一条明细同时满足两个条件的成本单；1002 的一条明细是物料 115、
    价格 2，另一条是物料 116、价格 5，不出现（QE-12）。"""
    advanced = {"op": "and", "conditions": [
        {"entity": MATERIAL, "group": "g1", "field": "GOODSID", "operator": "=", "value": "115"},
        {"entity": MATERIAL, "group": "g1", "logic": "and", "field": "PRICE", "operator": ">", "value": "3"}]}
    result = queries.list(context(), PAGE, request(advanced=advanced))
    assert keys(result.rows) == ["1001", "1003"] and result.total == 2


def test_advanced_master_and_detail_conditions(queries: PageQueries) -> None:
    """C09 第 4 节的样例写法：主表条件和明细条件为且；同一明细的 OR 组也由同一条明细行满足。"""
    advanced = {"op": "and", "conditions": [
        {"field": "TOTAL_COST", "operator": ">=", "value": "10.5"},
        {"entity": MATERIAL, "group": "g1", "field": "GOODSID", "operator": "=", "value": "116"},
        {"entity": MATERIAL, "group": "g1", "logic": "or", "field": "PRICE", "operator": ">", "value": "3.6"}]}
    assert keys(queries.list(context(), PAGE, request(advanced=advanced)).rows) == ["1001", "1002", "1003"]
    old_style = {"op": "and", "conditions": [
        {"field": "GOODSNAME", "operator": "like", "value": "胶囊"},
        {"entity": MATERIAL, "field": "GOODSID", "operator": "in", "value": ["116", "117"]}]}
    assert keys(queries.list(context(), PAGE, request(advanced=old_style)).rows) == ["1003"]


def test_aggregates_cover_every_matching_row(queries: PageQueries) -> None:
    """QE-04：汇总对全部满足条件的行计算，不只是当前页。"""
    result = queries.list(context(), PAGE, request(startRow=0, endRow=1))
    assert len(result.rows) == 1 and result.total == 5
    assert Decimal(str(result.aggregates["TOTAL_COST"])) == Decimal("46.25")
    filtered = queries.list(context(), PAGE, request(filterModel={"GOODSNAME": {"filterType": "text", "type": "contains",
                                                                                "filter": "胶囊"}}))
    assert Decimal(str(filtered.aggregates["TOTAL_COST"])) == Decimal("21")


def test_frozen_rows_name_their_approval(queries: PageQueries, freeze: FakeFreezeReader) -> None:
    """QE-05：被冻结的单据标明被哪个审批冻结；单据加载时主表和全部明细都标为冻结。"""
    freeze.freeze(FreezeEntry(approval_id="203", table="T_COST_PINGGU", record_key="1003"))
    rows = queries.list(context(), PAGE, request()).rows
    assert {r.row_key: (r.frozen.approval_id if r.frozen else None) for r in rows} == {
        "1001": None, "1002": None, "1003": "203", "1004": None, "1005": None}
    record = queries.record(context(), PAGE, "1003")
    assert record.master.frozen is not None and record.master.frozen.approval_id == "203"
    assert [r.frozen.approval_id for r in record.details[MATERIAL] if r.frozen] == ["203", "203"]
    assert freeze.calls_to("find")[0].args[1] == "T_COST_PINGGU"


def test_record_loads_master_and_details_from_read_view(queries: PageQueries) -> None:
    """单据加载：明细经 readView 读取（物料名称只在视图中），按主键排序（QE-03）。"""
    record = queries.record(context(), PAGE, "1002")
    assert record.master.values["GOODSNAME"] == "片剂B"
    materials = record.details[MATERIAL]
    assert keys(materials) == ["5002", "5003"]
    assert [(r.values["GOODSID"], r.values["GOODSNAME"], r.values["PRICE"]) for r in materials] == [
        ("115", "硬脂酸镁", "2"), ("116", "胶囊壳", "5")]


def test_record_not_found(queries: PageQueries) -> None:
    with pytest.raises(PlatformError) as caught:
        queries.record(context(), PAGE, "9999")
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_rows_by_keys(queries: PageQueries, permission: FakePermissionChecker) -> None:
    """按主键取行：按请求顺序返回；不存在或超出行权限的行不返回；明细行随主表的行权限。"""
    found = queries.by_keys(context(), PAGE, ByKeysRequest(entity=MASTER, row_keys=["1003", "1001", "9999"]))
    assert keys(found.rows) == ["1003", "1001"]
    permission.set_rows(PAGE, MASTER, SqlCondition(sql="CREATE_BY = :rp_user", binds={"rp_user": "zhang"}))
    assert keys(queries.by_keys(context(), PAGE, ByKeysRequest(entity=MASTER, row_keys=["1002", "1003"])).rows) == ["1003"]
    details = queries.by_keys(context(), PAGE, ByKeysRequest(entity=MATERIAL, row_keys=["5003", "5001"])).rows
    assert keys(details) == ["5001"] and details[0].values["GOODSNAME"] == "硬脂酸镁"


def test_page_the_role_cannot_open() -> None:
    queries = PageQueries(database(), FakePermissionChecker())
    with pytest.raises(PlatformError) as caught:
        queries.list(context(), "OTHER_PAGE", request())
    assert caught.value.code is ErrorCode.PERMISSION_DENIED
