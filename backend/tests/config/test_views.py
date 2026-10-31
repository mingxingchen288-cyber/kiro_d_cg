"""页面视图（CF-03、C05，T-CF-2、T-AZ-2）：三层叠加、可编辑与保存操作的 writableFields 取交集、内置按钮的
requiresSelection、按角色过滤按钮（新增、删除按区域授权）、区域的 canModify、新增和删除显示在页面配置放了它们的区域。"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from cost_platform.config.catalog import Catalog
from cost_platform.config.views import BUILTIN_REQUIRES_SELECTION, build_page_view, build_views, field_state
from cost_platform.contracts.types import (
    ConfigDraft,
    EntityConfig,
    EntityField,
    ErpRow,
    FieldFlags,
    FieldSetting,
    PackRef,
    PageView,
    dump_wire,
    parse_wire,
)

from .support import draft, seed_drafts

flags = st.none() | st.booleans()
layer = st.builds(FieldFlags, visible=flags, editable=flags, required=flags)
setting = st.builds(FieldSetting, visible=flags, editable=flags, required=flags)
field_strategy = st.builds(
    EntityField, name=st.just("F"), column=st.sampled_from(["F", None]), label=st.just("字段"),
    type=st.sampled_from(["text", "number"]), source=st.sampled_from(["erp", "own"]),
    role=st.sampled_from(["input", "calculated", "system"]))


@settings(max_examples=300, deadline=None)
@given(field=field_strategy, has_erp_row=st.booleans(), entity_layer=st.none() | layer, page_layer=st.none() | setting,
       role_layer=st.none() | layer)
def test_layers_only_tighten(field: EntityField, has_erp_row: bool, entity_layer: FieldFlags | None,
                             page_layer: FieldSetting | None, role_layer: FieldFlags | None) -> None:
    """基于属性的测试：任意实体、页面、角色设置叠加后，可见、可编辑不比上层宽，必填不比上层少；
    没有 erpRow 的实体，ERP 列始终只读。"""
    entity = EntityConfig(table="T", primary_key="ID", freezable=True, fields=[field],
                          erp_row=ErpRow(column="ISERP", value="1", local_value="0") if has_erp_row else None)
    top = field_state(field, entity, [entity_layer])
    mid = field_state(field, entity, [entity_layer, page_layer])
    low = field_state(field, entity, [entity_layer, page_layer, role_layer])
    for upper, lower in ((top, mid), (mid, low)):
        assert upper[0] or not lower[0]   # 可见不比上层宽
        assert upper[1] or not lower[1]   # 可编辑不比上层宽
        assert lower[2] or not upper[2]   # 必填不比上层少
    if field.source == "erp" and not has_erp_row:
        assert not low[1]
    if field.role != "input" or field.column is None:
        assert not low[1]


def _view(items: list[ConfigDraft], page: str, role: str) -> PageView:
    catalog = Catalog({}).merged(items)
    config = catalog.page(page)
    operation = catalog.operation(config.save_operation)
    return build_page_view(page, config, catalog.entities(), catalog.roles()[role], 7,
                           PackRef(pack_id=config.master.entity, version=5), operation.writable_fields)


def _with(items: list[ConfigDraft], config_type: str, key: str, content: dict[str, Any]) -> list[ConfigDraft]:
    return [d if (d.type, d.key) != (config_type, key) else draft(config_type, key, content, d.name) for d in items]


BUTTONS = [{"action": "addRow", "label": "新增"}, {"action": "copyRow", "label": "复制"}, {"action": "deleteRow", "label": "删除"},
           {"action": "syncPrice", "label": "同步价格", "operation": "COST_PINGGU.save", "requiresSelection": False},
           {"action": "saveGridConfig", "label": "保存列配置"}]


def _seed_with_buttons(role_buttons: list[str]) -> list[ConfigDraft]:
    items = seed_drafts()
    page = next(d for d in items if d.type == "page").content
    page = {**page, "master": {**page["master"], "buttons": BUTTONS},
            "details": [{**page["details"][0], "buttons": BUTTONS[:3]}, {**page["details"][1], "buttons": []}]}
    role = {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": role_buttons}}}
    return [*_with(items, "page", "COST_PINGGU", page), draft("role", "COST_ACCOUNTANT", role)]


def test_builtin_buttons_requires_selection() -> None:
    """CF-03：区域按钮中内置动作的 requiresSelection 按平台的表给出，业务按钮取页面配置的值；
    页面配置放了 addRow、deleteRow 的区域，区域按钮中有这两个按钮（C05：显示在放了它们的区域），没放的区域没有。"""
    view = _view(_seed_with_buttons(["*"]), "COST_PINGGU", "COST_ACCOUNTANT")
    master = [(b.key, b.action, b.operation, b.requires_selection) for b in view.master.buttons]
    assert master == [("master:addRow", "addRow", None, False),
                      ("master:copyRow", "copyRow", None, True),
                      ("master:deleteRow", "deleteRow", None, True),
                      ("master:syncPrice", "syncPrice", "COST_PINGGU.save", False),
                      ("master:saveGridConfig", "saveGridConfig", None, False)]
    assert [(b.key, b.requires_selection) for b in view.details[0].buttons] == [
        ("COST_MATERIAL:addRow", False), ("COST_MATERIAL:copyRow", True), ("COST_MATERIAL:deleteRow", True)]
    assert view.details[1].buttons == []
    assert view.system_buttons == ["save", "advancedSearch"]
    assert BUILTIN_REQUIRES_SELECTION == {"copyRow": True, "deleteRow": True, "addRow": False, "saveGridConfig": False}


def test_buttons_filtered_by_role() -> None:
    """按钮只留当前角色有权限的（C06 v24 第 8 节的权限键）：新增、删除也按区域，看 `<区域>:addRow`、`<区域>:deleteRow`；
    区域的 canModify 看 `<区域>:modify`；没有 system:save 时 systemButtons 中没有 save。"""
    view = _view(_seed_with_buttons(["master:copyRow", "COST_MATERIAL:addRow", "COST_MATERIAL:deleteRow", "COST_MATERIAL:modify",
                                     "system:advancedSearch"]), "COST_PINGGU", "COST_ACCOUNTANT")
    assert [b.key for b in view.master.buttons] == ["master:copyRow"]
    assert [b.key for b in view.details[0].buttons] == ["COST_MATERIAL:addRow", "COST_MATERIAL:deleteRow"]
    assert view.system_buttons == ["advancedSearch"]
    assert (view.master.can_modify, view.details[0].can_modify, view.details[1].can_modify) == (False, True, False)
    dumped = dump_wire(PageView, view)
    assert (dumped["master"]["canModify"], "canModify" in dumped["details"][0]) == (False, False)  # true 时省略（C05 v8）


def test_page_view_before_v8_still_parses() -> None:
    """v8 之前生成、还没重新生成的页面视图（systemButtons 带 addRow、deleteRow，区域没有 canModify）照样能读：
    区域按能修改读出。下次保存任何配置时 config 按新规则重新生成（CF-02）。"""
    view = _view(_seed_with_buttons(["*"]), "COST_PINGGU", "COST_ACCOUNTANT")
    old = dump_wire(PageView, view)
    old["systemButtons"] = ["save", "addRow", "deleteRow", "advancedSearch"]
    parsed = parse_wire(PageView, old)
    assert parsed.system_buttons == ["save", "addRow", "deleteRow", "advancedSearch"]
    assert parsed.master.can_modify is True and all(d.can_modify for d in parsed.details)


def test_editable_within_save_operation_writable_fields() -> None:
    """C05：页面视图的 editable 与页面保存操作的 writableFields 取交集。成本核算主表的备注（MEMO）三层都可编辑，
    从 COST_PINGGU.save 的 writableFields 中去掉后，页面视图（经 build_views，与保存时生成的相同）中只读，其他字段不变。"""
    items = seed_drafts()
    role = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["*"]}}})
    operation = next(d for d in items if (d.type, d.key) == ("operation", "COST_PINGGU.save")).content
    narrowed = {**operation["writableFields"], "COST_PINGGU": [n for n in operation["writableFields"]["COST_PINGGU"] if n != "MEMO"]}

    def editable(drafts: list[ConfigDraft]) -> dict[str, bool]:
        view = build_views(Catalog({}).merged([*drafts, role]), 7, {})[("COST_PINGGU", "COST_ACCOUNTANT")]
        return {f.name: f.editable for f in view.master.fields}

    before = editable(items)
    after = editable(_with(items, "operation", "COST_PINGGU.save", {**operation, "writableFields": narrowed}))
    assert before["MEMO"] is True and after["MEMO"] is False
    assert {n for n, e in after.items() if e} == {n for n, e in before.items() if e} - {"MEMO"}
    assert {n for n, e in before.items() if e} <= set(operation["writableFields"]["COST_PINGGU"])


def test_seed_page_view() -> None:
    """seed 的成本核算页：字段按三层叠加，`column` 为 null 的字段只读，明细区的 parentKey 取主表实体的 details。"""
    items = seed_drafts()
    role = {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {
        "buttons": ["system:save"], "columns": {"master": {"MEMO": {"required": True}, "PACKTYPE": {"editable": False}},
                                                "COST_MATERIAL": {"MEMO": {"visible": False}}}}}}
    view = _view([*items, draft("role", "COST_ACCOUNTANT", role)], "COST_PINGGU", "COST_ACCOUNTANT")
    fields = {f.name: f for f in view.master.fields}
    assert (fields["MEMO"].editable, fields["MEMO"].required) == (True, True)
    assert fields["PACKTYPE"].editable is False and fields["GOODSNAME"].editable is False  # 角色收紧、实体 fieldDefaults
    assert fields["TOTAL_COST"].calculated is True and fields["TOTAL_COST"].editable is False
    assert fields["DOCID"].pinned == "left" and fields["DOCID"].editable is False
    material = {f.name: f for f in view.details[0].fields}
    assert material["MEMO"].visible is False and material["MEMO"].editable is True
    assert material["GOODSNAME"].editable is False  # column 为 null
    assert (view.details[0].parent_key, view.details[0].primary_key) == ("DOCID", "DTLID")
    assert (view.rules_pack.pack_id, view.rules_pack.version, view.version) == ("COST_PINGGU", 5, 7)
    assert dump_wire(PageView, parse_wire(PageView, dump_wire(PageView, view))) == dump_wire(PageView, view)


PRODUCT_FILL = ["GOODSNAME", "STRENGTH", "MA_NO", "MAH", "CUSTOMNAME", "LIVERY", "GOODSNAME_EN"]
"""成本核算主表产品 Lookup（costGoods）回填目标中不可编辑的字段：旧系统 EDITABLE=0，随产品回填写库。"""


def test_seed_master_lookups_fill_writable() -> None:
    """按旧系统 cost-pinggu 的列配置：产品ID、客户ID 配 Lookup 后可编辑（迁移 MG-10，旧系统点单元格即打开 Lookup）；
    产品名称、规格等回填目标仍不可编辑，但 `fillWritable` 为 true（AZ-04 接受）；不是回填目标的项目号不是；
    明细的物料名称（column 为 null，只在视图中）不是。页面视图序列化时只在为 true 时带 `fillWritable`。
    币种（2026-10-31，旧列 FMNAME 的 Lookup formoney）配 Lookup 后可编辑，回填币种、汇率，两者本来可编辑，不是 `fillWritable`；
    状态（旧列 USESTATUS 的下拉）配字典 COST_PINGGU.USESTATUS。"""
    role = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["*"]}}})
    view = _view([*seed_drafts(), role], "COST_PINGGU", "COST_ACCOUNTANT")
    fields = {f.name: f for f in view.master.fields}
    assert fields["GOODSID"].editable and fields["GOODSID"].lookup is not None and fields["GOODSID"].lookup.code == "costGoods"
    assert fields["CUSTOMID"].editable and fields["CUSTOMID"].lookup is not None and fields["CUSTOMID"].lookup.code == "costCustomer"
    money = fields["FMNAME"].lookup
    assert fields["FMNAME"].editable and money is not None
    assert (money.code, money.fill) == ("formoney", {"FMNAME": "FMNAME", "FMRATE": "FMRATE"})
    assert fields["FMRATE"].editable and not fields["FMRATE"].fill_writable
    assert fields["USESTATUS"].dict_type == "COST_PINGGU.USESTATUS" and fields["USESTATUS"].editable
    business = fields["BUSINESS_USER"].lookup
    assert business is not None and (business.code, business.multiple, business.fill) == ("costUser", True, {"BUSINESS_USER": "REAL_NAME"})
    assert sorted(n for n, f in fields.items() if f.fill_writable) == sorted([*PRODUCT_FILL, "COUNTRY", "TRANPOSID"])
    assert all(not fields[n].editable for n in [*PRODUCT_FILL, "COUNTRY", "TRANPOSID"])
    assert not fields["PROJECTNO"].fill_writable and not fields["FMNAME"].fill_writable
    assert not fields["APEX_PL"].fill_writable and fields["APEX_PL"].editable  # 本来就可编辑的回填目标
    material = {f.name: f for f in view.details[0].fields}
    assert not material["GOODSNAME"].editable and not material["GOODSNAME"].fill_writable
    wire = {f["name"]: f for f in dump_wire(PageView, view)["master"]["fields"]}
    assert wire["GOODSNAME"]["fillWritable"] is True and "fillWritable" not in wire["MEMO"]


def test_fill_writable_follows_lookup_field_and_writable_fields() -> None:
    """产品ID 被角色设为不可编辑时，它的回填目标都不是 `fillWritable`（AZ-04 只接受可编辑字段的回填目标）；
    回填目标不在保存操作的 writableFields 中时也不是。"""
    items = seed_drafts()
    locked = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {
        "buttons": ["*"], "columns": {"master": {"GOODSID": {"editable": False}, "CUSTOMID": {"editable": False}}}}}})
    view = _view([*items, locked], "COST_PINGGU", "COST_ACCOUNTANT")
    assert [f.name for f in view.master.fields if f.fill_writable] == []
    operation = next(d for d in items if (d.type, d.key) == ("operation", "COST_PINGGU.save")).content
    narrowed = {**operation["writableFields"], "COST_PINGGU": [n for n in operation["writableFields"]["COST_PINGGU"] if n != "MAH"]}
    role = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["*"]}}})
    view = _view([*_with(items, "operation", "COST_PINGGU.save", {**operation, "writableFields": narrowed}), role],
                 "COST_PINGGU", "COST_ACCOUNTANT")
    fields = {f.name: f for f in view.master.fields}
    assert not fields["MAH"].fill_writable and fields["GOODSNAME"].fill_writable


def test_seed_page_view_summary_fields() -> None:
    """汇总行（C06 第 3 节 `aggregate`，由旧系统列配置 aggFunc: "sum" 推出）：seed 的成本核算页按 cmx 的 cost-pinggu 列配置，
    主表 14 个字段、原辅料和包材的 COST_BATCH 求和；页面视图带出 `aggregate`，没有设置的字段省略。"""
    role = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["*"]}}})
    view = _view([*seed_drafts(), role], "COST_PINGGU", "COST_ACCOUNTANT")
    assert [f.name for f in view.master.fields if f.aggregate == "sum"] == [
        "TOTAL_FL", "TOTAL_BC", "TOTAL_YL", "TOTAL_COST", "COST_PERBOX", "OUT_PRICE_RMB", "SALEMONEY", "JGF_BATCH", "COST_PERQP",
        "JGF_PERQP", "ML_PERQP", "Y_JG_RE", "Y_ML", "Y_SALE"]
    assert [[f.name for f in d.fields if f.aggregate == "sum"] for d in view.details] == [["COST_BATCH"], ["COST_BATCH"]]
    master = dump_wire(PageView, view)["master"]["fields"]
    assert next(f for f in master if f["name"] == "TOTAL_COST")["aggregate"] == "sum"
    assert "aggregate" not in next(f for f in master if f["name"] == "DOCID")


CF_FIELDS = {"FMNAME", "FMRATE", "USESTATUS"}
"""成本核算主表中归 CF 组改的字段：旧系统也勾了"查询"，第 7 批合并时随 CF 组的 seed 一起补，这里不要求。"""


def test_seed_page_view_searchable() -> None:
    """查询（C06 v23 第 3 节 `searchable`，由旧系统列配置的"查询"推出）：seed 按 cmx 的 cost-pinggu、goods-price-manage 列配置
    （.reports/batch7-20261030/qs-advanced-search/02-旧列查询标记.out.txt）。成本核算主表 43 个字段旧系统全勾，原辅料、包材
    各 18 个全勾；物料清单 9 个，单价 ZX_PRICE、ROW_CLASS_FLAG 不勾。角色隐藏的字段（主表备注）不带 `searchable`；
    序列化时只在为 true 时带。"""
    role = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {
        "COST_PINGGU": {"buttons": ["*"], "columns": {"master": {"MEMO": {"visible": False}}}},
        "GOODS_PRICE_MANAGE": {"buttons": ["*"]}}})
    items = [*seed_drafts(), role]
    view = _view(items, "COST_PINGGU", "COST_ACCOUNTANT")
    searchable = {f.name for f in view.master.fields if f.searchable}
    assert searchable >= {f.name for f in view.master.fields} - CF_FIELDS - {"MEMO"}
    assert "MEMO" not in searchable and {"GOODSNAME", "CUSTOMID", "DOCID"} <= searchable
    assert all(f.visible for f in view.master.fields if f.searchable)
    assert [[f.name for f in d.fields if f.searchable] for d in view.details] == [[f.name for f in d.fields] for d in view.details]
    assert [len(d.fields) for d in view.details] == [18, 18]
    wire = {f["name"]: f for f in dump_wire(PageView, view)["master"]["fields"]}
    assert wire["GOODSNAME"]["searchable"] is True and "searchable" not in wire["MEMO"]

    goods = _view(items, "GOODS_PRICE_MANAGE", "COST_ACCOUNTANT")
    assert [f.name for f in goods.master.fields if f.searchable] == [
        "GOODSID", "GOODSNAME", "PRICE", "USEFLAG", "GOODSTYPE", "PACKTYPE", "FACTORYNAME", "ISERP", "STANDARDTYPE"]


def test_erp_row_entity() -> None:
    """有 erpRow 的物料清单：ERP 列按页面设置可编辑（前端在 ERP 行上再显示为只读），erpRow.column 本身不可编辑。
    PRICE 同时列入保存操作的 writableFields（页面视图的 editable 与它取交集）。"""
    from .support import goods_price_items

    items = goods_price_items()
    page = {**next(d for d in items if d.type == "page").content}
    page["master"] = {**page["master"], "fields": {"PRICE": {"editable": True}}}
    operation = next(d for d in items if d.type == "operation").content
    operation = {**operation, "writableFields": {"COST_GOODS_PRICE": ["PRICE", "ZX_PRICE"]}}
    role = draft("role", "R", {"name": "R", "admin": False, "pages": {"GOODS_PRICE_MANAGE": {}}})
    items = _with(_with(items, "page", "GOODS_PRICE_MANAGE", page), "operation", "GOODS_PRICE_MANAGE.save", operation)
    view = _view([*items, role], "GOODS_PRICE_MANAGE", "R")
    fields = {f.name: f for f in view.master.fields}
    assert fields["PRICE"].editable is True and fields["PRICE"].source == "erp"
    assert fields["ISERP"].editable is False
    assert view.master.erp_row is not None and view.master.erp_row.column == "ISERP"
    assert view.system_buttons == [] and view.details == []


def test_field_default_and_compare_format() -> None:
    """CF-19（C05 v9）：页面视图的字段带出实体字段的 `default`（写法同 C06 第 2 节）和 `compare` 的显示方式 `format`；
    没有配置的字段省略这两项。例（E28、E29 的写法，配在成本核算主表上）：商务人员默认当前用户名，使用状态下拉"草稿、已提交"，
    总成本与另一个字段对比、只显示百分比。"""
    items = seed_drafts()
    entity = next(d for d in items if (d.type, d.key) == ("entity", "COST_PINGGU")).content
    extra = {"BUSINESS_USER": {"default": {"type": "builtin", "value": "currentUserName"}},
             "USESTATUS": {"default": {"type": "options", "value": ["草稿", "已提交"]}},
             "TOTAL_COST": {"compare": {"mode": "field", "field": "SALEMONEY", "format": "percent"}}}
    entity = {**entity, "fields": [{**f, **extra.get(f["name"], {})} for f in entity["fields"]]}
    role = draft("role", "COST_ACCOUNTANT", {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["*"]}}})
    view = _view([*_with(items, "entity", "COST_PINGGU", entity), role], "COST_PINGGU", "COST_ACCOUNTANT")
    wire = {f["name"]: f for f in dump_wire(PageView, view)["master"]["fields"]}
    assert wire["BUSINESS_USER"]["default"] == {"type": "builtin", "value": "currentUserName"}
    assert wire["USESTATUS"]["default"] == {"type": "options", "value": ["草稿", "已提交"]}
    assert wire["TOTAL_COST"]["compare"] == {"format": "percent"}
    assert "default" not in wire["DOCID"] and "compare" not in wire["DOCID"]
    assert parse_wire(PageView, dump_wire(PageView, view)) == view
