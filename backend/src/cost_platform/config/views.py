"""按（页面、角色）生成页面视图（C05、CF-03）。

三层叠加：实体（`fieldDefaults`）→ 页面（主表区或明细区的 `fields`）→ 角色（`columns` 的 `master` 或明细实体）。
可见、可编辑只能收紧，必填只能增加。字段本身不能编辑的情况：`role` 不是 `input`（计算字段、系统字段）、`column` 为 null
（只在 readView 中）、没有 `erpRow` 的实体的 ERP 列、`erpRow.column` 本身（只由平台写，C06 第 2 节）。
可编辑再与页面保存操作的 `writableFields` 取交集（C05）：后端保存时按它拒绝（authz 的 `writable_fields`），
页面上显示能编辑的字段，保存时一定能写。不可编辑、但随可编辑字段的 Lookup 回填写库的字段标 `fillWritable`（C05）。

按钮：区域按钮按页面配置的顺序，只留当前角色有权限的：`addRow`、`deleteRow` 是页面级按钮，要 `system:<动作>`
（同时列在 `systemButtons` 中），前端只在页面配置放了这两个按钮的区域显示它们（C05、frontend-page 的 FP-14）；
其他按钮要 `*` 或权限键 `master:<动作>`、`<明细实体>:<动作>`。内置动作是否要求选中行按 CF-03 的表，
业务动作取页面配置中的值。
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from cost_platform.contracts.types import (
    ButtonConfig,
    EntityConfig,
    EntityField,
    FieldFlags,
    FieldSetting,
    PackRef,
    PageConfig,
    PageView,
    RoleConfig,
    RolePage,
    SystemButton,
    ViewButton,
    ViewDetail,
    ViewField,
    ViewMaster,
)

from .catalog import Catalog

BUILTIN_REQUIRES_SELECTION: dict[str, bool] = {"copyRow": True, "deleteRow": True, "addRow": False, "saveGridConfig": False}
"""CF-03：内置按钮动作是否要求选中行，由平台统一规定，管理员不配置。"""

SYSTEM_BUTTONS: tuple[SystemButton, ...] = ("save", "addRow", "deleteRow", "advancedSearch")
PAGE_LEVEL_ACTIONS = frozenset({"addRow", "deleteRow"})

Layer = FieldFlags | FieldSetting | None


def _structural(field: EntityField, entity: EntityConfig) -> bool:
    """字段本身能不能写：只有 `role` 为 `input`、有写入列的字段，不含没有 `erpRow` 的实体的 ERP 列和 `erpRow.column`。"""
    return (field.role == "input" and field.column is not None
            and not (field.source == "erp" and entity.erp_row is None)
            and not (entity.erp_row is not None and field.name == entity.erp_row.column))


def field_state(field: EntityField, entity: EntityConfig, layers: Sequence[Layer]) -> tuple[bool, bool, bool]:
    """（可见、可编辑、必填）：各层叠加，可见、可编辑只能收紧，必填只能增加。"""
    visible = all(layer is None or layer.visible is not False for layer in layers)
    editable = _structural(field, entity) and all(layer is None or layer.editable is not False for layer in layers)
    required = any(layer is not None and layer.required is True for layer in layers)
    return visible, editable, required


def _view_field(field: EntityField, entity: EntityConfig, setting: FieldSetting | None, role: FieldFlags | None,
                writable: Collection[str]) -> ViewField:
    visible, editable, required = field_state(field, entity, [entity.field_defaults.get(field.name), setting, role])
    return ViewField(
        name=field.name, label=field.label, type=field.type, scale=field.scale, source=field.source,
        calculated=field.role == "calculated", visible=visible, editable=editable and field.name in writable,
        required=required, width=setting.width if setting else None, pinned=setting.pinned if setting else None,
        dict_type=setting.dict_type if setting else None, lookup=setting.lookup if setting else None,
        aggregate=setting.aggregate if setting else None,
    )


def _fields(entity: EntityConfig, settings: Mapping[str, FieldSetting], columns: Mapping[str, FieldFlags],
            writable: Collection[str]) -> list[ViewField]:
    """区域的字段。不可编辑的字段是本区域可编辑字段的 Lookup 回填目标、有写入列且在 `writableFields` 中时，
    `fillWritable` 为 true（与 authz AZ-04 接受的回填字段相同）：例如成本核算主表的产品名称不能直接填写，
    但随产品 Lookup 回填后要写库（旧系统 useLookupDialog.ts 回填不看目标列能否编辑，DynamicDataService 照样写入）。"""
    fields = [_view_field(f, entity, settings.get(f.name), columns.get(f.name), writable) for f in entity.fields]
    targets = {target for f in fields if f.editable and f.lookup is not None and f.lookup.fill_back for target in f.lookup.fill}
    own = {f.name: f for f in entity.fields}
    return [f.model_copy(update={"fill_writable": True})
            if not f.editable and f.name in targets and f.name in writable and _structural(own[f.name], entity) else f
            for f in fields]


def _allowed(grant: RolePage, key: str) -> bool:
    return "*" in grant.buttons or key in grant.buttons


def _buttons(region: str, buttons: Sequence[ButtonConfig], grant: RolePage) -> list[ViewButton]:
    result = []
    for button in buttons:
        key = f"{region}:{button.action}"
        permission = f"system:{button.action}" if button.action in PAGE_LEVEL_ACTIONS else key
        if not _allowed(grant, permission):
            continue
        if button.action in BUILTIN_REQUIRES_SELECTION:
            requires, operation = BUILTIN_REQUIRES_SELECTION[button.action], None
        else:
            requires, operation = bool(button.requires_selection), button.operation
        result.append(ViewButton(key=key, action=button.action, label=button.label, operation=operation,
                                 requires_selection=requires))
    return result


def build_page_view(page_code: str, page: PageConfig, entities: Mapping[str, EntityConfig], role: RoleConfig,
                    version: int, pack: PackRef, writable_fields: Mapping[str, Sequence[str]]) -> PageView:
    """角色在该页面的权限见 `role.pages[page_code]`；调用方已确认角色可以访问该页面。
    `writable_fields` 是页面保存操作（`page.save_operation`）的 `writableFields`。"""
    grant = role.pages[page_code]
    entity = entities[page.master.entity]
    master = ViewMaster(
        entity=page.master.entity, primary_key=entity.primary_key,
        fields=_fields(entity, page.master.fields, grant.columns.get("master", {}),
                       set(writable_fields.get(page.master.entity, ()))),
        buttons=_buttons("master", page.master.buttons, grant), grid=page.master.grid,
        form_layout=page.master.form_layout, erp_row=entity.erp_row,
    )
    parent_keys = {link.entity: link.parent_key for link in entity.details}
    details = []
    for area in page.details:
        detail = entities[area.entity]
        details.append(ViewDetail(
            entity=area.entity, title=area.title, primary_key=detail.primary_key, parent_key=parent_keys[area.entity],
            fields=_fields(detail, area.fields, grant.columns.get(area.entity, {}),
                           set(writable_fields.get(area.entity, ()))),
            buttons=_buttons(area.entity, area.buttons, grant), grid=area.grid, form_layout=area.form_layout,
            erp_row=detail.erp_row,
        ))
    return PageView(
        page_code=page_code, title=page.title, version=version, layout=page.layout, detail_mode=page.detail_mode,
        audit=page.audit, save_operation=page.save_operation, rules_pack=pack, master=master, details=details,
        system_buttons=[b for b in SYSTEM_BUTTONS if _allowed(grant, f"system:{b}")],
    )


def view_pairs(catalog: Catalog) -> list[tuple[str, str]]:
    """要生成页面视图的（页面、角色）：角色配置中有、配置中也存在的页面。"""
    pages = catalog.pages()
    return sorted((page, role) for role, config in catalog.roles().items() for page in config.pages if page in pages)


def build_views(catalog: Catalog, version: int, pack_versions: Mapping[str, int]) -> dict[tuple[str, str], PageView]:
    """全部页面视图；`version` 先填同一个值，由调用方按内容是否变化定下每个视图自己的版本。"""
    entities, pages, roles = catalog.entities(), catalog.pages(), catalog.roles()
    views = {}
    for page_code, role_code in view_pairs(catalog):
        page = pages[page_code]
        pack = PackRef(pack_id=page.master.entity, version=pack_versions.get(page.master.entity, version))
        operation = catalog.operation(page.save_operation)
        writable = operation.writable_fields if operation is not None else {}
        views[(page_code, role_code)] = build_page_view(page_code, page, entities, roles[role_code], version, pack, writable)
    return views
