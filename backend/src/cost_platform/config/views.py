"""按（页面、角色）生成页面视图（C05、CF-03）。

三层叠加：实体（`fieldDefaults`）→ 页面（主表区或明细区的 `fields`）→ 角色（`columns` 的 `master` 或明细实体）。
可见、可编辑只能收紧，必填只能增加。字段本身不能编辑的情况：`role` 不是 `input`（计算字段、系统字段）、`column` 为 null
（只在 readView 中）、没有 `erpRow` 的实体的 ERP 列、`erpRow.column` 本身（只由平台写，C06 第 2 节）。
可编辑再与页面保存操作的 `writableFields` 取交集（C05）：后端保存时按它拒绝（authz 的 `writable_fields`），
页面上显示能编辑的字段，保存时一定能写。不可编辑、但随可编辑字段的 Lookup 回填写库的字段标 `fillWritable`（C05）。

按钮：区域按钮按页面配置的顺序，只留当前角色有权限的：要 `*` 或权限键 `master:<动作>`、`<明细实体>:<动作>`，
新增、删除也一样按区域授权（C06 v24 第 8 节，用户 2026-10-30"控制到明细级别"）。`systemButtons` 只有 `save`、
`advancedSearch`。内置动作是否要求选中行按 CF-03 的表，业务动作取页面配置中的值。

修改：区域的 `canModify` 为角色有没有 `<区域>:modify`（C05 v8）。没有时前端把这个区域已经保存的行整行设为只读，
新增、复制出的行照常按 `editable` 填写；字段的 `editable` 不因此改变。后端按同一规则拒绝（authz 的 AZ-01）。
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from cost_platform.contracts.types import (
    ButtonConfig,
    EntityConfig,
    EntityField,
    FieldFlags,
    FieldSetting,
    LookupConfig,
    LookupSetting,
    PackRef,
    PageConfig,
    PageView,
    RoleConfig,
    RolePage,
    SystemButton,
    ViewButton,
    ViewDetail,
    ViewField,
    ViewLookup,
    ViewMaster,
)

from .catalog import Catalog

BUILTIN_REQUIRES_SELECTION: dict[str, bool] = {"copyRow": True, "deleteRow": True, "addRow": False, "saveGridConfig": False}
"""CF-03：内置按钮动作是否要求选中行，由平台统一规定，管理员不配置。"""

SYSTEM_BUTTONS: tuple[SystemButton, ...] = ("save", "advancedSearch")
MODIFY_ACTION = "modify"
"""区域的修改权限键 `<区域>:modify` 中的动作名（C06 第 8 节）；不是按钮。"""

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


def view_lookup(setting: LookupSetting | None, lookups: Mapping[str, LookupConfig]) -> ViewLookup | None:
    """页面配置的 Lookup 设置加上 Lookup 配置的显示列（C05 `lookup.columns`，标题没写时为列名）。"""
    if setting is None:
        return None
    lookup = lookups.get(setting.code)
    return ViewLookup(**dict(setting), columns=lookup.display_columns() if lookup is not None else [])


def _view_field(field: EntityField, entity: EntityConfig, setting: FieldSetting | None, role: FieldFlags | None,
                writable: Collection[str], lookups: Mapping[str, LookupConfig]) -> ViewField:
    visible, editable, required = field_state(field, entity, [entity.field_defaults.get(field.name), setting, role])
    return ViewField(
        name=field.name, label=field.label, type=field.type, scale=field.scale, source=field.source,
        calculated=field.role == "calculated", visible=visible, editable=editable and field.name in writable,
        required=required, width=setting.width if setting else None, pinned=setting.pinned if setting else None,
        dict_type=setting.dict_type if setting else None,
        lookup=view_lookup(setting.lookup if setting else None, lookups),
        aggregate=setting.aggregate if setting else None, grouping=field.grouping,
        dict_free_text=bool(setting and setting.dict_type and setting.dict_free_text),
    )


def _fields(entity: EntityConfig, settings: Mapping[str, FieldSetting], columns: Mapping[str, FieldFlags],
            writable: Collection[str], lookups: Mapping[str, LookupConfig]) -> list[ViewField]:
    """区域的字段。不可编辑的字段是本区域可编辑字段的 Lookup 回填目标、有写入列且在 `writableFields` 中时，
    `fillWritable` 为 true（与 authz AZ-04 接受的回填字段相同）：例如成本核算主表的产品名称不能直接填写，
    但随产品 Lookup 回填后要写库（旧系统 useLookupDialog.ts 回填不看目标列能否编辑，DynamicDataService 照样写入）。"""
    fields = [_view_field(f, entity, settings.get(f.name), columns.get(f.name), writable, lookups) for f in entity.fields]
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
        if not _allowed(grant, key):
            continue
        if button.action in BUILTIN_REQUIRES_SELECTION:
            requires, operation = BUILTIN_REQUIRES_SELECTION[button.action], None
        else:
            requires, operation = bool(button.requires_selection), button.operation
        result.append(ViewButton(key=key, action=button.action, label=button.label, operation=operation,
                                 requires_selection=requires))
    return result


def build_page_view(page_code: str, page: PageConfig, entities: Mapping[str, EntityConfig], role: RoleConfig,
                    version: int, pack: PackRef, writable_fields: Mapping[str, Sequence[str]], *,
                    lookups: Mapping[str, LookupConfig] | None = None) -> PageView:
    """角色在该页面的权限见 `role.pages[page_code]`；调用方已确认角色可以访问该页面。
    `writable_fields` 是页面保存操作（`page.save_operation`）的 `writableFields`；`lookups` 是全部 Lookup 配置，
    字段的 Lookup 从中带出显示列（没有给出时不带）。"""
    grant = role.pages[page_code]
    entity = entities[page.master.entity]
    lookups = lookups or {}
    master = ViewMaster(
        entity=page.master.entity, primary_key=entity.primary_key,
        fields=_fields(entity, page.master.fields, grant.columns.get("master", {}),
                       set(writable_fields.get(page.master.entity, ())), lookups),
        buttons=_buttons("master", page.master.buttons, grant), grid=page.master.grid,
        form_layout=page.master.form_layout, erp_row=entity.erp_row,
        can_modify=_allowed(grant, f"master:{MODIFY_ACTION}"),
    )
    parent_keys = {link.entity: link.parent_key for link in entity.details}
    details = []
    for area in page.details:
        detail = entities[area.entity]
        details.append(ViewDetail(
            entity=area.entity, title=area.title, primary_key=detail.primary_key, parent_key=parent_keys[area.entity],
            fields=_fields(detail, area.fields, grant.columns.get(area.entity, {}),
                           set(writable_fields.get(area.entity, ())), lookups),
            buttons=_buttons(area.entity, area.buttons, grant), grid=area.grid, form_layout=area.form_layout,
            erp_row=detail.erp_row, can_modify=_allowed(grant, f"{area.entity}:{MODIFY_ACTION}"),
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
    lookups: dict[str, LookupConfig] = catalog.of_type("lookup")
    views = {}
    for page_code, role_code in view_pairs(catalog):
        page = pages[page_code]
        pack = PackRef(pack_id=page.master.entity, version=pack_versions.get(page.master.entity, version))
        operation = catalog.operation(page.save_operation)
        writable = operation.writable_fields if operation is not None else {}
        views[(page_code, role_code)] = build_page_view(page_code, page, entities, roles[role_code], version, pack, writable,
                                                        lookups=lookups)
    return views
