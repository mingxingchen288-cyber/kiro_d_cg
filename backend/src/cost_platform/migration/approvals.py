"""审批流的迁移（C06 第 7 节，MG-03、MG-09）。

只迁移启用的审批流（WF_FLOW_DEF.IS_ENABLED=1，取 WF_FLOW_CONFIG 中的发布版本）。旧审批流的入口条件是对
保存上下文 JSON 的 SQL，不能原样迁移；两种价格同步审批（direction 为 COST_TO_GOODS、GOODS_TO_COST）按
固定写法转换：WRITE_DATA 动作转为影响对象的 updateFields（MG-03），入口条件改由 changedFields 表达，差异列入
审批确认清单。其他审批流不生成，列入人工改写清单和审批确认清单。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .inventory import Entry, Inventory, Source
from .legacy import T_FLOW, T_FLOW_APPROVER, T_FLOW_CONFIG, T_FLOW_NODE, Legacy, split_top, src, top_keyword
from .pages import EntityInfo, Registry

PRICE_DIRECTIONS = ("COST_TO_GOODS", "GOODS_TO_COST")
_OPERATIONS = {"modified": "modify", "added": "add", "deleted": "delete"}
_JSON_TABLE = re.compile(r"JSON_TABLE\(\s*:contextJson\s*,\s*'([^']+)'\s+COLUMNS\s*\((.*?)\)\)\s*([A-Za-z_]\w*)", re.S | re.I)
_JSON_COLUMN = re.compile(r"([A-Za-z_]\w*)\s+[A-Za-z0-9_()]+\s+PATH\s+'([^']+)'", re.I)


def migrate_flows(legacy: Legacy, inv: Inventory, reg: Registry) -> None:
    flows = sorted((f for f in legacy.s[T_FLOW] if f["PAGE_CODE"] in reg.pages),
                   key=lambda f: (f["FLOW_PRIORITY"] or 0, f["FLOW_ID"]))
    retired = [f for f in flows if f["IS_ENABLED"] != 1]
    if retired:
        inv.note("未迁移的旧配置", "停用的旧审批流不迁移：" + "、".join(
            f"{f['FLOW_NAME']}（FLOW_ID={f['FLOW_ID']}，v{f['FLOW_VERSION']}）" for f in retired))
    configs = {r["FLOW_ID"]: r for r in legacy.s[T_FLOW_CONFIG]}
    seq = 0
    for flow in (f for f in flows if f["IS_ENABLED"] == 1):
        cfg = json.loads(configs[flow["FLOW_ID"]]["CONFIG_JSON"])
        if cfg.get("direction") in PRICE_DIRECTIONS:
            seq += 1
            _FlowMigration(legacy, inv, reg, flow, cfg, seq).run()
        else:
            _unconverted(legacy, inv, reg, flow, cfg)
    inv.note("按旧系统行为取值（MG-10）", "审批流不写 notify：旧系统没有消息通知，只有待办和“我发起的”列表"
             "（ApprovalNotificationService.java）")


def _flow_sources(legacy: Legacy, flow: dict[str, Any]) -> list[Source]:
    nodes = [n for n in legacy.s[T_FLOW_NODE] if n["FLOW_ID"] == flow["FLOW_ID"]]
    node_ids = {n["NODE_ID"] for n in nodes}
    return ([src(T_FLOW, flow, "FLOW_ID"), Source(T_FLOW_CONFIG, f"FLOW_ID={flow['FLOW_ID']}")]
            + [src(T_FLOW_NODE, n, "NODE_ID") for n in nodes]
            + [src(T_FLOW_APPROVER, a) for a in legacy.s[T_FLOW_APPROVER] if a["NODE_ID"] in node_ids])


def _unconverted(legacy: Legacy, inv: Inventory, reg: Registry, flow: dict[str, Any], cfg: dict[str, Any]) -> None:
    page = reg.pages[flow["PAGE_CODE"]].code
    sources = _flow_sources(legacy, flow)
    ops = [_OPERATIONS.get(o, o) for o in cfg["trigger"].get("operations", [])]
    inv.entry(Entry("manual", f"MR-FLOW-{flow['FLOW_ID']}-入口条件", page, f"审批流“{flow['FLOW_NAME']}”的入口条件",
                    sources, cfg["trigger"].get("condition", ""),
                    "入口条件是对旧保存上下文 JSON 的 SQL（JSON_VALUE、JSON_EXISTS、:old_* 和 :user_departmentId），"
                    "新平台的 trigger.when 按主表求值、不能逐行判断明细的修改前值，不能自动转换",
                    "没有生成这个审批流"))
    inv.entry(Entry("approval", f"AC-FLOW-{flow['FLOW_ID']}", page, f"审批流“{flow['FLOW_NAME']}”（FLOW_ID={flow['FLOW_ID']}）",
                    sources, json.dumps({"operations": ops, "condition": cfg["trigger"].get("condition")}, ensure_ascii=False),
                    "旧审批流不是价格同步审批，入口条件不能自动转换",
                    "没有生成；迁移后这类保存不再进入审批",
                    scenario=_scenario_71(cfg) if cfg.get("direction") == "NONE" else None))


def _scenario_71(cfg: dict[str, Any]) -> str:
    return ("旧系统：技术中心的用户打开状态为“评估中”的成本单，在原辅料或包材中删除一行“客户指定”的物料，或者把这一行换成"
            "别的物料、改了“客户指定”，保存后进入“管理员审批”，管理员通过后修改才生效。新平台没有这个审批流时，同样的保存"
            "直接生效。要保留，需要在新平台用 trigger 和 when 改写：operations 为 modify、delete，changedFields 为原辅料、包材的"
            "GOODSID、CUSTOMER_SPECIFIED，when 判断 old.USESTATUS == '评估中' 和申请人部门（需要数据项查部门），"
            "“这一行修改前是客户指定”只能按主表求值，无法逐行判断")


class _FlowMigration:
    def __init__(self, legacy: Legacy, inv: Inventory, reg: Registry, flow: dict[str, Any], cfg: dict[str, Any],
                 seq: int) -> None:
        self.l, self.inv, self.reg, self.flow, self.cfg, self.seq = legacy, inv, reg, flow, cfg, seq
        self.page = reg.pages[flow["PAGE_CODE"]]
        self.entities = reg.page_entities(flow["PAGE_CODE"])
        self.master = reg.entities[self.page.master]
        self.key = cfg["direction"]
        self.sources = _flow_sources(legacy, flow)
        self.name = flow["FLOW_NAME"]

    def confirm(self, suffix: str, title: str, original: str, reason: str, handling: str,
                scenario: str | None = None) -> None:
        self.inv.entry(Entry("approval", f"AC-{self.key}-{suffix}", self.page.code, f"审批流“{self.name}”：{title}",
                             self.sources, original, reason, handling, scenario=scenario))

    def run(self) -> None:
        content: dict[str, Any] = {"createdSeq": self.seq, "sourceOperation": self.page.save_operation,
                                   "trigger": self._trigger(), "levels": self._levels()}
        freeze = self._freeze()
        if freeze:
            content["freeze"] = freeze
        content["display"] = self._display()
        content["propagation"] = "end"
        self.inv.add("approvalFlow", self.key, self.name, content, self.sources)
        self.inv.note("编码", f"审批流编码取旧配置的 direction：{self.key}（FLOW_ID={self.flow['FLOW_ID']}，"
                      f"v{self.flow['FLOW_VERSION']}）；createdSeq 按 FLOW_PRIORITY、FLOW_ID 排列")
        for key in ("emptyPolicy", "requireApplicantForSubmit", "decisionMode"):
            if key in self.cfg:
                self.inv.note("转换说明", f"审批流 {self.key} 的 {key}={json.dumps(self.cfg[key])}"
                              + ("：转为影响对象的 selection" if key == "decisionMode" else "：新平台没有对应项，不迁移"))

    # ------------------------------------------------------------ 审批入口

    def _write_actions(self) -> list[dict[str, Any]]:
        return [a for a in self.cfg.get("actions", []) if a.get("enabled", True) and a.get("code") == "WRITE_DATA"]

    def _trigger(self) -> dict[str, Any]:
        trig = self.cfg["trigger"]
        ops = [_OPERATIONS[o] for o in trig.get("operations", ["modified"])]
        changed: dict[str, list[str]] = {}
        for action in self._write_actions():
            table, col = action["valueField"].upper().split(".")
            for e in self.entities:
                if e.table == table and col in e.fields:
                    changed.setdefault(e.code, []).append(col)
        if self.key == "COST_TO_GOODS":
            self.confirm("入口条件", "入口条件", trig.get("condition", ""),
                         "旧条件是 SQL：主表为修改或未改，且原辅料或包材有一行被修改、priceChangeKind 为 PRICE_CHANGED"
                         "（物料编号没变而单价变了，ApprovalCostPreviewService.java:39）。新平台按 changedFields 判断："
                         f"{', '.join(f'{k}.{v[0]}' for k, v in changed.items())} 有变化就触发，换了物料、单价随之变化时也会触发",
                         f"按 operations={ops}、changedFields 生成，SQL 条件不迁移",
                         scenario="成本单 200680 的原辅料明细里，把硬脂酸镁那一行换成另一个物料，Lookup 带出新物料的单价后保存："
                                  "旧系统直接保存，不审批，也不改物料清单；新平台会进入“成本明细改价审批”，管理员通过后把新单价"
                                  "写到新物料在物料清单中的执行价。只改单价、不换物料时两边相同，都进入审批")
        else:
            self.inv.note("转换说明", f"审批流 {self.key} 的旧入口条件（主表被修改且改了 "
                          f"{', '.join(c for v in changed.values() for c in v)}）与 operations={ops}、changedFields 相同，SQL 条件不迁移")
        return {"operations": ops, "changedFields": changed}

    def _levels(self) -> list[dict[str, Any]]:
        by_level: dict[int, list[dict[str, Any]]] = {}
        for entry in self.cfg.get("entries", []):
            if not entry.get("enabled", True):
                continue
            if entry.get("conditionType", "ALWAYS") != "ALWAYS" or entry.get("departmentId") is not None:
                self.confirm(f"入口-{entry['nodeId']}", f"第 {entry['level']} 级“{entry['name']}”的条件",
                             json.dumps(entry, ensure_ascii=False), "入口条件或部门限制不能自动转换", "按总是满足生成")
            approvers = [self._approver(a) for a in entry.get("approvers", [])]
            by_level.setdefault(entry["level"], []).append(
                {"name": entry["name"], "mode": str(entry.get("mode", "OR")).lower(), "approvers": approvers})
        return [{"level": i + 1, "entries": by_level[lv]} for i, lv in enumerate(sorted(by_level))]

    def _approver(self, a: dict[str, Any]) -> dict[str, Any]:
        kind = a.get("type")
        if kind == "ROLE":
            return {"type": "role", "role": self.l.roles[a["roleId"]]["ROLE_CODE"]}
        if kind == "USER":
            return {"type": "user", "userId": str(a["userId"])}
        return {"type": "sql", "sql": a["sql"]}

    # ------------------------------------------------------------ 锁定范围

    def _freeze(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        field_locks: list[str] = []
        detail_tables = {e.table for e in self.entities if e.master is not None}
        for lock in self.cfg.get("locks", []):
            if not lock.get("enabled", True):
                continue
            target = lock["targetTable"].upper()
            s_table, s_col = lock["sourceField"].upper().split(".")
            if lock.get("fields"):
                field_locks.append(f"{lock['key']}：{target} 只锁 {', '.join(lock['fields'])}")
            if s_table == self.master.table and s_col == self.master.pk and target in {self.master.table, *detail_tables}:
                continue  # 触发审批的单据（含明细）总是整单锁定
            targets = self.reg.by_table(lock["pageCode"], target)
            sources = [e for e in self.entities if e.table == s_table and s_col in e.fields]
            doc_master = self.reg.entities[self.reg.pages[lock["pageCode"]].master]
            for s in sources:
                if lock.get("wholeDocument") or any(t.master is not None for t in targets):
                    key_col = next((t.parent_key for t in targets if t.parent_key), doc_master.pk)
                    bind = s_col.lower()
                    out.append({"kind": "sql", "entity": doc_master.code,
                                "sql": f"SELECT DISTINCT {key_col} AS DOC_ID FROM {target} WHERE {s_col} = :{bind}",
                                "binds": {bind: f"{s.code}.{s_col}"}, "recordKeyColumn": "DOC_ID"})
                else:
                    out.extend({"kind": "relationKey", "entity": t.code, "targetKey": s_col,
                                "sourceKey": f"{s.code}.{s_col}", "rows": "changed"} for t in targets)
        if field_locks:
            self.confirm("字段锁定", "只锁部分字段的锁定", "；".join(field_locks),
                         "新平台以单据为单位锁定，没有字段级锁定（C06 7.3）", "锁定整行（整张单据）",
                         scenario=("审批期间，被锁定的物料清单行旧系统只禁止改执行价，名称、规格等其他列仍可修改；"
                                   "新平台整行锁定，审批结束前这一行的任何列都不能改" if self.key == "COST_TO_GOODS" else
                                   "物料清单改价审批期间，旧系统只禁止改这一行的执行价；新平台整行锁定，审批结束前这一行的任何列都不能改"))
        if self.key == "GOODS_TO_COST":
            self.confirm("液体成本单", "影响范围不含液体成本核算", json.dumps(self.cfg.get("locks"), ensure_ascii=False),
                         "旧审批流只锁定、同步成本核算（cost-pinggu）的成本单；C06 7.5 样例还含液体成本核算",
                         "按旧配置生成，只含成本核算",
                         scenario="物料清单中某物料的执行价从 3.50 改为 3.80：成本核算中含这个物料的成本单会被锁定并列给审批人勾选；"
                                  "液体成本核算中含这个物料的成本单不锁定、不同步，通过后单价仍是旧值。要同步液体成本核算，需要另加")
        return out

    # ------------------------------------------------------------ 展示与动作

    def _display(self) -> dict[str, Any]:
        source: dict[str, Any] = {"master": [], "details": []}
        objects: dict[str, dict[str, Any]] = {}
        dropped: list[str] = []
        for view in self.cfg.get("views", []):
            entity = self.reg.by_legacy_code(view["pageCode"], view["tableCode"])
            if entity is None:
                dropped.append(f"{view['key']}（表 {view['tableCode']} 不在迁移的页面中）")
                continue
            if view["region"] == "MASTER":
                source["master"] = self._columns(view, entity, dropped, allow_master=False)
            elif view["region"] == "DETAIL":
                source["details"].append({"title": view["title"], "entity": entity.code, "rows": "changed",
                                          "columns": self._columns(view, entity, dropped, allow_master=False)})
            else:
                objects[entity.code] = view
        affected = self._affected(objects, dropped)
        for action in self.cfg.get("actions", []):
            if not action.get("enabled", True):
                continue
            if action.get("event") != "FLOW_APPROVED":
                self.confirm(f"动作-{action['key']}", f"{action['event']} 时的动作 {action['code']}",
                             json.dumps(action, ensure_ascii=False),
                             "新平台中途某一级通过、驳回和撤回都不执行动作，全部审批节点通过后才生效（approval AP-20）", "不迁移")
            elif action.get("procedure"):
                self.inv.entry(Entry("escape", f"EH-{self.key}-{action['key']}", self.page.code,
                                     f"审批流“{self.name}”的存储过程动作 {action['procedure']}", self.sources,
                                     json.dumps(action, ensure_ascii=False), "审批动作调用存储过程",
                                     "没有生成；默认改写成通用动作，由用户决定"))
            elif action.get("code") not in ("APPLY_PENDING_CHANGE", "WRITE_DATA"):
                self.inv.entry(Entry("manual", f"MR-{self.key}-{action['key']}", self.page.code,
                                     f"审批流“{self.name}”的动作 {action['code']}", self.sources,
                                     json.dumps(action, ensure_ascii=False), "迁移没有覆盖这种动作", "没有生成"))
        self.inv.note("转换说明", f"审批流 {self.key} 的 APPLY_PENDING_CHANGE 是新平台固定的“应用来源单据的修改”，不另生成")
        self.confirm("展示", "审批详情的展示", "；".join(
            f"{v['key']}（{v['title']}，{v['region']}）" for v in self.cfg.get("views", [])),
            "旧展示是对保存上下文 JSON 的 SQL，按 JSON_TABLE 的 PATH 换成实体字段；新平台每列自动显示“修改前 → 修改后”，"
            "不再配置小数位和列宽；来源明细只列新增、修改、删除的行，旧系统还列出因重算而金额变化的未修改行"
            + (f"；不能换成实体字段、没有生成的列：{'；'.join(dropped)}" if dropped else ""),
            "按实体字段生成")
        display: dict[str, Any] = {"source": {k: v for k, v in source.items() if v}}
        if affected:
            display["affected"] = affected
        return display

    def _affected(self, objects: dict[str, dict[str, Any]], dropped: list[str]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for action in self._write_actions():
            v_table, v_col = action["valueField"].upper().split(".")
            m_col = action["matchField"].upper().split(".")[1]
            to = action["writeField"].upper()
            targets = self.reg.by_table(action["pageCode"], action["targetTable"])
            sources = [e for e in self.entities if e.table == v_table and v_col in e.fields]
            if action.get("fallbackField"):
                self._fallback(action, sources, v_col)
            for t in targets:
                view = objects.get(t.code)
                columns = self._columns(view, t, dropped, allow_master=True) if view else []
                mode = self.cfg.get("decisionMode")
                selection = "checked" if mode == "SELECTED" else ("all" if columns else "hidden")
                for s in sources:
                    key = view["key"] if view and len(sources) == 1 else f"{action['key']}.{s.code}"
                    title = view["title"] if view else f"{self.reg.pages[action['pageCode']].title}（{s.row['TABLE_NAME']}）"
                    blocks.append({"key": key, "title": title, "find": self._find(t, s, m_col), "columns": columns,
                                   "selection": selection, "actions": [
                                       {"action": "updateFields", "fieldMapping": [{"from": f"{s.code}.{v_col}", "to": to}]}]})
                if view is None and selection == "hidden":
                    self.confirm(f"影响对象-{t.code}", f"{self.reg.pages[action['pageCode']].title}一块不给审批人看",
                                 json.dumps(action, ensure_ascii=False),
                                 "旧审批流没有这一块的展示，审批人看不到将被修改的行，通过后全部写入；C06 7.4 样例为显示且不能取消（all）",
                                 "按旧行为生成为 hidden（不显示，通过后全部执行）",
                                 scenario="成本单 200680 改了硬脂酸镁的单价并保存后，管理员打开审批详情：旧系统只看到成本单和改了价的"
                                          "明细，看不到要改的物料清单；按旧行为生成时同样看不到，通过后照常把新单价写到物料清单的执行价。"
                                          "如果要像 C06 7.4 那样显示物料清单（货品编号、名称、执行价），需要确认")
        return blocks

    def _find(self, target: EntityInfo, source: EntityInfo, col: str) -> dict[str, Any]:
        if target.master is None:
            return {"kind": "relationKey", "entity": target.code, "targetKey": col, "sourceKey": f"{source.code}.{col}",
                    "rows": "changed"}
        obj = target.read_view or target.table
        bind = col.lower()
        return {"kind": "sql", "entity": target.code,
                "sql": f"SELECT D.{target.parent_key} AS DOC_ID, D.{target.pk} AS DTL_ID FROM {obj} D "
                       f"WHERE D.{col} = :{bind} ORDER BY D.{target.parent_key}, D.{target.pk}",
                "binds": {bind: f"{source.code}.{col}"}, "recordKeyColumn": "DOC_ID", "rowKeyColumns": ["DTL_ID"]}

    def _fallback(self, action: dict[str, Any], sources: list[EntityInfo], col: str) -> None:
        fb = action["fallbackField"].upper().split(".")[1]
        for s in sources:
            vc = self.l.view_columns(s.read_view, s.table).get(col) if s.read_view else None
            if vc and re.search(rf"\b{fb}\b", vc.expression, re.I):
                self.inv.note("转换说明", f"审批流 {self.key} 写入时 {action['valueField']} 为空取 {action['fallbackField']}："
                              f"{s.code}.{col} 经视图 {s.read_view} 读取，已是 {vc.expression}，与旧行为相同")
            else:
                self.inv.entry(Entry("manual", f"MR-{self.key}-{action['key']}-fallback", self.page.code,
                                     f"审批流“{self.name}”写入的备用值", self.sources, json.dumps(action, ensure_ascii=False),
                                     f"{col} 为空时取 {fb}，新平台的 fieldMapping 没有备用值", "按不取备用值生成"))

    def _columns(self, view: dict[str, Any], entity: EntityInfo, dropped: list[str], allow_master: bool) -> list[dict[str, str]]:
        tables = {m.group(3).upper(): (m.group(1), dict((c.upper(), p) for c, p in _JSON_COLUMN.findall(m.group(2))))
                  for m in _JSON_TABLE.finditer(view["sql"])}
        items = _select_items(view["sql"])
        master = entity if entity.master is None else self.reg.entities[entity.master]
        out: list[dict[str, str]] = []
        for c in view["columns"]:
            resolved = None
            for name in (c.get("beforeField"), c.get("afterField"), c.get("field")):
                if name and resolved is None:
                    resolved = _resolve(str(name).upper(), items, tables)
            fld = None
            if resolved:
                root, path = resolved
                owner = master if ("masters" in root or root == "$.master") else entity
                m = re.match(r"^\$\.(?:old|new)\.([A-Za-z_]\w*)$", path)
                fld = m.group(1).upper() if m else (owner.pk if path == "$.id" else None)
                if fld is not None and fld not in owner.fields:
                    fld = None
                if fld is not None and owner is not entity:
                    fld = f"{owner.code}.{fld}" if allow_master else None
            if fld is None:
                dropped.append(f"{view['key']}.{c['field']}（{c['label']}）")
                continue
            out.append({"label": c["label"], "field": fld})
        return out


def _select_items(sql: str) -> dict[str, str]:
    body = sql.strip()
    start, end = top_keyword(body, "SELECT"), top_keyword(body, "FROM")
    items: dict[str, str] = {}
    for item in split_top(body[start + 6:end]):
        m = re.match(r"^(.*\S)\s+([A-Za-z_]\w*)$", item, re.S)
        if m and not m.group(1).rstrip().endswith((".", "(")):
            items[m.group(2).upper()] = m.group(1)
        else:
            items[item.split(".")[-1].upper()] = item
    return items


def _resolve(name: str, items: dict[str, str], tables: dict[str, tuple[str, dict[str, str]]]) -> tuple[str, str] | None:
    expr = items.get(name)
    if expr is None or "||" in expr:
        return None
    for alias, col in re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)", expr):
        table = tables.get(alias.upper())
        if table and col.upper() in table[1]:
            return table[0], table[1][col.upper()]
    return None
