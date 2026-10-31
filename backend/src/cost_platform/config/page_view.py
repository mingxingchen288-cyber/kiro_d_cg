"""按（页面、角色）生成页面视图（C05）：实体、页面、角色三层叠加，可见和可编辑只能收紧，必填只能增加。"""

from __future__ import annotations

from collections.abc import Mapping

from cost_platform.contracts.types import (
    EntityConfig,
    EntityField,
    FieldFlags,
    FieldSetting,
    PackRef,
    PageConfig,
    PageView,
    RoleConfig,
    SystemButton,
    ViewDetail,
    ViewField,
    ViewMaster,
)

SYSTEM_BUTTONS: tuple[SystemButton, ...] = ("save", "addRow", "deleteRow", "advancedSearch")


def _view_field(field: EntityField, entity: EntityConfig, setting: FieldSetting | None, role: FieldFlags | None) -> ViewField:
    layers = [entity.field_defaults.get(field.name), setting, role]
    visible = all(layer is None or layer.visible is not False for layer in layers)
    # `column` 为 null 的字段只存在于 readView 中，只读显示（C06 第 2 节）
    editable = (field.role == "input" and field.column is not None
                and not (field.source == "erp" and entity.erp_row is None)
                and all(layer is None or layer.editable is not False for layer in layers))
    required = any(layer is not None and layer.required is True for layer in layers)
    return ViewField(
        name=field.name, label=field.label, type=field.type, scale=field.scale, source=field.source,
        calculated=field.role == "calculated", visible=visible, editable=editable, required=required,
        width=setting.width if setting else None, pinned=setting.pinned if setting else None,
        dict_type=setting.dict_type if setting else None, lookup=setting.lookup if setting else None,
        aggregate=setting.aggregate if setting else None, grouping=field.grouping,
        dict_free_text=bool(setting and setting.dict_type and setting.dict_free_text),
        searchable=visible and setting is not None and setting.searchable is True,
    )


def _fields(entity: EntityConfig, settings: Mapping[str, FieldSetting], columns: Mapping[str, FieldFlags]) -> list[ViewField]:
    return [_view_field(f, entity, settings.get(f.name), columns.get(f.name)) for f in entity.fields]


def build_page_view(page_code: str, page: PageConfig, entities: Mapping[str, EntityConfig], role: RoleConfig,
                    version: int) -> PageView:
    """角色在该页面的权限见 role.pages[page_code]；调用方已确认角色可以访问该页面。"""
    grant = role.pages[page_code]
    entity = entities[page.master.entity]
    allowed = set(grant.buttons)
    master = ViewMaster(
        entity=page.master.entity,
        primary_key=entity.primary_key,
        fields=_fields(entity, page.master.fields, grant.columns.get("master", {})),
        buttons=[],
        grid=page.master.grid,
        form_layout=page.master.form_layout,
        erp_row=entity.erp_row,
    )
    parent_keys = {link.entity: link.parent_key for link in entity.details}
    details = []
    for area in page.details:
        detail = entities[area.entity]
        details.append(ViewDetail(
            entity=area.entity, title=area.title, primary_key=detail.primary_key, parent_key=parent_keys[area.entity],
            fields=_fields(detail, area.fields, grant.columns.get(area.entity, {})), buttons=[], grid=area.grid,
            form_layout=area.form_layout, erp_row=detail.erp_row,
        ))
    return PageView(
        page_code=page_code, title=page.title, version=version, layout=page.layout, detail_mode=page.detail_mode,
        audit=page.audit, save_operation=page.save_operation, rules_pack=PackRef(pack_id=page_code, version=version),
        master=master, details=details,
        system_buttons=[b for b in SYSTEM_BUTTONS if ("*" in allowed or f"system:{b}" in allowed)
                        and not (b == "save" and page.save_operation is None)],  # 只读页面（C06 v30）
    )
