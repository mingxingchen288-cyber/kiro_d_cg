"""T-QE-2、T-QE-4：Lookup（QE-09、QE-11）和字典。"""

from __future__ import annotations

from typing import Any

import pytest

from cost_platform.contracts.types import DictConfig, ErrorCode, LookupConfig, LookupSearchRequest, PlatformError, parse_wire
from cost_platform.queries.catalog import ItemsCatalog
from cost_platform.queries.lookups import DictQueries, LookupQueries

from .support import context, database

CATALOG = ItemsCatalog(
    lookups={
        "GOODS": LookupConfig(table="T_COST_GOODS", columns=["GOODSID", "GOODSNAME", "GOODSTYPE"],
                              keyword_columns=["GOODSID", "GOODSNAME"], order_by="GOODSID"),
        "GOODS_PLAIN": LookupConfig(table="T_COST_GOODS", columns=["GOODSID", "GOODSNAME", "GOODSTYPE"], keyword_columns=[]),
    },
    dicts={"STATUS": DictConfig(items=[{"value": "0", "label": "停用", "order": 2}, {"value": "1", "label": "启用", "order": 1}])},
)


@pytest.fixture
def lookups() -> LookupQueries:
    return LookupQueries(database(), lambda ctx: CATALOG)


def search(lookups: LookupQueries, code: str, **body: Any) -> Any:
    return lookups.search(context(), code, parse_wire(LookupSearchRequest, {"startRow": 0, "endRow": 50, **body}))


def ids(result: Any) -> list[str]:
    return [r.values["GOODSID"] for r in result.rows]


def test_keyword_matches_keyword_columns(lookups: LookupQueries) -> None:
    """关键字去掉首尾空白后在 keywordColumns 中按包含匹配；返回 Lookup 的列和总数。"""
    result = search(lookups, "GOODS", keyword=" 胶 ")
    assert ids(result) == ["116", "118", "119"] and result.total == 3 and result.keyword_search is True
    assert result.rows[0].values == {"GOODSID": "116", "GOODSNAME": "胶囊壳", "GOODSTYPE": "瓶"}
    assert ids(search(lookups, "GOODS", keyword="11")) == ["115", "116", "117", "118", "119"]


def test_keyword_and_filter_with_paging(lookups: LookupQueries) -> None:
    """C09 第 4 节的样例：关键字"胶"、只查类型为"瓶"的物料。"""
    result = search(lookups, "GOODS", keyword="胶", filter={"column": "GOODSTYPE", "value": "瓶"})
    assert ids(result) == ["116", "118"] and result.total == 2
    page = search(lookups, "GOODS", startRow=1, endRow=3)
    assert ids(page) == ["116", "117"] and page.total == 5


def test_empty_filter_value_does_not_filter(lookups: LookupQueries) -> None:
    assert search(lookups, "GOODS", filter={"column": "GOODSTYPE", "value": None}).total == 5
    assert search(lookups, "GOODS", filter={"column": "GOODSTYPE", "value": ""}).total == 5


def test_filter_column_must_be_a_lookup_column(lookups: LookupQueries) -> None:
    """QE-11：`filter.column` 不是 Lookup 的列时返回 422。"""
    with pytest.raises(PlatformError) as caught:
        search(lookups, "GOODS", filter={"column": "PRICE", "value": "1"})
    assert caught.value.code is ErrorCode.VALIDATION_FAILED


def test_lookup_without_keyword_columns(lookups: LookupQueries) -> None:
    """QE-09：keywordColumns 为空时，只有空白的关键字照常按 filter 过滤并分页、返回总数，keywordSearch 为 false；
    非空关键字返回 400 INVALID_REQUEST。"""
    result = search(lookups, "GOODS_PLAIN", keyword="   ", filter={"column": "GOODSTYPE", "value": "袋"}, startRow=0, endRow=1)
    assert ids(result) == ["115"] and result.total == 2 and result.keyword_search is False
    assert search(lookups, "GOODS_PLAIN").total == 5
    with pytest.raises(PlatformError) as caught:
        search(lookups, "GOODS_PLAIN", keyword="胶")
    assert caught.value.code is ErrorCode.INVALID_REQUEST


def test_unknown_lookup_is_not_found(lookups: LookupQueries) -> None:
    with pytest.raises(PlatformError) as caught:
        search(lookups, "NOPE")
    assert caught.value.code is ErrorCode.NOT_FOUND


def test_dict_items_in_order() -> None:
    dicts = DictQueries(lambda ctx: CATALOG)
    assert [(i.value, i.label) for i in dicts.items(context(), "STATUS").items] == [("1", "启用"), ("0", "停用")]
    assert dicts.items(context(), "NOPE").items == []
