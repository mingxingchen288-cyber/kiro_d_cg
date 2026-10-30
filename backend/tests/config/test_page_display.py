"""第 7 批页面显示（C06 v22、C05 v6）：seed 的成本核算页视图带出千分位、Lookup 显示列的标题和宽度、分类的可填写字典。

依据旧系统：cmx 列配置 `rulesConfig.useGrouping`（cost-pinggu 主表 20 列、原辅料和包材各 7 列，
`.reports/batch7-20261030/pg-page-display/q03-旧千分位列.out.txt`）；旧 Lookup 配置的 `displayColumns`（q02）；
PINGGU_CLASS 的 `tagSelectCellEditor`（选项 委托研发、委托转移、自主立项、平台业务）。
"""

from __future__ import annotations

from cost_platform.config.catalog import Catalog
from cost_platform.config.views import build_views
from cost_platform.contracts.types import LookupColumn, LookupConfig, PageView, dump_wire, parse_wire

from .support import draft, seed_drafts

MASTER_GROUPING = ["ANNUAL_QTY", "APEX_PL", "S_PERBACK", "X_PERBACK", "M_PERPACK", "TOTAL_FL", "TOTAL_BC", "TOTAL_YL", "TOTAL_COST",
                   "COST_PERBOX", "OUT_PRICE_RMB", "OUT_PRICE_F", "SALEMONEY", "JGF_BATCH", "COST_PERQP", "JGF_PERQP", "ML_PERQP",
                   "Y_JG_RE", "Y_ML", "Y_SALE"]
DETAIL_GROUPING = ["PER_HL", "EXADD_MATER", "BATCH_QTY", "SUQTY", "PRICE", "BASE_PRICE", "COST_BATCH"]


def _seed_view() -> PageView:
    role = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["*"]}}})
    views = build_views(Catalog({}).merged([*seed_drafts(), role]), 7, {})
    return views[("COST_PINGGU", "COST_ACCOUNTANT")]


def test_seed_grouping_follows_old_column_config() -> None:
    """千分位只在旧系统配了 useGrouping 的列上；序列化时只在为 true 时带 `grouping`。"""
    view = _seed_view()
    assert [f.name for f in view.master.fields if f.grouping] == MASTER_GROUPING
    assert [[f.name for f in d.fields if f.grouping] for d in view.details] == [DETAIL_GROUPING, DETAIL_GROUPING]
    wire = {f["name"]: f for f in dump_wire(PageView, view)["master"]["fields"]}
    assert wire["APEX_PL"]["grouping"] is True and "grouping" not in wire["P_PERPACK"] and "grouping" not in wire["MEMO"]


def test_seed_lookup_columns_carry_old_titles_and_widths() -> None:
    """产品 Lookup 的显示列按旧配置的顺序带出标题和宽度，没配宽度的不写；物料 Lookup 同样。"""
    view = _seed_view()
    goods = next(f for f in view.master.fields if f.name == "GOODSID").lookup
    assert goods is not None and goods.code == "costGoods"
    assert [(c.column, c.label, c.width) for c in goods.columns[:4]] == [
        ("GOODSID", "产品ID", 80), ("GOODSNAME", "产品名称", 200), ("MA_NO", "注册证号", None), ("APEX_PL", "批量", None)]
    material = next(f for f in view.details[0].fields if f.name == "GOODSID").lookup
    assert material is not None and [c.label for c in material.columns] == [
        "物料ID", "物料名称", "单价", "用途", "规格", "包装规格", "供应商", "质量标准", "英文名"]
    wire = next(f for f in dump_wire(PageView, view)["master"]["fields"] if f["name"] == "GOODSID")["lookup"]
    assert wire["columns"][:3] == [{"column": "GOODSID", "label": "产品ID", "width": 80},
                                   {"column": "GOODSNAME", "label": "产品名称", "width": 200},
                                   {"column": "MA_NO", "label": "注册证号"}]


def test_seed_pinggu_class_uses_free_text_dict() -> None:
    """分类：字典 pingguClass（四项，值与显示相同），可填写字典以外的值；其他字段没有 `dictFreeText`。"""
    view = _seed_view()
    fields = {f.name: f for f in view.master.fields}
    assert (fields["PINGGU_CLASS"].dict_type, fields["PINGGU_CLASS"].dict_free_text) == ("pingguClass", True)
    assert [n for n, f in fields.items() if f.dict_free_text] == ["PINGGU_CLASS"]
    wire = {f["name"]: f for f in dump_wire(PageView, view)["master"]["fields"]}
    assert wire["PINGGU_CLASS"]["dictFreeText"] is True and "dictFreeText" not in wire["MEMO"]
    pinggu_class = next(d for d in seed_drafts() if (d.type, d.key) == ("dict", "pingguClass")).content
    assert [(i["value"], i["label"]) for i in pinggu_class["items"]] == [
        ("委托研发", "委托研发"), ("委托转移", "委托转移"), ("自主立项", "自主立项"), ("平台业务", "平台业务")]


def test_lookup_columns_accept_names_and_objects() -> None:
    """`columns` 每项写列名或对象；列名按顺序取出，显示列的标题没写时为列名。"""
    config = parse_wire(LookupConfig, {"table": "V", "columns": ["A", {"column": "B", "label": "乙", "width": 80}, {"column": "C"}],
                                       "keywordColumns": ["A"]})
    assert config.column_names() == ["A", "B", "C"]
    assert config.display_columns() == [LookupColumn(column="A", label="A"), LookupColumn(column="B", label="乙", width=80),
                                        LookupColumn(column="C", label="C")]
