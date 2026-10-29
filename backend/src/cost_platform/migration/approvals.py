"""审批流的迁移（C06 第 7 节，MG-03、MG-09）。

只迁移启用的审批流（WF_FLOW_DEF.IS_ENABLED=1，取 WF_FLOW_CONFIG 中的发布版本）。结构按固定写法转换：所属页面、
顺序、审批级别和节点、审批人、或签会签、冻结（旧 locks）、展示数据（旧 views 和“写入数据”动作）。旧的送审条件和
入口条件是解析保存上下文 JSON 的 SQL，不能自动转换：第 1 级的入口条件和审核操作按用户确认的改写生成
（人工改写清单 `MR-FLOW-<FLOW_ID>-入口条件`，确认文本为 JSON：`operations`、`condition`，可选 `department`、`key`），
没有确认时不生成这个审批流。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .inventory import Entry, Inventory, Source
from .legacy import T_FLOW, T_FLOW_APPROVER, T_FLOW_CONFIG, T_FLOW_NODE, Legacy, split_top, src, top_keyword
from .pages import EntityInfo, Registry

PRICE_DIRECTIONS = ("COST_TO_GOODS", "GOODS_TO_COST")
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
    for order, flow in enumerate((f for f in flows if f["IS_ENABLED"] == 1), start=1):
        _FlowMigration(legacy, inv, reg, flow, json.loads(configs[flow["FLOW_ID"]]["CONFIG_JSON"]), order).run()
    inv.note("按旧系统行为取值（MG-10）", "审批流不写 notify：旧系统没有消息通知，只有待办和“我发起的”列表"
             "（ApprovalNotificationService.java）")
    inv.note("编码", "审批流编码：价格同步审批取旧配置的 direction（COST_TO_GOODS、GOODS_TO_COST），其他取确认文本中的 `key`，"
             "没有时为 FLOW_<FLOW_ID>；`order` 按 FLOW_PRIORITY、FLOW_ID 排列")


def _flow_sources(legacy: Legacy, flow: dict[str, Any]) -> list[Source]:
    nodes = [n for n in legacy.s[T_FLOW_NODE] if n["FLOW_ID"] == flow["FLOW_ID"]]
    node_ids = {n["NODE_ID"] for n in nodes}
    return ([src(T_FLOW, flow, "FLOW_ID"), Source(T_FLOW_CONFIG, f"FLOW_ID={flow['FLOW_ID']}")]
            + [src(T_FLOW_NODE, n, "NODE_ID") for n in nodes]
            + [src(T_FLOW_APPROVER, a) for a in legacy.s[T_FLOW_APPROVER] if a["NODE_ID"] in node_ids])


class _FlowMigration:
    def __init__(self, legacy: Legacy, inv: Inventory, reg: Registry, flow: dict[str, Any], cfg: dict[str, Any],
                 order: int) -> None:
        self.l, self.inv, self.reg, self.flow, self.cfg, self.order = legacy, inv, reg, flow, cfg, order
        self.page = reg.pages[flow["PAGE_CODE"]]
        self.entities = reg.page_entities(flow["PAGE_CODE"])
        self.master = reg.entities[self.page.master]
        self.direction = cfg.get("direction")
        self.key = self.direction if self.direction in PRICE_DIRECTIONS else f"FLOW_{flow['FLOW_ID']}"
        self.sources = _flow_sources(legacy, flow)
        self.name = flow["FLOW_NAME"]

    def confirm(self, suffix: str, title: str, original: str, reason: str, handling: str,
                scenario: str | None = None) -> None:
        self.inv.entry(Entry("approval", f"AC-{self.key}-{suffix}", self.page.code, f"审批流“{self.name}”：{title}",
                             self.sources, original, reason, handling, scenario=scenario))

    def run(self) -> None:
        entry = self._entry_condition()
        if entry is None:
            return
        self.key = entry.get("key", self.key)
        content: dict[str, Any] = {"page": self.page.code, "order": self.order, "enabled": True,
                                   "operations": entry["operations"], "levels": self._levels(entry)}
        freeze = self._freeze()
        if freeze:
            content["freeze"] = freeze
        content["display"] = self._display()
        content["propagation"] = "end"
        self.inv.add("approvalFlow", self.key, self.name, content, self.sources)
        for key in ("emptyPolicy", "requireApplicantForSubmit", "decisionMode"):
            if key in self.cfg:
                self.inv.note("转换说明", f"审批流 {self.key} 的 {key}={json.dumps(self.cfg[key])}"
                              + ("：转为受影响单据的 selection" if key == "decisionMode" else "：新平台没有对应项，不迁移"))

    # ------------------------------------------------------------ 审核操作和审批节点

    def _entry_condition(self) -> dict[str, Any] | None:
        trig = self.cfg["trigger"]
        entry_id = f"MR-FLOW-{self.flow['FLOW_ID']}-入口条件"
        confirmed = self.inv.entry(Entry(
            "manual", entry_id, self.page.code, f"审批流“{self.name}”的审核操作和第 1 级入口条件", self.sources,
            json.dumps({"operations": trig.get("operations", []), "condition": trig.get("condition", "")}, ensure_ascii=False),
            "旧条件是解析保存上下文 :contextJson 的 SQL（JSON_VALUE、JSON_EXISTS、priceChangeKind、:old_*、:user_departmentId），"
            "新平台的入口条件逐行执行、直接用 :new_、:old_ 参数（C06 7.2），不能自动转换",
            "没有生成这个审批流；确认改写（审核操作、第 1 级入口条件，JSON）后生成"))
        if confirmed is None:
            return None
        return json.loads(confirmed)

    def _levels(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        by_level: dict[int, list[dict[str, Any]]] = {}
        enabled = [n for n in self.cfg.get("entries", []) if n.get("enabled", True)]
        first_level = min((n["level"] for n in enabled), default=None)
        for node in enabled:
            first = node["level"] == first_level
            out: dict[str, Any] = {"name": node["name"]}
            if first:
                out |= {"conditionType": "sql", "condition": entry["condition"]}
            elif node.get("conditionType", "ALWAYS") == "ALWAYS":
                out["conditionType"] = "always"
            else:
                self.confirm(f"入口-{node['nodeId']}", f"第 {node['level']} 级“{node['name']}”的入口条件",
                             json.dumps(node, ensure_ascii=False), "旧入口条件不能自动转换", "按始终满足生成")
                out["conditionType"] = "always"
            department = entry.get("department") if first else None
            if node.get("departmentId") is not None:
                department = str(node["departmentId"])
            if department is not None:
                out["department"] = department
            out |= {"approvers": [self._approver(a) for a in node.get("approvers", [])],
                    "mode": str(node.get("mode", "OR")).lower()}
            by_level.setdefault(node["level"], []).append(out)
        return [{"level": i + 1, "nodes": by_level[lv]} for i, lv in enumerate(sorted(by_level))]

    def _approver(self, a: dict[str, Any]) -> dict[str, Any]:
        kind = a.get("type")
        if kind == "ROLE":
            return {"type": "role", "role": self.l.roles[a["roleId"]]["ROLE_CODE"]}
        if kind == "USER":
            return {"type": "user", "userId": str(a["userId"])}
        return {"type": "sql", "sql": a["sql"]}

    # ------------------------------------------------------------ 冻结节点

    def _freeze(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        field_locks: list[str] = []
        page_tables = {e.table for e in self.entities}
        for lock in self.cfg.get("locks", []):
            if not lock.get("enabled", True):
                continue
            target = lock["targetTable"].upper()
            s_table, s_col = lock["sourceField"].upper().split(".")
            if lock.get("fields"):
                field_locks.append(f"{lock['key']}：{target} 只锁 {', '.join(lock['fields'])}")
            if target in page_tables and s_table in page_tables:
                continue  # 触发审批的单据（含明细）总是整单冻结
            item = {"table": target, "condition": f"{s_col} = :new_{s_col}"}
            if item not in out:
                out.append(item)
        if field_locks:
            self.confirm("字段锁定", "只锁部分字段的锁定", "；".join(field_locks),
                         "新平台冻结整行或整张单据，没有字段级冻结（C06 7.4）", "冻结整行（注册过的表冻结整张单据）",
                         scenario=("审批期间，被冻结的物料清单行旧系统只禁止改执行价，名称、规格等其他列仍可修改；"
                                   "新平台整行冻结，审批结束前这一行的任何列都不能改" if self.direction == "COST_TO_GOODS" else
                                   "物料清单改价审批期间，旧系统只禁止改这一行的执行价；新平台整行冻结，审批结束前这一行的任何列都不能改"))
        if self.direction == "GOODS_TO_COST":
            self.confirm("液体成本单", "影响范围不含液体成本核算", json.dumps(self.cfg.get("locks"), ensure_ascii=False),
                         "旧审批流只冻结、同步成本核算（cost-pinggu）的成本单；C06 7.10 样例还含液体成本核算",
                         "按旧配置生成，只含成本核算",
                         scenario="物料清单中某物料的执行价从 3.50 改为 3.80：成本核算中含这个物料的成本单会被冻结并列给审批人勾选；"
                                  "液体成本核算中含这个物料的成本单不冻结、不同步，通过后单价仍是旧值。要同步液体成本核算，需要另加")
        return out

    # ------------------------------------------------------------ 展示数据

    def _write_actions(self) -> list[dict[str, Any]]:
        return [a for a in self.cfg.get("actions", []) if a.get("enabled", True) and a.get("code") == "WRITE_DATA"]

    def _display(self) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        objects: dict[str, dict[str, Any]] = {}
        dropped: list[str] = []
        for view in self.cfg.get("views", []):
            entity = self.reg.by_legacy_code(view["pageCode"], view["tableCode"])
            if entity is None:
                dropped.append(f"{view['key']}（表 {view['tableCode']} 不在迁移的页面中）")
                continue
            if view["region"] in ("MASTER", "DETAIL"):
                blocks.append({"key": view["key"], "title": view["title"], "region": view["region"].lower(), "source": entity.code,
                               "columns": self._columns(view, entity, dropped, allow_master=False)})
            else:
                objects[entity.code] = view
        blocks += self._affected(objects, dropped)
        for action in self.cfg.get("actions", []):
            if not action.get("enabled", True):
                continue
            if action.get("event") != "FLOW_APPROVED":
                self.confirm(f"动作-{action['key']}", f"{action['event']} 时的动作 {action['code']}",
                             json.dumps(action, ensure_ascii=False),
                             "新平台中途某一级通过、驳回和撤回都不执行操作，全部审批节点通过后才生效（approval AP-20）", "不迁移")
            elif action.get("procedure"):
                self.inv.entry(Entry("escape", f"EH-{self.key}-{action['key']}", self.page.code,
                                     f"审批流“{self.name}”的存储过程动作 {action['procedure']}", self.sources,
                                     json.dumps(action, ensure_ascii=False), "审批动作调用存储过程",
                                     "没有生成；默认改写成通用的操作，由用户决定"))
            elif action.get("code") not in ("APPLY_PENDING_CHANGE", "WRITE_DATA"):
                self.inv.entry(Entry("manual", f"MR-{self.key}-{action['key']}", self.page.code,
                                     f"审批流“{self.name}”的动作 {action['code']}", self.sources,
                                     json.dumps(action, ensure_ascii=False), "迁移没有覆盖这种动作", "没有生成"))
        self.inv.note("转换说明", f"审批流 {self.key} 的 APPLY_PENDING_CHANGE 是新平台固定的“应用来源单据的修改”，不另生成")
        self.confirm("展示", "审批详情的展示", "；".join(
            f"{v['key']}（{v['title']}，{v['region']}）" for v in self.cfg.get("views", [])),
            "旧展示是对保存上下文 JSON 的 SQL，按 JSON_TABLE 的 PATH 换成实体字段；新平台每列自动显示“修改前 → 修改后”；"
            "来源明细只列新增、修改、删除的行，旧系统还列出因重算而金额变化的未修改行"
            + (f"；不能换成实体字段、没有生成的列：{'；'.join(dropped)}" if dropped else ""),
            "按实体字段生成")
        return blocks

    def _affected(self, objects: dict[str, dict[str, Any]], dropped: list[str]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for action in self._write_actions():
            v_col = action["valueField"].upper().split(".")[1]
            m_col = action["matchField"].upper().split(".")[1]
            value = f":new_{v_col}"
            if action.get("fallbackField"):
                value = f"NVL(:new_{v_col}, :old_{action['fallbackField'].upper().split('.')[1]})"
            for t in self.reg.by_table(action["pageCode"], action["targetTable"]):
                view = objects.get(t.code)
                columns = self._columns(view, t, dropped, allow_master=True) if view else []
                selection = "checked" if self.cfg.get("decisionMode") == "SELECTED" else ("all" if columns else "hidden")
                block: dict[str, Any] = {"key": view["key"] if view else f"{action['key']}.{t.code}",
                                         "title": view["title"] if view else f"{self.reg.pages[action['pageCode']].title}",
                                         "region": "affected", "source": t.read_view or t.table,
                                         "condition": f"{m_col} = :new_{m_col}"}
                if t.read_view:
                    block |= {"targetTable": t.table, "keyColumn": t.pk}
                block |= {"columns": columns, "selection": selection,
                          "actions": [{"action": "updateFields", "fields": [{"column": action["writeField"].upper(), "value": value}]}]}
                blocks.append(block)
                if view is None and selection == "hidden":
                    self.confirm(f"影响对象-{t.code}", f"{self.reg.pages[action['pageCode']].title}一块不给审批人看",
                                 json.dumps(action, ensure_ascii=False),
                                 "旧审批流没有这一块的展示，审批人看不到将被修改的行，通过后全部写入；C06 7.8 样例为显示且不能取消（all）",
                                 "按旧行为生成为 hidden（不显示，通过后全部执行）",
                                 scenario="成本单 2550 改了聚维酮K30 的单价并保存后，管理员打开审批详情：旧系统只看到成本单和改了价的"
                                          "明细，看不到要改的物料清单；按旧行为生成时同样看不到，通过后照常把新单价写到物料清单的执行价")
        return blocks

    def _columns(self, view: dict[str, Any], entity: EntityInfo, dropped: list[str], allow_master: bool) -> list[dict[str, Any]]:
        tables = {m.group(3).upper(): (m.group(1), dict((c.upper(), p) for c, p in _JSON_COLUMN.findall(m.group(2))))
                  for m in _JSON_TABLE.finditer(view["sql"])}
        items = _select_items(view["sql"])
        master = entity if entity.master is None else self.reg.entities[entity.master]
        out: list[dict[str, Any]] = []
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
                    fld = f"master.{fld}" if allow_master else None
            if fld is None:
                dropped.append(f"{view['key']}.{c['field']}（{c['label']}）")
                continue
            column: dict[str, Any] = {"field": fld, "label": c["label"]}
            if c.get("precision") is not None:
                column["precision"] = c["precision"]
            if c.get("width") is not None:
                column["width"] = c["width"]
            out.append(column)
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
