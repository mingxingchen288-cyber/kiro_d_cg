"""authz 测试用的配置样例：旧系统 cmx 中真实的角色权限，按 C06 第 8 节转换后的写法。

数据来源（只读查询，SQL 和结果在 `.reports/modules/authz/`）：
- 01、04：T_COST_ROLE_PAGE 中"技术中心"（ROLE_ID 101）、"001 海外营销中心-商业运营"（121）的按钮、行、列权限；
- 02：ADMIN（ROLE_ID 3）在 cost-pinggu 为 `["*"]`、没有行权限；cost-pinggu 的页面组件和按钮；
- 05：物料清单页 goods-price-manage 的列和 ERP 行规则（EDITABLE、APPROVAL_REQUIRED 按 ISERP）；
- 07：原辅料明细 GOODSID 的 Lookup 回填映射；
- 08：有技术中心角色的账号（没有同时有 001 的）；09：技术中心和 001 各自能访问的页面。

旧按钮键的分组换成区域编码（C06 第 8 节，分组取组件引用表的 TABLE_NAME，旧 RoleManageService.listPageButtons）：
"物料成本核算表"→`master`，"原辅料明细"→`COST_MATERIAL`，"包材明细"→`COST_PACKAGE`，"物料清单及成本"→`master`，
"系统默认按钮"→`system`，"自定义导出"→`export`。`approval.*` 不转换：审批不使用按钮权限（C06 第 8 节）。

页面视图正常由 config 按（页面、角色）生成；这里的 `page_view` 是测试用的简化生成：实体、页面、角色三层只收紧可见和
可编辑，区域按钮按角色的 `buttons` 过滤（C05）。实体、页面、保存操作取自种子配置 `backend/seed/config/`。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cost_platform.contracts.fakes import FakeConfigSnapshot
from cost_platform.contracts.types import (
    ButtonConfig,
    EntityConfig,
    ExecutionContext,
    FieldFlags,
    FieldSetting,
    GridOptions,
    Identity,
    LookupSetting,
    OperationConfig,
    Origin,
    PackRef,
    PageConfig,
    PageView,
    RoleConfig,
    ViewButton,
    ViewDetail,
    ViewField,
    ViewMaster,
    parse_config_content,
)

SEED = Path(__file__).resolve().parents[2] / "seed" / "config"

COST_PINGGU = "COST_PINGGU"
COST_MATERIAL = "COST_MATERIAL"
COST_PACKAGE = "COST_PACKAGE"
GOODS_PRICE_MANAGE = "GOODS_PRICE_MANAGE"
GOODS_MANAGE = "GOODS_MANAGE"
COST_GOODS_PRICE = "COST_GOODS_PRICE"
SAVE = "COST_PINGGU.save"
SYNC_PRICE = "COST_PINGGU.syncPrice"
GENERATE_FROM_BOM = "COST_PINGGU.generateFromBom"
GOODS_SAVE = "GOODS_PRICE_MANAGE.save"
EXPORT = "cost-pinggu-export"


def seed(type_: str, key: str) -> Any:
    item = json.loads((SEED / f"{type_}.{key}.json").read_text(encoding="utf-8"))
    return parse_config_content(type_, item["content"])


# ---------------------------------------------------------------- 角色（C06 第 8 节）

TECH_CENTER_PINGGU_BUTTONS = [
    # 旧 BUTTON_POLICY：["系统默认按钮:save","系统默认按钮:approval.apply","系统默认按钮:approval.cancel",
    # "系统默认按钮:approval.progress","系统默认按钮:advancedSearch","物料成本核算表:copyRow","物料成本核算表:generateFromBom",
    # "物料成本核算表:saveGridConfig","原辅料明细:copyRow","原辅料明细:saveGridConfig","包材明细:copyRow","包材明细:saveGridConfig"]
    "system:save", "system:advancedSearch",
    "master:copyRow", "master:generateFromBom", "master:saveGridConfig",
    "COST_MATERIAL:copyRow", "COST_MATERIAL:saveGridConfig",
    "COST_PACKAGE:copyRow", "COST_PACKAGE:saveGridConfig",
]

TECH_CENTER_ROWS = {
    # 旧 ROW_POLICY 原样（可视化写法）
    "mode": "visual", "logic": "OR",
    "conditions": [
        {"field": "USESTATUS", "fieldLabel": "状态", "op": "eq", "valueType": "static", "value": "评估中"},
        {"field": "USESTATUS", "fieldLabel": "状态", "op": "eq", "valueType": "static", "value": "已立项"},
    ],
    "sql": "USESTATUS = '评估中' OR USESTATUS = '已立项'",
}

TECH_CENTER_PINGGU_COLUMNS = {
    # 旧 COLUMN_POLICY 的 masterGrid、material、package 三组，按列名改写
    "master": {
        "ANNUAL_QTY": {"editable": False}, "P_PERPACK": {"editable": False}, "S_PERBACK": {"editable": False},
        "X_PERBACK": {"editable": False}, "TOTAL_YL": {"visible": False}, "TOTAL_FL": {"visible": False},
        "TOTAL_BC": {"visible": False}, "TOTAL_COST": {"visible": False}, "OUT_PRICE_RMB": {"visible": False},
        "SALEMONEY": {"visible": False}, "JGF_BATCH": {"visible": False}, "COST_PERQP": {"visible": False, "editable": False},
        "JGF_PERQP": {"visible": False}, "ML_PERQP": {"visible": False}, "Y_JG_RE": {"visible": False},
        "Y_ML": {"visible": False}, "Y_SALE": {"visible": False}, "FMRATE": {"editable": False},
        "COST_PERBOX": {"visible": False}, "USESTATUS": {"editable": False}, "OUT_PRICE_F": {"visible": False, "editable": False},
        "M_PERPACK": {"editable": False}, "PINGGU_CLASS": {"editable": False}, "BUSINESS_USER": {"editable": False},
    },
    "COST_MATERIAL": {"PRICE": {"visible": False, "editable": False}, "COST_BATCH": {"visible": False},
                      "BASE_PRICE": {"visible": False}},
    "COST_PACKAGE": {"PRICE": {"visible": False, "editable": False}, "COST_BATCH": {"visible": False},
                     "BASE_PRICE": {"visible": False}},
}

TECH_CENTER = {
    "name": "技术中心", "admin": False,
    "pages": {
        COST_PINGGU: {"buttons": TECH_CENTER_PINGGU_BUTTONS, "rows": TECH_CENTER_ROWS, "columns": TECH_CENTER_PINGGU_COLUMNS},
        GOODS_PRICE_MANAGE: {
            # 旧：["系统默认按钮:addRow","系统默认按钮:save",…审批三项…,"系统默认按钮:advancedSearch","物料清单及成本:copyRow",
            # "物料清单及成本:saveGridConfig"]；列权限 {"grid":{"1428":{"visible":false,"editable":false,"columnName":"PRICE"}}}
            "buttons": ["system:addRow", "system:save", "system:advancedSearch", "master:copyRow", "master:saveGridConfig"],
            "columns": {"master": {"PRICE": {"visible": False, "editable": False}}},
        },
    },
}

ROLE_001 = {
    "name": "海外营销中心-商业运营", "admin": False,
    "pages": {
        COST_PINGGU: {
            # 旧：["自定义导出:cost-pinggu-export","包材明细:copyRow","包材明细:saveGridConfig","原辅料明细:copyRow",
            # "原辅料明细:saveGridConfig","物料成本核算表:copyRow","物料成本核算表:generateFromBom","物料成本核算表:syncPrice",
            # "物料成本核算表:saveGridConfig","系统默认按钮:addRow","系统默认按钮:save",…审批三项…,"系统默认按钮:advancedSearch"]
            "buttons": ["export:cost-pinggu-export", "COST_PACKAGE:copyRow", "COST_PACKAGE:saveGridConfig",
                        "COST_MATERIAL:copyRow", "COST_MATERIAL:saveGridConfig", "master:copyRow", "master:generateFromBom",
                        "master:syncPrice", "master:saveGridConfig", "system:addRow", "system:save", "system:advancedSearch"],
            "rows": {"mode": "visual", "logic": "OR",
                     "conditions": [{"field": "USESTATUS", "fieldLabel": "状态", "op": "eq", "valueType": "static", "value": "商业化"}],
                     "sql": "USESTATUS = '商业化'"},
        },
        GOODS_MANAGE: {
            # 产品信息维护 goods-manage（09 查询）；技术中心没有这个页面。旧：["系统默认按钮:addRow","系统默认按钮:save",
            # …审批三项…,"系统默认按钮:advancedSearch","产品信息维护:copyRow","产品信息维护:saveGridConfig","系统默认按钮:deleteRow"]
            "buttons": ["system:addRow", "system:save", "system:advancedSearch", "master:copyRow", "master:saveGridConfig",
                        "system:deleteRow"],
        },
    },
}

ADMIN = {"name": "系统管理员", "admin": True, "pages": {COST_PINGGU: {"buttons": ["*"]}}}

ROLES = {"技术中心": TECH_CENTER, "001": ROLE_001, "ADMIN": ADMIN}


def role(code: str, **page_changes: dict[str, Any]) -> RoleConfig:
    """`ROLES` 中的角色；`page_changes` 按页面替换其中的项（只用于写明了原因的测试）。"""
    content = json.loads(json.dumps(ROLES[code]))
    for page, changes in page_changes.items():
        content["pages"][page] = {**content["pages"].get(page, {}), **changes}
    return parse_config_content("role", content)


# ---------------------------------------------------------------- 页面的区域按钮（旧 cost-pinggu 页面组件，02 查询）

PINGGU_AREA_BUTTONS = {
    "master": [ButtonConfig(action="copyRow", label="复制"),
               ButtonConfig(action="generateFromBom", label="由BOM生成明细", operation=GENERATE_FROM_BOM, requires_selection=True),
               ButtonConfig(action="syncPrice", label="同步采购价", operation=SYNC_PRICE, requires_selection=False),
               ButtonConfig(action="saveGridConfig", label="保存列配置")],
    COST_MATERIAL: [ButtonConfig(action="copyRow", label="明细复制"), ButtonConfig(action="saveGridConfig", label="保存列配置")],
    COST_PACKAGE: [ButtonConfig(action="copyRow", label="明细复制"), ButtonConfig(action="saveGridConfig", label="保存列配置")],
}

# 原辅料明细 GOODSID 的 Lookup（旧 RULES_CONFIG.cellEditorParams，07 查询）。旧列 EDITABLE=0 但配置了 Lookup，迁移按可编辑生成
# （MG-10）；FACTORYNAME、STANDARDTYPE、GOODSTYPE、GOODSNAME_EN 在旧系统是虚拟列（保存时跳过），回填映射中照样保留。
MATERIAL_LOOKUP = LookupSetting(code="COST_MATERIAL_EFFECTIVE", fill={
    "GOODSID": "GOODSID", "GOODSNAME": "GOODSNAME", "PRICE": "ZX_PRICE", "FACTORYNAME": "FACTORYNAME",
    "STANDARDTYPE": "STANDARDTYPE", "GOODSTYPE": "GOODSTYPE", "GOODSNAME_EN": "GOODSNAME_EN", "DTL_USEFLAG": "USEFLAG"})

_BUILTIN_SELECTION = {"copyRow": True, "deleteRow": True, "addRow": False, "saveGridConfig": False}  # config 的 CF-03
_GRID = GridOptions(side_bar=True, cell_selection=True, group_by=[])


# ---------------------------------------------------------------- 物料清单（05 查询）：有 erpRow 的实体

GOODS_ENTITY = parse_config_content("entity", {
    "table": "T_COST_GOODS", "primaryKey": "GOODSID", "freezable": True, "readView": "T_COST_GOODS_PRICE_V",
    # 旧 EDITABLE：ISERP ≠ 1 的行可编辑；APPROVAL_REQUIRED：ISERP = 1 的行只有 ZX_PRICE 可编辑，转为 erpRow（迁移 _erp_pattern）
    "erpRow": {"column": "ISERP", "value": "1", "localValue": "0"},
    "fields": [
        {"name": "GOODSID", "column": "GOODSID", "label": "物料ID", "type": "number", "scale": 0, "source": "own", "role": "system"},
        {"name": "GOODSNAME", "column": "GOODSNAME", "label": "物料名称", "type": "text", "source": "erp", "role": "input"},
        {"name": "PRICE", "column": "PRICE", "label": "参考价格", "type": "number", "source": "erp", "role": "input"},
        {"name": "USEFLAG", "column": "USEFLAG", "label": "用途", "type": "text", "source": "erp", "role": "input"},
        {"name": "GOODSTYPE", "column": "GOODSTYPE", "label": "规格", "type": "text", "source": "erp", "role": "input"},
        {"name": "PACKTYPE", "column": "PACKTYPE", "label": "包装规格", "type": "text", "source": "erp", "role": "input"},
        {"name": "FACTORYNAME", "column": "FACTORYNAME", "label": "供应商", "type": "text", "source": "erp", "role": "input"},
        {"name": "ISERP", "column": "ISERP", "label": "是否ERP", "type": "number", "scale": 0, "source": "own", "role": "input"},
        {"name": "STANDARDTYPE", "column": "STANDARDTYPE", "label": "质量标准", "type": "text", "source": "erp", "role": "input"},
        {"name": "ZX_PRICE", "column": "ZX_PRICE", "label": "单价", "type": "number", "source": "own", "role": "input"},
    ],
    # 旧列元数据 EDITABLE=0 的 ISERP；PRICE 旧 IS_VIRTUAL=1，保存时跳过，按不可编辑
    "fieldDefaults": {"ISERP": {"editable": False}, "PRICE": {"editable": False}},
})

GOODS_PAGE = parse_config_content("page", {
    "title": "物料清单及成本", "layout": "single", "detailMode": "tabs", "audit": True, "saveOperation": GOODS_SAVE,
    "master": {"entity": COST_GOODS_PRICE, "grid": {"sideBar": True, "cellSelection": True, "groupBy": []}},
})

GOODS_SAVE_OPERATION = parse_config_content("operation", {
    # 按 CF-14 生成：可输入、有列、没有设为不可编辑的字段，不含主键和 erpRow.column；有 erpRow，ERP 列照样列出
    "label": "保存", "kind": "save", "propagation": "continue", "impact": [COST_GOODS_PRICE],
    "writableFields": {COST_GOODS_PRICE: ["GOODSNAME", "USEFLAG", "GOODSTYPE", "PACKTYPE", "FACTORYNAME", "STANDARDTYPE", "ZX_PRICE"]},
})


# ---------------------------------------------------------------- 页面视图（简化生成，见模块说明）

def _layers(*settings: FieldFlags | FieldSetting | None) -> tuple[bool, bool, bool]:
    present = [s for s in settings if s is not None]
    return (all(s.visible is not False for s in present), all(s.editable is not False for s in present),
            any(s.required is True for s in present))


def _area_fields(entity: EntityConfig, page_fields: dict[str, FieldSetting], role_columns: dict[str, FieldFlags],
                 lookups: dict[str, LookupSetting]) -> list[ViewField]:
    out = []
    for f in entity.fields:
        setting = page_fields.get(f.name)
        visible, editable, required = _layers(entity.field_defaults.get(f.name), setting, role_columns.get(f.name))
        lookup = lookups.get(f.name) or (setting.lookup if setting else None)
        out.append(ViewField(name=f.name, label=f.label, type=f.type, scale=f.scale, source=f.source,
                             calculated=f.role == "calculated", visible=visible,
                             editable=editable and f.role == "input" and f.column is not None, required=required,
                             width=setting.width if setting else None, pinned=setting.pinned if setting else None,
                             dict_type=setting.dict_type if setting else None, lookup=lookup))
    return out


def page_view(page_code: str, page: PageConfig, entities: dict[str, EntityConfig], grant_role: RoleConfig,
              buttons: dict[str, list[ButtonConfig]] | None = None,
              lookups: dict[str, dict[str, LookupSetting]] | None = None) -> PageView:
    grant = grant_role.pages[page_code]
    allowed = set(grant.buttons)

    def permitted(key: str) -> bool:
        return "*" in allowed or key in allowed

    def area_buttons(region: str) -> list[ViewButton]:
        found = []
        for b in (buttons or {}).get(region, []):
            key = f"{region}:{b.action}"
            if permitted(key):
                selection = b.requires_selection if b.operation else _BUILTIN_SELECTION[b.action]
                found.append(ViewButton(key=key, action=b.action, label=b.label, operation=b.operation,
                                        requires_selection=bool(selection)))
        return found

    master_entity = entities[page.master.entity]
    master = ViewMaster(entity=page.master.entity, primary_key=master_entity.primary_key,
                        fields=_area_fields(master_entity, page.master.fields, grant.columns.get("master", {}),
                                            (lookups or {}).get("master", {})),
                        buttons=area_buttons("master"), grid=page.master.grid, form_layout=[],
                        erp_row=master_entity.erp_row)
    links = {link.entity: link.parent_key for link in master_entity.details}
    details = []
    for d in page.details:
        entity = entities[d.entity]
        details.append(ViewDetail(entity=d.entity, title=d.title, primary_key=entity.primary_key, parent_key=links[d.entity],
                                  fields=_area_fields(entity, d.fields, grant.columns.get(d.entity, {}),
                                                      (lookups or {}).get(d.entity, {})),
                                  buttons=area_buttons(d.entity), grid=d.grid or _GRID, form_layout=[],
                                  erp_row=entity.erp_row))
    system = [b for b in ("save", "addRow", "deleteRow", "advancedSearch") if permitted(f"system:{b}")]
    return PageView(page_code=page_code, title=page.title, version=1, layout=page.layout, detail_mode=page.detail_mode,
                    audit=page.audit, save_operation=page.save_operation, rules_pack=PackRef(pack_id=page_code, version=1),
                    master=master, details=details, system_buttons=system)


def pinggu_entities(material: EntityConfig | None = None) -> dict[str, EntityConfig]:
    return {COST_PINGGU: seed("entity", COST_PINGGU), COST_MATERIAL: material or seed("entity", COST_MATERIAL),
            COST_PACKAGE: seed("entity", COST_PACKAGE)}


def snapshot(role_code: str, grant_role: RoleConfig | None = None, *, material: EntityConfig | None = None,
             save_operation: OperationConfig | None = None,
             lookups: dict[str, dict[str, LookupSetting]] | None = None) -> FakeConfigSnapshot:
    """角色 `role_code` 的配置快照：成本核算页（种子配置加上旧页面的区域按钮），以及该角色能访问的物料清单页。"""
    granted = grant_role or role(role_code)
    entities: dict[str, EntityConfig] = {**pinggu_entities(material), COST_GOODS_PRICE: GOODS_ENTITY}
    views = {COST_PINGGU: page_view(COST_PINGGU, seed("page", COST_PINGGU), entities, granted, PINGGU_AREA_BUTTONS, lookups)}
    if GOODS_PRICE_MANAGE in granted.pages:
        views[GOODS_PRICE_MANAGE] = page_view(GOODS_PRICE_MANAGE, GOODS_PAGE, entities, granted,
                                              {"master": [ButtonConfig(action="copyRow", label="复制"),
                                                          ButtonConfig(action="saveGridConfig", label="保存列配置")]})
    operations = {SAVE: save_operation or seed("operation", SAVE), GOODS_SAVE: GOODS_SAVE_OPERATION}
    return FakeConfigSnapshot(version=1, role_code=role_code, role=granted, page_views=views,
                              pages=[COST_PINGGU, GOODS_PRICE_MANAGE, GOODS_MANAGE], entities=entities, operations=operations)


# ---------------------------------------------------------------- 执行上下文

def context(config: FakeConfigSnapshot, *, user_id: str = "381", username: str = "HY190510",
            origin: Origin | None = None) -> ExecutionContext:
    """默认账号取 cmx 中有技术中心角色的真实账号 HY190510（ID 381，08 查询）。cmx 中没有同时拥有技术中心和 001 的账号，
    E07 的"两个角色"是假设的场景；会话选定的角色决定快照，见 `snapshot`。"""
    who = Identity(user_id=user_id, username=username, display_name=username, department_id=None,
                   role_code=config.role_code, session_id=f"s-{user_id}")
    return ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=who, config=config,
                            config_version=config.version, origin=origin or Origin(kind="user", approval_id=None),
                            now=datetime(2026, 10, 29, 10, 0, 0))
