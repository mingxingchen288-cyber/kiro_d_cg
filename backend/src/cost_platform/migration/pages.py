"""页面的迁移：实体、页面、保存操作、计算和界面规则、字典、Lookup、导出（C06 第 2–5、9 节）。

每个旧页面按以下顺序生成：
1. 实体：页面组件引用的旧表元数据，字段只取列元数据中 VISIBLE=1 的列（MG-13）；有查询视图时，
   字段的 `column` 取视图中来自写入表同名列的列，来自其他表或由表达式算出的为 null（只读显示）。
2. 计算规则：写入表有 Oracle 虚拟列的按虚拟列表达式转换（MG-12），其余字段按旧前端 CALC 转换。
3. 页面字段设置、区域按钮、表格选项、界面规则、字典、Lookup。
4. 字段的角色和可编辑、保存操作的 writableFields。
5. 导出（MG-07）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from . import naming
from .expressions import Converted, Scope, Unconvertible, convert_legacy_calc, convert_oracle
from .inventory import Entry, Inventory, Source
from .legacy import (
    T_COLUMN,
    T_COMPONENT,
    T_EXPORT,
    T_EXPORT_DETAIL,
    T_LOOKUP,
    T_RESOURCE,
    T_RULE,
    T_TAB_COLS,
    T_TABLE,
    Legacy,
    load_json,
    split_top,
    top_keyword,
    src,
)
from .snapshot import Row

_TYPES = {"number": "number", "text": "text", "date": "date", "datetime": "datetime", "checkbox": "boolean"}
_BUILTIN_ACTIONS = ("addRow", "copyRow", "deleteRow", "saveGridConfig")
_PAGE_ACTIONS = ("save", "advancedSearch")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPS = {"eq": "eq", "ne": "ne", "gt": "gt", "ge": "ge", "lt": "lt", "le": "le", "like": "like", "in": "in",
        "isNull": "isNull", "isNotNull": "isNotNull"}

MG14_EDITABLE = {("COST_PINGGU", "MEMO")}
"""MG-14：按用户决定改为可编辑的字段（旧系统不可编辑）。"""


@dataclass
class EntityInfo:
    code: str
    row: Row
    page: str
    component: Row
    master: str | None
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    columns: dict[str, Row] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)
    calculated: set[str] = field(default_factory=set)
    lookup_editable: set[str] = field(default_factory=set)
    fill_targets: set[str] = field(default_factory=set)
    erp_row: dict[str, str] | None = None
    erp_fields: set[str] = field(default_factory=set)
    approval_required: list[dict[str, Any]] = field(default_factory=list)
    defaults: dict[str, dict[str, bool]] = field(default_factory=dict)
    writable: list[str] = field(default_factory=list)

    @property
    def table(self) -> str:
        return self.row["TARGET_TABLE"].upper()

    @property
    def read_view(self) -> str | None:
        view = (self.row["QUERY_VIEW"] or "").upper()
        return view if view and view != self.table else None

    @property
    def pk(self) -> str:
        return (self.row["PK_COLUMN"] or "ID").upper()

    @property
    def parent_key(self) -> str | None:
        return (self.row["PARENT_FK_COLUMN"] or "").upper() or None

    @property
    def region(self) -> str:
        return "master" if self.master is None else self.code

    def source(self) -> Source:
        return src(T_TABLE, self.row)


@dataclass
class PageInfo:
    old: str
    code: str
    title: str
    master: str
    details: list[str]
    save_operation: str
    region_buttons: dict[str, list[str]] = field(default_factory=dict)
    procedure_buttons: dict[str, dict[str, Any]] = field(default_factory=dict)
    exports: dict[str, bool] = field(default_factory=dict)
    """导出编码 → 是否生成（被暂缓时为 False）。"""


class Registry:
    """已迁移页面的实体和页面，供角色、菜单和审批流引用。"""

    def __init__(self) -> None:
        self.entities: dict[str, EntityInfo] = {}
        self.pages: dict[str, PageInfo] = {}
        self.lookups: dict[str, set[str]] = {}
        """用到的旧 Lookup 编码 → 回填用到的列。"""

    def page_entities(self, old_page: str) -> list[EntityInfo]:
        page = self.pages[old_page]
        return [self.entities[c] for c in (page.master, *page.details)]

    def by_table(self, old_page: str, table: str) -> list[EntityInfo]:
        return [e for e in self.page_entities(old_page) if e.table == table.upper()]

    def by_legacy_code(self, old_page: str, table_code: str) -> EntityInfo | None:
        for e in self.page_entities(old_page):
            if e.row["TABLE_CODE"] == table_code:
                return e
        return None


class PageMigration:
    def __init__(self, legacy: Legacy, inv: Inventory, registry: Registry, old_page: str) -> None:
        self.l = legacy
        self.inv = inv
        self.reg = registry
        self.old = old_page
        self.code = naming.page_code(old_page)
        self.save_op = naming.save_operation(self.code)
        self.entities: list[EntityInfo] = []
        self.page_fields: dict[str, dict[str, dict[str, Any]]] = {}
        self.rules: list[tuple[str, str, dict[str, Any], list[Source]]] = []

    # ------------------------------------------------------------ 总流程

    def run(self) -> PageInfo:
        self._entities()
        master = self.entities[0]
        page = PageInfo(self.old, self.code, self._title(master), master.code, [e.code for e in self.entities[1:]],
                        self.save_op)
        self.reg.pages[self.old] = page
        for e in self.entities:
            self.reg.entities[e.code] = e
        for e in self.entities:
            self.page_fields[e.code] = {}
            self._calc_rules(e)
            self._lookups(e)
            self._dicts(e)
        self._other_rules()
        for e in self.entities:
            self._editability(e)
        self._emit_entities()
        self._emit_page(page)
        self._emit_operation()
        self._emit_rules()
        self._exports(page)
        return page

    def _title(self, master: EntityInfo) -> str:
        for r in self.l.s[T_RESOURCE]:
            if r["PAGE_CODE"] == self.old:
                return r["RESOURCE_NAME"]
        return master.row["TABLE_NAME"]

    def _entry(self, list_name: str, entry_id: str, title: str, sources: list[Source], original: str, reason: str,
               handling: str, proposal: str | None = None, scenario: str | None = None) -> str | None:
        return self.inv.entry(Entry(list_name, entry_id, self.code, title, sources, original, reason, handling,  # type: ignore[arg-type]
                                    proposal, scenario))

    def _note(self, section: str, text: str) -> None:
        self.inv.note(section, f"{self.code}：{text}")

    # ------------------------------------------------------------ 1. 实体

    def _entities(self) -> None:
        master_code: str | None = None
        for comp in self.l.components[self.old]:
            if comp["COMPONENT_TYPE"] not in ("GRID", "DETAIL_GRID") or not comp["REF_TABLE_CODE"]:
                continue
            row = self.l.tables[comp["REF_TABLE_CODE"]]
            code = naming.entity_code(row["TABLE_CODE"])
            is_master = comp["COMPONENT_TYPE"] == "GRID"
            info = EntityInfo(code, row, self.code, comp, None if is_master else master_code)
            if is_master:
                master_code = code
            self._fields(info)
            self.entities.append(info)
        for e in self.entities[1:]:
            self.entities[0].details.append(e.code)
        unused = [r for r in self.l.s[T_TABLE] if r["PAGE_CODE"] == self.old
                  and r["TABLE_CODE"] not in {e.row["TABLE_CODE"] for e in self.entities}]
        for r in unused:
            self._note("未迁移的旧配置", f"表元数据 {r['TABLE_CODE']}（{r['TABLE_NAME']}，{T_TABLE} ID={r['ID']}）没有页面组件引用，"
                       "不生成实体")

    def _fields(self, e: EntityInfo) -> None:
        cols = sorted(self.l.columns[e.row["ID"]], key=lambda r: (r["DISPLAY_ORDER"] or 0, r["ID"]))
        view = self.l.view_columns(e.read_view, e.table) if e.read_view else None
        table_cols = self.l.tab_cols[e.table]
        hidden: list[str] = []
        for r in cols:
            name = r["COLUMN_NAME"].upper()
            if r["VISIBLE"] != 1:
                hidden.append(name)
                continue
            if name in e.fields:
                first = e.columns[name]
                self._entry("manual", f"MR-{e.code}-{name}-重复列", f"{e.code}.{name} 的列元数据重复",
                            [src(T_COLUMN, first), src(T_COLUMN, r)],
                            f"ID={first['ID']} 标题“{first['HEADER_TEXT']}”；ID={r['ID']} 标题“{r['HEADER_TEXT']}”",
                            "旧页面同一个字段有两条可见的列元数据，表格中显示两列；新平台一个字段只有一列",
                            f"保留 ID={first['ID']}（显示顺序在前、ID 小的一条），不生成 ID={r['ID']}")
                continue
            if view is not None:
                vc = view.get(name)
                column = vc.column if vc else None
                if vc is None:
                    self._note("转换说明", f"{e.code}.{name} 不在查询视图 {e.read_view} 中，按只读字段生成（column 为 null）")
            else:
                target = (r["TARGET_COLUMN"] or r["COLUMN_NAME"]).upper()
                column = target if target in table_cols else None
            cfg = load_json(r["RULES_CONFIG"]) or {}
            ftype = _TYPES.get((r["DATA_TYPE"] or "text").lower())
            if ftype is None:
                raise ValueError(f"未知的旧数据类型 {r['DATA_TYPE']}（{T_COLUMN} ID={r['ID']}）")
            item: dict[str, Any] = {"name": name, "column": column, "label": r["HEADER_TEXT"], "type": ftype}
            if ftype == "number" and isinstance(cfg.get("precision"), int):
                item["scale"] = cfg["precision"]
            item["source"] = "own"
            item["role"] = "input"
            default = self._default(e, r, ftype)
            if default is not None:
                item["default"] = default
            e.fields[name] = item
            e.columns[name] = r
        if e.pk not in e.fields:
            raise ValueError(f"{e.code} 的主键 {e.pk} 不在可见列中")
        if hidden:
            self._note("不进实体的列（MG-13）", f"{e.code}：列元数据 VISIBLE=0 的 {', '.join(hidden)}")
        own_view = {n for n, f in e.fields.items() if f["column"] is None}
        if own_view:
            self._note("转换说明", f"{e.code} 的 {', '.join(sorted(own_view))} 在查询视图中取自其他表或由表达式算出，"
                       "column 为 null，只读显示（C06 第 2 节）")

    def _default(self, e: EntityInfo, r: Row, ftype: str) -> dict[str, Any] | None:
        raw = r["DEFAULT_VALUE"]
        if raw is None or raw == "":
            return None
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        if not isinstance(parsed, dict):
            parsed = {"type": "static", "value": str(raw)}
        kind, value = parsed.get("type"), parsed.get("value")
        if kind == "builtin":
            return {"type": "builtin", "value": value}
        if kind == "multi":
            values = value if isinstance(value, list) else str(value or "").split(",")
            return {"type": "options", "value": [str(v).strip() for v in values if str(v).strip()]}
        text = str(value)
        if ftype == "boolean" and text in ("0", "1"):
            self._note("按旧系统行为取值（MG-10）", f"{e.code}.{r['COLUMN_NAME']} 是勾选框（旧 DATA_TYPE=checkbox，"
                       f"库中为 NUMBER(1)），默认值 {text} 写成 {'true' if text == '1' else 'false'}")
            text = "true" if text == "1" else "false"
        return {"type": "static", "value": text}

    # ------------------------------------------------------------ 2. 计算规则

    def _scope(self, e: EntityInfo) -> Scope:
        codes = {x.row["TABLE_CODE"]: x.code for x in self.entities}
        if e.master is None:
            details = {d.code: frozenset(d.fields) for d in self.entities if d.master == e.code}
            return Scope(e.code, frozenset(e.fields), details=details, legacy_codes=codes)
        master = next(x for x in self.entities if x.code == e.master)
        return Scope(e.code, frozenset(e.fields), master_entity=master.code, master=frozenset(master.fields),
                     legacy_codes=codes)

    def _virtual(self, table: str) -> dict[str, Row]:
        cols = sorted(self.l.tab_cols[table].values(), key=lambda r: r["COLUMN_ID"])
        return {r["COLUMN_NAME"]: r for r in cols if r["VIRTUAL_COLUMN"] == "YES"}

    def _calc_rules(self, e: EntityInfo) -> None:
        virtual = self._virtual(e.table)
        exprs = {name: r["DATA_DEFAULT"].strip() for name, r in virtual.items()}
        calc_row = self.l.rule(self.old, e.component["COMPONENT_KEY"], "CALC")
        old_items: list[dict[str, Any]] = load_json(calc_row["RULES"]) if calc_row else []
        old_order = {str(i.get("field", "")).upper(): i.get("order") for i in old_items}
        for name, vr in virtual.items():
            source = Source(T_TAB_COLS, f"TABLE_NAME={e.table},COLUMN_NAME={name}")
            if name not in e.fields:
                self._note("转换说明", f"{e.table} 的虚拟列 {name} 页面不显示，不生成计算规则")
                continue
            order = old_order.get(name)
            order = order if isinstance(order, int) else 100 + vr["COLUMN_ID"]
            scope = self._scope(e)
            try:
                conv = convert_oracle(exprs[name], name, scope, exprs)
            except Unconvertible as exc:
                self._entry("manual", f"MR-{e.code}-{name}-虚拟列", f"{e.code}.{name} 的虚拟列表达式", [source],
                            exprs[name], str(exc), "没有生成计算规则")
                continue
            self._add_calc(e, name, order, conv, [source])
            if scope.master_refs:
                self._note("转换说明（MG-12）", f"{e.code}.{name} 中的 {', '.join(sorted(scope.master_refs))} "
                           "改为取主表的值（master.字段）")
            if conv.dropped_else:
                self._note("转换说明（MG-12）", f"{e.code}.{name} 去掉兜底分支 ELSE {conv.dropped_else}："
                           "分支都不成立时保持原值")
        for index, item in enumerate(old_items):
            name = str(item.get("field", "")).upper()
            source = src(T_RULE, calc_row) if calc_row else Source(T_RULE, "")
            if name in virtual:
                self._note("转换说明（MG-12）", f"{e.code}.{name}：旧前端 CALC（{source.text()} 第 {index + 1} 项）"
                           "不使用，按 Oracle 虚拟列表达式转换")
                continue
            original = json.dumps(item, ensure_ascii=False)
            if name not in e.fields:
                self._entry("manual", f"MR-{e.code}-{name}-CALC", f"{e.code}.{name} 的旧前端计算", [source], original,
                            f"计算的字段 {name} 页面不显示，不在实体中（MG-13）", "没有生成计算规则")
                continue
            order = item.get("order")
            try:
                conv = convert_legacy_calc(item, self._scope(e))
            except Unconvertible as exc:
                self._entry("manual", f"MR-{e.code}-{name}-CALC", f"{e.code}.{name} 的旧前端计算", [source], original,
                            str(exc), "没有生成计算规则", scenario=self._hidden_scenario(e, name, str(exc)))
                continue
            if not isinstance(order, int):
                order = index + 1
                self._note("按旧系统行为取值（MG-10）", f"{e.code}.{name} 的旧 CALC 没有 order，按在旧规则中的位置取 {order}")
            self._add_calc(e, name, order, conv, [source])

    def _hidden_scenario(self, e: EntityInfo, name: str, reason: str) -> str | None:
        """公式用到页面不显示的列时，说明不生成的后果和保留的办法（交用户决定）。"""
        headers = {r["COLUMN_NAME"].upper(): r["HEADER_TEXT"] for r in self.l.columns[e.row["ID"]] if r["VISIBLE"] != 1}
        hidden = sorted(c for c in self.l.tab_cols[e.read_view or e.table] if c not in e.fields and re.search(rf"\b{c}\b", reason))
        if not hidden:
            return None
        names = "、".join(f"{c}（{headers[c]}）" if c in headers else c for c in hidden)
        after = "用户可以直接输入" if e.columns[name]["EDITABLE"] == 1 else "保持迁移时的值，用户也不能输入"
        return (f"{self.code} 页面的{e.row['TABLE_NAME']}中，“{e.fields[name]['label']}”在旧系统按这条公式自动计算，公式用到页面不显示的列"
                f" {names}。不生成时这一列不再自动计算，{after}；要保留，需要把这些列作为隐藏字段放进实体，"
                "这与 MG-13“页面不显示的列不进实体”冲突，需要用户决定")

    def _add_calc(self, e: EntityInfo, name: str, order: int, conv: Converted, sources: list[Source]) -> None:
        content: dict[str, Any] = {"layer": "entity", "target": e.code, "category": "calc", "field": name, "order": order}
        if conv.branches is not None:
            content["branches"] = [({"when": w} if w else {}) | {"expression": x} for w, x in conv.branches]
        else:
            content["expression"] = conv.expression
        label = e.fields[name]["label"]
        self.rules.append((f"{e.code}.{name}", f"{label}（计算）", content, sources))
        e.calculated.add(name)

    # ------------------------------------------------------------ 3. Lookup、字典

    def _lookups(self, e: EntityInfo) -> None:
        for name, r in e.columns.items():
            params = (load_json(r["RULES_CONFIG"]) or {}).get("cellEditorParams") or {}
            old_code = params.get("lookupCode")
            if not old_code:
                continue
            lookup = self.l.lookups.get(old_code)
            source = src(T_COLUMN, r)
            if lookup is None:
                self._entry("manual", f"MR-{e.code}-{name}-Lookup", f"{e.code}.{name} 的 Lookup", [source], old_code,
                            "旧 Lookup 配置不存在", "没有生成 Lookup 设置")
                continue
            fill: dict[str, str] = {}
            for target, column in (params.get("mapping") or {}).items():
                if _IDENT.match(target) and _IDENT.match(column) and target.upper() in e.fields:
                    fill[target.upper()] = column.upper()
                else:
                    self._note("转换说明", f"{e.code}.{name} 的 Lookup 回填项 {target} ← {column} 不是本表字段，"
                               "旧系统回填后不进入任何列，不生成")
            setting: dict[str, Any] = {"code": naming.lookup_code(old_code), "fill": fill}
            if params.get("multiple") or r["CELL_EDITOR"] == "lookupMultiple":
                setting["multiple"] = True
            if params.get("filterColumn"):
                flt: dict[str, Any] = {"column": params["filterColumn"].upper(), "from": params.get("filterValueFrom") or "row"}
                if flt["from"] == "row":
                    flt["field"] = str(params.get("filterField") or "").upper()
                setting["filter"] = flt
            if params.get("noFillback"):
                setting["fillBack"] = False
            else:
                e.lookup_editable.add(name)
                e.fill_targets |= set(fill)
            self.page_fields[e.code].setdefault(name, {})["lookup"] = setting
            self.reg.lookups.setdefault(old_code, set()).update(fill.values())

    def _dicts(self, e: EntityInfo) -> None:
        for name, r in e.columns.items():
            params = (load_json(r["RULES_CONFIG"]) or {}).get("cellEditorParams") or {}
            values = params.get("values")
            if values is None or params.get("lookupCode"):
                continue
            items = values if isinstance(values, list) else [v.strip() for v in str(values).split(",")]
            items = [str(v) for v in items if str(v)]
            source = src(T_COLUMN, r)
            if r["CELL_EDITOR"] == "tagSelectCellEditor":
                self._entry("manual", f"MR-{e.code}-{name}-可填写下拉", f"{e.code}.{name} 的“下拉（可填写）”", [source],
                            json.dumps(items, ensure_ascii=False),
                            "旧编辑器 tagSelectCellEditor 可以从下拉中选，也可以填写下拉中没有的值；新平台的字典只能从列表中选，"
                            "需要新增能力", "按普通文本字段生成，不生成字典")
                continue
            editable = e.fields[name]["column"] is not None and r["EDITABLE"] == 1
            if not editable:
                self._note("转换说明", f"{e.code}.{name} 的下拉选项 {'/'.join(items)} 只用于编辑，新平台中该字段只读，不生成字典")
                continue
            key = naming.dict_code(e.code, name)
            self.inv.add("dict", key, e.fields[name]["label"],
                         {"items": [{"value": v, "label": v, "order": i + 1} for i, v in enumerate(items)]}, [source])
            self.page_fields[e.code].setdefault(name, {})["dictType"] = key

    # ------------------------------------------------------------ 3. 其他页面规则

    def _other_rules(self) -> None:
        self.grids: dict[str, dict[str, Any]] = {}
        self.required_from_columns: set[str] = set()
        for e in self.entities:
            comp = e.component["COMPONENT_KEY"]
            rows = {r["RULE_TYPE"]: r for r in self.l.rules[(self.old, comp)]}
            self._grid(e, rows.get("GRID_OPTIONS"))
            self._validation(e, rows.get("VALIDATION"))
            if "GRID_STYLE" in rows:
                self._grid_style(e, rows["GRID_STYLE"])
            if "EDITABLE" in rows or "APPROVAL_REQUIRED" in rows:
                self._erp_pattern(e, rows.get("EDITABLE"), rows.get("APPROVAL_REQUIRED"))
            if "ROLE_BINDING" in rows:
                self._note("未迁移的旧配置", f"ROLE_BINDING {rows['ROLE_BINDING']['RULES']}（{src(T_RULE, rows['ROLE_BINDING']).text()}）"
                           "标记主表组件，由页面配置的 master 表达，不另生成")
            if "SUMMARY_CONFIG" in rows:
                r = rows["SUMMARY_CONFIG"]
                self._entry("manual", f"MR-{self.code}-{comp}-SUMMARY_CONFIG", f"{self.code} 的汇总配置 SUMMARY_CONFIG",
                            [src(T_RULE, r)], r["RULES"],
                            "新平台没有对应的配置项；需要新增能力：在表格中按分类显示明细金额汇总和行数（旧配置的 summaryColumns、"
                            "summaryAggregates）", "没有生成")
            for kind, r in rows.items():
                if kind not in ("CALC", "GRID_OPTIONS", "VALIDATION", "GRID_STYLE", "EDITABLE", "APPROVAL_REQUIRED",
                                "ROLE_BINDING", "SUMMARY_CONFIG"):
                    self._entry("manual", f"MR-{self.code}-{comp}-{kind}", f"{self.code} 的 {kind} 规则", [src(T_RULE, r)],
                                r["RULES"], "迁移没有覆盖这种规则类型", "没有生成")

    def _grid(self, e: EntityInfo, row: Row | None) -> None:
        opts = load_json(row["RULES"]) if row else {}
        self.grids[e.code] = {"sideBar": bool(opts.get("sideBar") or opts.get("enableSidebar")),
                              "cellSelection": bool(opts.get("cellSelection")), "groupBy": []}
        if row is None:
            self._note("按旧系统行为取值（MG-10）", f"{e.code} 的表格没有 GRID_OPTIONS，旧系统不显示侧边栏、不启用单元格选择"
                       "（grid-options.ts），写为 sideBar=false、cellSelection=false")
        extra = sorted(k for k in opts if k not in ("sideBar", "enableSidebar", "cellSelection"))
        if extra:
            self._note("未迁移的旧配置", f"{e.code} 的 GRID_OPTIONS 中 {', '.join(extra)}（{src(T_RULE, row).text()}）"
                       "是旧表格的分页加载参数，新平台的列表查询自己分页，不迁移")

    def _validation(self, e: EntityInfo, row: Row | None) -> None:
        items = load_json(row["RULES"]) if row else []
        if not items:
            self.required_from_columns |= {f"{e.code}.{n}" for n, r in e.columns.items() if r["REQUIRED"] == 1}
            return
        upper_columns = set(self.l.tab_cols[e.read_view or e.table]) | set(e.fields)
        for index, item in enumerate(items):
            fld = item.get("field") or item.get("columnName") or ""
            keys = [k for k in ("required", "notZero", "min", "max", "pattern") if item.get(k) not in (None, False, "")]
            reasons = []
            if not keys:
                reasons.append(f"没有 required、notZero、min、max、pattern 中的任何一项（写的是 {', '.join(sorted(k for k in item if k not in ('field', 'message')))}）")
            if fld != fld.upper() or fld not in upper_columns:
                reasons.append(f"字段名 {fld} 与行数据的列名（大写）不一致，取不到值")
            entry_id = f"MR-{e.code}-VALIDATION-{index + 1}"
            original = json.dumps(item, ensure_ascii=False)
            if reasons:
                self._entry("manual", entry_id, f"{e.code} 的校验“{item.get('message', '')}”", [src(T_RULE, row)], original,
                            "旧前端只认 required、notZero、min、max、pattern 这几个键，并按大写列名取行中的值"
                            "（usePageRules.ts:105、validator.ts:105）；这一条" + "，".join(reasons) + "，旧系统保存时实际不检查",
                            "按旧系统行为不生成校验规则",
                            proposal=f"如果要按提示文字检查，需要另行确认后新增 validate 规则：{item.get('message', '')}")
            else:
                self._entry("manual", entry_id, f"{e.code} 的校验“{item.get('message', '')}”", [src(T_RULE, row)], original,
                            "迁移没有实现这种校验写法的自动转换", "没有生成")
        self._note("按旧系统行为取值（MG-10）", f"{e.code} 有页面校验规则（{src(T_RULE, row).text()}），旧系统因此不再使用"
                   "列元数据的 REQUIRED（useRuleCompiler.ts:141），required 不从列元数据生成")

    def _grid_style(self, e: EntityInfo, row: Row) -> None:
        if e.master is not None:
            self._entry("manual", f"MR-{e.code}-GRID_STYLE", f"{e.code} 的行样式", [src(T_RULE, row)], row["RULES"],
                        "明细表格的行样式在新平台的页面规则中无法指明作用于哪个明细", "没有生成")
            return
        for index, item in enumerate(load_json(row["RULES"]) or []):
            fld = str(item.get("field", "")).upper()
            op = _OPS.get(item.get("operator", ""))
            entry_id = f"MR-{self.code}-GRID_STYLE-{index + 1}"
            original = json.dumps(item, ensure_ascii=False)
            if fld not in e.fields or op is None:
                self._entry("manual", entry_id, f"{self.code} 的行底色（{fld} {item.get('operator')} {item.get('value')}）",
                            [src(T_RULE, row)], original,
                            f"条件字段 {fld} 页面不显示，不在实体中（MG-13）" if fld not in e.fields else "条件运算符不能转换",
                            "没有生成", scenario=self._style_scenario(e, fld, item))
                continue
            content = {"layer": "page", "target": self.code, "category": "ui", "order": index + 1,
                       "when": {"logic": "AND", "conditions": [{"source": "row", "field": fld, "op": op, "value": item.get("value")}]},
                       "effect": {"rowStyle": item.get("style")}}
            self.rules.append((f"{self.code}.style.{index + 1}", f"行底色：{fld} {op} {item.get('value')}", content,
                               [src(T_RULE, row)]))

    def _style_scenario(self, e: EntityInfo, fld: str, item: dict[str, Any]) -> str | None:
        if e.read_view is None or fld not in self.l.tab_cols[e.read_view]:
            return None
        return (f"{self.code} 页面中，{fld} 由视图 {e.read_view} 按其他列算出，旧系统据此给行上底色"
                f"（{item.get('value')} 时 {json.dumps(item.get('style'), ensure_ascii=False)}）。不迁移时这些行没有底色；"
                f"要保留需要把 {fld} 作为只读字段放进实体（它页面不显示，与 MG-13 冲突），或改写成按实体字段判断的条件")

    def _erp_pattern(self, e: EntityInfo, editable: Row | None, required: Row | None) -> None:
        """旧 EDITABLE（某列不等于某值时整行可编辑）加 APPROVAL_REQUIRED（等于该值时只有部分字段可编辑且须审批），
        即 C06 第 2 节的 ERP 行：erpRow 加 ERP 列，可编辑的字段为平台自有列并列入 approvalRequired。"""
        rules_e = load_json(editable["RULES"]) if editable else []
        rules_a = load_json(required["RULES"]) if required else []
        sources = [src(T_RULE, r) for r in (editable, required) if r]
        ok = (len(rules_e) == 1 and rules_e[0].get("scope") == "row" and len(rules_e[0].get("conditions", [])) == 1
              and rules_e[0]["conditions"][0].get("operator") == "ne" and len(rules_a) == 1
              and rules_a[0].get("scope") == "cell" and len(rules_a[0].get("conditions", [])) == 1
              and rules_a[0]["conditions"][0].get("operator") == "eq")
        if ok:
            ce, ca = rules_e[0]["conditions"][0], rules_a[0]["conditions"][0]
            column = str(ce["field"]).upper()
            ok = column == str(ca["field"]).upper() and str(ce["value"]) == str(ca["value"]) and column in e.fields
        if not ok:
            self._entry("manual", f"MR-{e.code}-EDITABLE", f"{e.code} 的可编辑和必须审批规则", sources,
                        json.dumps({"EDITABLE": rules_e, "APPROVAL_REQUIRED": rules_a}, ensure_ascii=False),
                        "不是“某列为某值的行只能改部分字段且须审批”的写法", "没有生成")
            return
        value = str(rules_e[0]["conditions"][0]["value"])
        fields = [str(f).upper() for f in rules_a[0].get("editableFields", []) if str(f).upper() in e.fields]
        local = self._default(e, e.columns[column], e.fields[column]["type"])
        local_value = local["value"] if local and local["type"] == "static" else "0"
        e.erp_row = {"column": column, "value": value, "localValue": local_value}
        e.erp_fields = {n for n in e.fields if n not in fields and n not in (column, e.pk)
                        and e.fields[n]["column"] is not None}
        e.approval_required.append({"fields": fields, "when": {"logic": "AND", "conditions": [
            {"field": column, "op": "eq", "value": value}]}, "sourcePages": [self.code]})
        self._note("转换说明", f"{e.code}：旧 EDITABLE（{column} ≠ {value} 的行可编辑）和 APPROVAL_REQUIRED"
                   f"（{column} = {value} 的行只有 {', '.join(fields)} 可编辑、须审批）转为 erpRow"
                   f"（{column}={value}，新增行为 {local_value}）、ERP 列 {', '.join(sorted(e.erp_fields))} 和 approvalRequired")

    # ------------------------------------------------------------ 4. 可编辑与可写

    def _editability(self, e: EntityInfo) -> None:
        virtual = set(self._virtual(e.table))
        writable: set[str] = set()
        for name, f in e.fields.items():
            r = e.columns[name]
            if name == e.pk or name == e.parent_key:
                f["role"] = "system"
            elif name in e.calculated:
                f["role"] = "calculated"
            if name in e.erp_fields:
                f["source"] = "erp"
            if f["role"] != "input":
                continue
            if f["column"] is None:
                if r["EDITABLE"] == 1:
                    self._note("转换说明（MG-13）", f"{e.code}.{name} 旧系统可编辑，值取自查询视图中的其他表，新平台只读")
                continue
            editable = r["EDITABLE"] == 1
            if name in e.lookup_editable and not editable:
                editable = True
                self._note("按旧系统行为取值（MG-10）", f"{e.code}.{name} 旧列元数据 EDITABLE=0，但配置了 Lookup，旧系统点单元格即可"
                           "打开 Lookup 并回填（useLookupDialog.ts:87），按可编辑生成")
            if (e.code, name) in MG14_EDITABLE:
                editable = True
                self._note("转换说明（MG-14）", f"{e.code}.{name} 旧系统不可编辑，按用户决定迁移为可编辑")
            if r["IS_VIRTUAL"] == 1 and name not in virtual:
                if editable:
                    self._note("按旧系统行为取值（MG-10）", f"{e.code}.{name} 旧列元数据 IS_VIRTUAL=1，旧后端保存时跳过"
                               "（DynamicDataService.java:303、411），按不可编辑生成")
                editable = False
            flags: dict[str, bool] = {}
            if not editable:
                flags["editable"] = False
            if f"{e.code}.{name}" in self.required_from_columns:
                flags["required"] = True
            if flags:
                e.defaults[name] = flags
            if editable:
                writable.add(name)
        for name in sorted(e.fill_targets - writable):
            f = e.fields[name]
            if f["role"] == "input" and f["column"] is not None and not (e.columns[name]["IS_VIRTUAL"] == 1 and name not in virtual):
                writable.add(name)
                self._note("按旧系统行为取值（MG-10）", f"{e.code}.{name} 不能直接编辑，但由 Lookup 回填，旧后端保存时写入，"
                           "列入保存操作的 writableFields")
        e.writable = [n for n in e.fields if n in writable]

    # ------------------------------------------------------------ 5. 输出配置项

    def _emit_entities(self) -> None:
        for e in self.entities:
            content: dict[str, Any] = {"table": e.table, "primaryKey": e.pk, "freezable": True}
            if e.read_view:
                content["readView"] = e.read_view
            if e.erp_row:
                content["erpRow"] = e.erp_row
            content["fields"] = list(e.fields.values())
            if e.details:
                content["details"] = [{"entity": d, "parentKey": self.reg.entities[d].parent_key} for d in e.details]
            if e.defaults:
                content["fieldDefaults"] = e.defaults
            if e.approval_required:
                content["approvalRequired"] = e.approval_required
            sources = [e.source()] + [src(T_COLUMN, e.columns[n]) for n in e.fields]
            self.inv.add("entity", e.code, e.row["TABLE_NAME"], content, sources)
        self.inv.note("按旧系统行为取值（MG-10）", "全部实体 freezable 为 true：旧审批的锁定（WF_APPROVAL_LOCK）可以锁定任何业务表的行")

    def _emit_page(self, page: PageInfo) -> None:
        sources = [src(T_COMPONENT, r) for r in self.l.components[self.old]]
        resource = next((r for r in self.l.s[T_RESOURCE] if r["PAGE_CODE"] == self.old), None)
        if resource:
            sources.append(src(T_RESOURCE, resource))
        sources += [src(T_RULE, r) for e in self.entities for r in self.l.rules[(self.old, e.component["COMPONENT_KEY"])]
                    if r["RULE_TYPE"] == "GRID_OPTIONS"]
        regions = [self._region(e, page) for e in self.entities]
        master_row = self.entities[0].row
        content: dict[str, Any] = {"title": page.title, "layout": "masterDetail" if len(regions) > 1 else "single",
                                   "detailMode": "tabs", "audit": master_row["AUDIT_ENABLED"] == 1,
                                   "saveOperation": self.save_op, "master": regions[0]}
        if len(regions) > 1:
            content["details"] = regions[1:]
        self.inv.add("page", self.code, page.title, content, sources)
        self._note("按旧系统行为取值（MG-10）", f"audit 取主表 AUDIT_ENABLED={master_row['AUDIT_ENABLED']}"
                   f"（{e_src(master_row)}）；detailMode 为 tabs：旧页面把 DETAIL_GRID 渲染为页签（useComponentLoader.ts:199）")

    def _region(self, e: EntityInfo, page: PageInfo) -> dict[str, Any]:
        cfg = load_json(e.component["COMPONENT_CONFIG"]) or {}
        region: dict[str, Any] = {"entity": e.code}
        if e.master is not None:
            region["title"] = cfg.get("title") or e.row["TABLE_NAME"]
        fields: dict[str, dict[str, Any]] = {}
        for name, r in e.columns.items():
            setting = dict(self.page_fields[e.code].get(name, {}))
            if isinstance(r["WIDTH"], int) and r["WIDTH"] > 0:
                setting = {"width": r["WIDTH"]} | setting
            if r["PINNED"] in ("left", "right"):
                setting["pinned"] = r["PINNED"]
            if setting:
                fields[name] = {k: setting[k] for k in ("width", "pinned", "dictType", "lookup") if k in setting}
        if fields:
            region["fields"] = fields
        buttons: list[dict[str, Any]] = []
        aliases: list[str] = []
        for b in cfg.get("buttons", []):
            action = b.get("action")
            if b.get("procedure"):
                page.procedure_buttons[f"{e.region}:{action}"] = {"button": b, "entity": e, "roles": []}
                continue
            if action in _BUILTIN_ACTIONS:
                buttons.append({"action": action, "label": b.get("label") or action})
                page.region_buttons.setdefault(e.region, []).append(action)
                if b.get("toolbarAlias"):
                    aliases.append(f"{b.get('label')}（工具栏显示“{b['toolbarAlias']}”）")
            elif action in _PAGE_ACTIONS:
                self._note("转换说明", f"{e.code} 的“{b.get('label')}”按钮（{action}）是页面级按钮，新平台不写在区域中（C06 第 3 节）")
            else:
                self._entry("manual", f"MR-{e.code}-按钮-{action}", f"{e.code} 的按钮“{b.get('label')}”",
                            [src(T_COMPONENT, e.component)], json.dumps(b, ensure_ascii=False), "不是内置动作，也没有调用存储过程",
                            "没有生成")
        if aliases:
            self._entry("manual", f"MR-{e.code}-按钮别名", f"{e.code} 的工具栏按钮文字", [src(T_COMPONENT, e.component)],
                        "；".join(aliases), "新平台的按钮只有一个 label，工具栏和右键菜单显示同样的文字；需要新增能力才能保留工具栏别名",
                        "label 取右键菜单的文字")
        extra = sorted({k for b in cfg.get("buttons", []) for k in b if k in ("position", "requiresRow")})
        if extra:
            self._note("转换说明", f"{e.code} 的按钮属性 {', '.join(extra)} 不迁移：内置动作是否需要选中行由平台规定（C06 第 3 节）")
        if buttons:
            region["buttons"] = buttons
        region["grid"] = self.grids[e.code]
        return region

    def _emit_operation(self) -> None:
        master = self.entities[0]
        cfg = load_json(master.component["COMPONENT_CONFIG"]) or {}
        label = next((b.get("label") for b in cfg.get("buttons", []) if b.get("action") == "save"), None) or "保存"
        content = {"label": label, "kind": "save",
                   "writableFields": {e.code: e.writable for e in self.entities if e.writable},
                   "impact": [e.code for e in self.entities], "propagation": "continue"}
        self.inv.add("operation", self.save_op, f"{self._title(master)}保存", content, [src(T_COMPONENT, master.component)])
        self.inv.note("按旧系统行为取值（MG-10）", "页面保存操作的 propagation 为 continue：旧系统保存后照常触发审批和同步；"
                      "rowNotFound 不写（默认 skip）")

    def _emit_rules(self) -> None:
        for key, name, content, sources in self.rules:
            self.inv.add("rule", key, name, content, sources)

    # ------------------------------------------------------------ 6. 导出（MG-07）

    def _exports(self, page: PageInfo) -> None:
        master = self.entities[0]
        for row in self.l.s[T_EXPORT]:
            if row["PAGE_CODE"] != self.old:
                continue
            code = row["EXPORT_CODE"]
            details = sorted((d for d in self.l.s[T_EXPORT_DETAIL] if d["EXPORT_CONFIG_ID"] == row["ID"]),
                             key=lambda d: (d["DISPLAY_ORDER"] or 0, d["ID"]))
            sources = [src(T_EXPORT, row)] + [src(T_EXPORT_DETAIL, d) for d in details]
            if (row["PAGE_FK_COLUMN"] or "").upper() != master.pk:
                self._entry("manual", f"MR-{code}-关联列", f"导出 {code} 的关联列", sources,
                            f"PAGE_FK_COLUMN={row['PAGE_FK_COLUMN']}", "PAGE_FK_COLUMN 不是页面主表的主键（MG-07）", "没有生成")
                page.exports[code] = False
                self.inv.withhold("export", code, f"MR-{code}-关联列")
                continue
            withheld: list[str] = []
            master_sql = self._export_sql(code, "master", row["MASTER_SQL"], [src(T_EXPORT, row)], withheld)
            content: dict[str, Any] = {"page": self.code, "name": row["EXPORT_NAME"], "fileName": row["EXPORT_NAME"]}
            if (row["FONT_NAME"] or "Calibri") != "Calibri":
                content["font"] = row["FONT_NAME"]
            content["master"] = {"sheet": row["MASTER_SHEET_NAME"], "sql": master_sql,
                                 "keyColumn": row["MASTER_LINK_COLUMN"].upper(),
                                 "columns": self._export_columns(code, "master", row["COLUMNS"], row["MASTER_SQL"],
                                                                 [src(T_EXPORT, row)], withheld)}
            out_details = []
            for d in details:
                sql = self._export_sql(code, f"detail-{d['TAB_KEY']}", d["DETAIL_SQL"], [src(T_EXPORT_DETAIL, d)], withheld)
                out_details.append({"sheet": d["SHEET_NAME"], "sql": sql, "linkColumn": d["DETAIL_LINK_COLUMN"].upper(),
                                    "columns": self._export_columns(code, f"detail-{d['TAB_KEY']}", d["COLUMNS"], d["DETAIL_SQL"],
                                                                    [src(T_EXPORT_DETAIL, d)], withheld)})
            if out_details:
                content["details"] = out_details
            if withheld:
                page.exports[code] = False
                self.inv.withhold("export", code, withheld[0])
                continue
            page.exports[code] = True
            self.inv.add("export", code, row["EXPORT_NAME"], content, sources)
        self.inv.note("按旧系统行为取值（MG-10）", "导出的 fileName 取 EXPORT_NAME（旧系统文件名为 导出名称.xlsx，"
                      "CustomExportService.java:141）；detailLayout 不写（默认 perMaster，与旧系统相同）")

    def _export_sql(self, code: str, part: str, sql: str, sources: list[Source], withheld: list[str]) -> str:
        missing = self._missing_columns(sql)
        if not missing:
            return sql
        entry_id = f"MR-{code}-{part}-SQL"
        proposal = re.sub(r"\s+WHERE\s+(\w+)\.DELETED\s*=\s*0\s*$", "", sql, flags=re.I) \
            if missing == ["DELETED"] else None
        confirmed = self._entry("manual", entry_id, f"导出 {code} 的 SQL（{part}）", sources, sql,
                                f"引用了没有复制到 d_cg 的列 {', '.join(missing)}（MG-13）",
                                "没有生成这个导出；确认后按确认的 SQL 生成，并恢复角色中的 export 权限", proposal=proposal,
                                scenario=("已删除的行没有复制，平台删除为物理删除，去掉这个条件后导出的行不变"
                                          if missing == ["DELETED"] else None))
        if confirmed is None:
            withheld.append(entry_id)
            return sql
        return confirmed

    def _missing_columns(self, sql: str) -> list[str]:
        """SQL 中按 `别名.列` 引用、而别名所指的表或视图在新平台的实体中没有的列。"""
        tables = {m.group(2).upper(): m.group(1).upper()
                  for m in re.finditer(r"\bFROM\s+([A-Za-z_][\w$#]*)\s+([A-Za-z_]\w*)", sql, re.I)}
        missing: list[str] = []
        for alias, col in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_][\w$#]*)", sql):
            obj = tables.get(alias.upper())
            if obj is None:
                continue
            available = self._object_columns(obj)
            if available is not None and col.upper() not in available and col.upper() not in missing:
                missing.append(col.upper())
        return missing

    def _object_columns(self, obj: str) -> set[str] | None:
        for e in self.reg.entities.values():
            if e.table == obj:
                return {f["column"] for f in e.fields.values() if f["column"]}
            if e.read_view == obj:
                return set(e.fields)
        return None

    def _export_columns(self, code: str, part: str, columns_json: str | None, sql: str, sources: list[Source],
                        withheld: list[str]) -> list[dict[str, str]]:
        cols = load_json(columns_json) or []
        if cols:
            shown = sorted((c for c in cols if c.get("visible", True) is not False and c.get("field")),
                           key=lambda c: c.get("order") if isinstance(c.get("order"), int) else 1 << 30)
            return [{"field": c["field"], "header": c.get("header") or c["field"]} for c in shown]
        names = _select_aliases(sql)
        if names is not None and len(set(names)) < len(names):
            dup = sorted({n for n in names if names.count(n) > 1})
            names = list(dict.fromkeys(names))
            self._note("按旧系统行为取值（MG-10）", f"导出 {code}（{part}）的 SQL 中 {', '.join(dup)} 出现多次，旧系统按结果行的"
                       "列名取值，同名列只导出一列")
        if names is None:
            entry_id = f"MR-{code}-{part}-列"
            self._entry("manual", entry_id, f"导出 {code} 的列（{part}）", sources, sql,
                        "旧配置没有 COLUMNS，旧系统按查询结果的全部列导出；无法从 SQL 中确定列名", "没有生成这个导出")
            withheld.append(entry_id)
            return []
        self._note("按旧系统行为取值（MG-10）", f"导出 {code}（{part}）没有 COLUMNS，旧系统按查询结果的全部列导出"
                   "（CustomExportService.java:988），按 SQL 的列名逐列生成，表头为列名")
        return [{"field": n, "header": n} for n in names]


def e_src(row: Row) -> str:
    return src(T_TABLE, row).text()


def _select_aliases(sql: str) -> list[str] | None:
    body = sql.strip()
    start, end = top_keyword(body, "SELECT"), top_keyword(body, "FROM")
    if start < 0 or end < 0:
        return None
    names: list[str] = []
    for item in split_top(body[start + 6:end]):
        quoted = re.search(r'"([^"]+)"\s*$', item)
        if quoted:
            names.append(quoted.group(1))
            continue
        plain = re.search(r"([A-Za-z_][\w$#]*)\s*$", item)
        if not plain:
            return None
        names.append(plain.group(1).upper())
    return names


def emit_lookups(legacy: Legacy, inv: Inventory, registry: Registry) -> None:
    """页面字段用到的 Lookup：列取旧 DISPLAY_COLUMNS，并补上回填用到的列；关键字按全部显示列搜索，与旧系统相同。"""
    for old_code in sorted(registry.lookups):
        row = legacy.lookups[old_code]
        display = [str(c["field"]).upper() for c in load_json(row["DISPLAY_COLUMNS"]) or [] if c.get("field")]
        columns = display + sorted(registry.lookups[old_code] - set(display))
        key = naming.lookup_code(old_code)
        inv.add("lookup", key, row["LOOKUP_NAME"],
                {"table": row["DATA_SOURCE"].upper(), "columns": columns, "keywordColumns": display}, [src(T_LOOKUP, row)])
        headers = [f"{c['field']}：{c.get('header')}" + (f"（宽 {c['width']}）" if c.get("width") else "")
                   for c in load_json(row["DISPLAY_COLUMNS"]) or []]
        inv.entry(Entry("manual", f"MR-LOOKUP-{key}-列标题", "", f"Lookup {key}（{row['LOOKUP_NAME']}）的列标题和列宽",
                        [src(T_LOOKUP, row)], "；".join(headers),
                        "C06 的 Lookup 只有列名，没有列标题和列宽；需要新增能力才能在对话框中显示旧的中文列标题",
                        "按列名生成 columns"))
    inv.note("按旧系统行为取值（MG-10）", "Lookup 的 keywordColumns 取全部显示列（旧后端按 DISPLAY_COLUMNS 逐列 LIKE，"
             "DynamicDataService.java:247）；orderBy 不写（旧查询没有排序）")
