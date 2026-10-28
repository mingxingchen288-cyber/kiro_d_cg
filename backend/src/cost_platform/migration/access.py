"""角色和菜单的迁移（C06 第 8、9 节，MG-08）。"""

from __future__ import annotations

import json
import re
from typing import Any

from . import naming
from .inventory import Entry, Inventory
from .legacy import T_RESOURCE, T_ROLE, T_ROLE_PAGE, Legacy, load_json, src
from .pages import Registry
from .snapshot import Row

SYSTEM_GROUP = "系统默认按钮"
EXPORT_GROUP = "自定义导出"
SYSTEM_ACTIONS = ("save", "addRow", "deleteRow", "advancedSearch")
ADMIN_PAGES = ("meta-config", "permission")
"""有这些旧页面权限的角色可以使用配置和管理功能（旧系统只有 ADMIN 有）。"""


def migrate_roles(legacy: Legacy, inv: Inventory, reg: Registry) -> None:
    rows_by_role: dict[int, list[Row]] = {}
    all_pages: dict[int, set[str]] = {}
    approval_buttons: dict[str, list[str]] = {}
    for r in legacy.s[T_ROLE_PAGE]:
        all_pages.setdefault(r["ROLE_ID"], set()).add(r["PAGE_CODE"])
        if r["PAGE_CODE"] in reg.pages:
            rows_by_role.setdefault(r["ROLE_ID"], []).append(r)
    for role_id in sorted(rows_by_role):
        role = legacy.roles[role_id]
        code = role["ROLE_CODE"]
        admin = bool(all_pages[role_id] & set(ADMIN_PAGES))
        pages: dict[str, Any] = {}
        blocked: list[str] = []
        sources = [src(T_ROLE, role)]
        for row in sorted(rows_by_role[role_id], key=lambda r: list(reg.pages).index(r["PAGE_CODE"])):
            page = reg.pages[row["PAGE_CODE"]]
            sources.append(src(T_ROLE_PAGE, row))
            entry: dict[str, Any] = {"buttons": _buttons(inv, reg, role, row, approval_buttons)}
            rows = _rows(inv, reg, role, row, blocked)
            if rows is not None:
                entry["rows"] = rows
            columns = _columns(inv, reg, role, row, blocked)
            if columns:
                entry["columns"] = columns
            pages[page.code] = entry
        content = {"name": role["ROLE_NAME"], "admin": admin, "pages": pages}
        if blocked:
            inv.withhold("role", code, blocked[0])
            continue
        inv.add("role", code, role["ROLE_NAME"], content, sources)
    for page_code, roles in approval_buttons.items():
        inv.note("未迁移的旧配置（MG-08）", f"{page_code} 的按钮权限 系统默认按钮:approval.apply、approval.cancel、approval.progress"
                 f"不迁移（审批改为保存时自动触发，处理权限由审批流决定，进度所有人可看），涉及角色：{'、'.join(roles)}")
    inv.note("编码", "角色编码取旧 T_COST_ROLE.ROLE_CODE 原值（ADMIN、技术中心、001、002 等），与账号的角色分配（T-MG-3）对应")
    inv.note("按旧系统行为取值（MG-10）", f"角色的 admin：旧系统只有拥有 {'、'.join(ADMIN_PAGES)} 页面权限的角色能进入配置和权限管理，"
             "这些角色为 true（只有 ADMIN），其余为 false")
    skipped = sorted(set(legacy.roles) - set(rows_by_role))
    if skipped:
        inv.note("未迁移的旧配置", "本次范围内没有页面权限的角色不生成：" + "、".join(
            f"{legacy.roles[i]['ROLE_CODE']}（{legacy.roles[i]['ROLE_NAME']}，ID={i}）" for i in skipped))


def _buttons(inv: Inventory, reg: Registry, role: Row, row: Row, approval_buttons: dict[str, list[str]]) -> list[str]:
    page = reg.pages[row["PAGE_CODE"]]
    groups = {reg.entities[c].row["TABLE_NAME"]: reg.entities[c] for c in (page.master, *page.details)}
    policy: list[str] = load_json(row["BUTTON_POLICY"]) or []
    out: list[str] = []
    dropped_approval: list[str] = []
    for item in policy:
        if item == "*":
            out.append("*")
            continue
        group, _, action = item.partition(":")
        key: str | None = None
        handled = False  # 不生成、但已按规则处理（审批按钮、暂缓的导出、存储过程按钮）
        if group == SYSTEM_GROUP:
            if action.startswith("approval."):
                dropped_approval.append(action)
                handled = True
            elif action in SYSTEM_ACTIONS:
                key = f"system:{action}"
        elif group == EXPORT_GROUP:
            if page.exports.get(action):
                key = f"export:{action}"
            elif action in page.exports:
                inv.note("暂缓生成的权限", f"{role['ROLE_CODE']} 在 {page.code} 的导出权限 export:{action} 随导出暂缓生成"
                         f"（{src(T_ROLE_PAGE, row).text()}）")
                handled = True
        elif group in groups:
            button = f"{groups[group].region}:{action}"
            if button in page.procedure_buttons:
                page.procedure_buttons[button]["roles"].append(role["ROLE_CODE"])
                handled = True
            elif action in page.region_buttons.get(groups[group].region, []):
                key = button
        if key is None and not handled:
            inv.entry(Entry("manual", f"MR-ROLE-{role['ID']}-{page.code}-按钮-{item}", page.code,
                            f"角色 {role['ROLE_CODE']} 的按钮权限 {item}", [src(T_ROLE_PAGE, row)], item,
                            "分组或动作在迁移后的页面中不存在", "没有生成这一项"))
        if key and key not in out:
            out.append(key)
    if dropped_approval:
        approval_buttons.setdefault(page.code, []).append(f"{role['ROLE_CODE']}（ID={row['ID']}）")
    return out


def _rows(inv: Inventory, reg: Registry, role: Row, row: Row, blocked: list[str]) -> Any:
    text = row["ROW_POLICY"]
    if not text:
        return None
    page = reg.pages[row["PAGE_CODE"]]
    master = reg.entities[page.master]
    columns = {f["column"] for f in master.fields.values() if f["column"]}
    try:
        policy = json.loads(text)
    except ValueError:
        return text
    if not isinstance(policy, dict):
        return text
    missing = [c for c in policy.get("conditions", []) if str(c.get("field", "")).upper() not in columns]
    if not missing:
        return policy
    entry_id = f"MR-ROLE-{role['ID']}-{page.code}-行权限"
    kept = [c for c in policy["conditions"] if c not in missing]
    proposal = None
    if kept and policy.get("mode") == "visual":
        sql = policy.get("sql", "")
        for c in missing:
            sql = re.sub(rf"\s+(?:OR|AND)\s+{re.escape(c['field'])}\s*=\s*'{re.escape(str(c.get('value')))}'", "", sql)
        proposal = json.dumps(policy | {"conditions": kept, "sql": sql}, ensure_ascii=False)
    names = "、".join(f"{c['field']} = '{c.get('value')}'" for c in missing)
    confirmed = inv.entry(Entry(
        "manual", entry_id, page.code, f"角色 {role['ROLE_CODE']}（{role['ROLE_NAME']}）在 {page.code} 的行权限",
        [src(T_ROLE_PAGE, row)], text, f"条件 {names} 引用了没有复制到 d_cg 的列（MG-13）",
        "没有生成这个角色；确认后按确认的行权限生成", proposal=proposal,
        scenario=f"与其他条件是“{policy.get('logic')}”的关系；新平台没有这一列，这个条件不会成立，去掉后能看到的行不变"))
    if confirmed is None:
        blocked.append(entry_id)
        return policy
    return json.loads(confirmed)


def _columns(inv: Inventory, reg: Registry, role: Row, row: Row, blocked: list[str]) -> dict[str, Any]:
    policy = load_json(row["COLUMN_POLICY"]) or {}
    page = reg.pages[row["PAGE_CODE"]]
    by_component = {reg.entities[c].component["COMPONENT_KEY"]: reg.entities[c] for c in (page.master, *page.details)}
    out: dict[str, Any] = {}
    missing: list[str] = []
    for comp, cols in policy.items():
        entity = by_component.get(comp)
        if entity is None:
            missing.append(f"组件 {comp}")
            continue
        flags: dict[str, Any] = {}
        for item in cols.values():
            name = str(item.get("columnName", "")).upper()
            values = {k: item[k] for k in ("visible", "editable", "required") if isinstance(item.get(k), bool)}
            if name not in entity.fields:
                missing.append(f"{comp}.{name}")
                continue
            if values:
                flags[name] = values
        if flags:
            out[entity.region] = dict(sorted(flags.items(), key=lambda kv: list(entity.fields).index(kv[0])))
    if missing:
        entry_id = f"MR-ROLE-{role['ID']}-{page.code}-列权限"
        inv.entry(Entry("manual", entry_id, page.code, f"角色 {role['ROLE_CODE']} 在 {page.code} 的列权限",
                        [src(T_ROLE_PAGE, row)], row["COLUMN_POLICY"], f"引用了不在实体中的列 {', '.join(missing)}（MG-13）",
                        "没有生成这个角色"))
        blocked.append(entry_id)
    return out


def migrate_menu(legacy: Legacy, inv: Inventory, reg: Registry) -> None:
    resources = legacy.s[T_RESOURCE]
    children: dict[int | None, list[Row]] = {}
    for r in sorted(resources, key=lambda r: (r["SORT_ORDER"] or 0, r["ID"])):
        children.setdefault(r["PARENT_ID"], []).append(r)
    used: list[Row] = []

    def build(parent: int | None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for r in children.get(parent, []):
            if r["RESOURCE_TYPE"] == "PAGE" and r["PAGE_CODE"] in reg.pages:
                code = reg.pages[r["PAGE_CODE"]].code
                items.append({"key": code, "title": r["RESOURCE_NAME"], "kind": "page", "pageCode": code})
                used.append(r)
            elif r["RESOURCE_TYPE"] == "DIRECTORY":
                sub = build(r["ID"])
                if sub:
                    items.append({"key": naming.page_code(r["PAGE_CODE"]), "title": r["RESOURCE_NAME"], "kind": "group",
                                  "children": sub})
                    used.append(r)
        return items

    items = build(None)
    inv.add("menu", "main", "菜单", {"items": items}, [src(T_RESOURCE, r) for r in sorted(used, key=lambda r: r["ID"])])
    others = [f"{r['RESOURCE_NAME']}（{r['PAGE_CODE']}）" for r in resources if r["RESOURCE_TYPE"] == "PAGE"
              and r["PAGE_CODE"] not in reg.pages]
    inv.note("未迁移的旧配置", "菜单只含已迁移的页面，其余页面迁移后再加入：" + "、".join(others))
