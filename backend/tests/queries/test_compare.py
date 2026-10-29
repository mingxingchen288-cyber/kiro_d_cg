"""T-QE-4：对比显示（QE-10，业务例子 E29）。"""

from __future__ import annotations

from decimal import Decimal

from cost_platform.contracts.fakes import FakePermissionChecker
from cost_platform.contracts.types import CompareResult, FieldCompare, ListRequest
from cost_platform.queries.compare import compare_result
from cost_platform.queries.lists import PageQueries

from .support import MATERIAL, PAGE, context, database, entities, snapshot


def test_e29_difference_and_percent() -> None:
    """E29：当前 3.80、历史 3.50：差值 0.30、百分比 8.57%；历史为 0 时只给差值；没有历史时都为空。"""
    assert compare_result(Decimal("3.80"), Decimal("3.50")) == CompareResult(value="3.50", diff="0.30", percent="8.57")
    assert compare_result(Decimal("3.80"), Decimal("0")) == CompareResult(value="0", diff="3.80", percent=None)
    assert compare_result(Decimal("3.80"), None) == CompareResult(value=None, diff=None, percent=None)
    assert compare_result(Decimal("2"), Decimal("3")) == CompareResult(value="3", diff="-1", percent="-33.33")


def test_query_mode_compares_with_history_view() -> None:
    """`query` 模式：按物料到历史价格表取对比值；单据加载的明细带对比结果，主表没有配置对比时不带。"""
    queries = PageQueries(database(), FakePermissionChecker())
    record = queries.record(context(snapshot(compare=True)), PAGE, "1001")
    assert record.master.compare is None
    compared = record.details[MATERIAL][0].compare
    assert compared is not None
    result = compared["PRICE"]
    assert (Decimal(str(result.value)), Decimal(str(result.diff)), result.percent) == (Decimal("3.5"), Decimal("0.3"), "8.57")

    zero = queries.record(context(snapshot(compare=True)), PAGE, "1004").details[MATERIAL][0].compare
    assert zero is not None and zero["PRICE"].value == "0" and Decimal(str(zero["PRICE"].diff)) == Decimal("9")
    assert zero["PRICE"].percent is None

    no_history = queries.record(context(snapshot(compare=True)), PAGE, "1002").details[MATERIAL]
    by_goods = {r.values["GOODSID"]: r.compare["PRICE"] for r in no_history if r.compare}
    assert by_goods["116"] == CompareResult(value=None, diff=None, percent=None)


def test_field_mode_compares_with_another_field_of_the_row() -> None:
    """`field` 模式：与同一行的上次单价对比，列表、按主键取行都带对比结果。"""
    configs = entities()
    material = configs[MATERIAL]
    fields = [f.model_copy(update={"compare": FieldCompare(mode="field", field="LAST_PRICE", format="both")})
              if f.name == "PRICE" else f for f in material.fields]
    snap = snapshot(configs={**configs, MATERIAL: material.model_copy(update={"fields": fields})})
    rows = PageQueries(database(), FakePermissionChecker()).record(context(snap), PAGE, "1002").details[MATERIAL]
    compared = {r.row_key: r.compare["PRICE"] for r in rows if r.compare}
    assert compared["5002"] == CompareResult(value="2", diff="0", percent="0.00")
    assert compared["5003"] == CompareResult(value="4", diff="1", percent="25.00")


def test_compare_is_not_added_without_config() -> None:
    rows = PageQueries(database(), FakePermissionChecker()).list(context(), PAGE, ListRequest(start_row=0, end_row=2)).rows
    assert all(r.compare is None for r in rows)
