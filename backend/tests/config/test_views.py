"""页面视图（CF-03、C05，T-CF-2）：三层叠加、可编辑与保存操作的 writableFields 取交集、内置按钮的 requiresSelection、
按角色过滤按钮、新增和删除显示在页面配置放了它们的区域。"""

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
    assert view.system_buttons == ["save", "addRow", "deleteRow", "advancedSearch"]
    assert BUILTIN_REQUIRES_SELECTION == {"copyRow": True, "deleteRow": True, "addRow": False, "saveGridConfig": False}


def test_buttons_filtered_by_role() -> None:
    """按钮只留当前角色有权限的（C06 第 8 节的权限键）：新增、删除看 system:addRow、system:deleteRow；
    没有 system:save 时 systemButtons 中没有 save。"""
    view = _view(_seed_with_buttons(["master:copyRow", "system:addRow", "COST_MATERIAL:copyRow"]), "COST_PINGGU", "COST_ACCOUNTANT")
    assert [b.key for b in view.master.buttons] == ["master:addRow", "master:copyRow"]
    assert [b.key for b in view.details[0].buttons] == ["COST_MATERIAL:addRow", "COST_MATERIAL:copyRow"]
    assert view.system_buttons == ["addRow"]


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
    assert fields["PACKTYPE"].editable is False and fields["GOODSID"].editable is False  # 角色收紧、实体 fieldDefaults
    assert fields["TOTAL_COST"].calculated is True and fields["TOTAL_COST"].editable is False
    assert fields["DOCID"].pinned == "left" and fields["DOCID"].editable is False
    material = {f.name: f for f in view.details[0].fields}
    assert material["MEMO"].visible is False and material["MEMO"].editable is True
    assert material["GOODSNAME"].editable is False  # column 为 null
    assert (view.details[0].parent_key, view.details[0].primary_key) == ("DOCID", "DTLID")
    assert (view.rules_pack.pack_id, view.rules_pack.version, view.version) == ("COST_PINGGU", 5, 7)
    assert dump_wire(PageView, parse_wire(PageView, dump_wire(PageView, view))) == dump_wire(PageView, view)


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
