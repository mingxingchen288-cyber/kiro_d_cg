"""`platform migrate generate` 的入口：读取旧元数据，生成配置项、来源、清单和迁移报告（T-MG-1、T-MG-2）。

调用方式（assembly 接到命令行）::

    from cost_platform.migration import generate
    result = generate(connection_factory, Path(".reports/migration"))

`connection_factory` 为 C08 第 2 节的 `ConnectionFactory`（真实实现 `db_core.legacy.OracleLegacyConnectionFactory`）。
输出目录中的内容见 `write_outputs`；同样的旧数据生成逐字节相同的文件，不含运行时间（MG-01）。
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cost_platform.contracts.types import parse_config_content

from .access import migrate_menu, migrate_roles
from .approvals import migrate_flows
from .inventory import LIST_TITLES, Entry, Inventory, Item, Source
from .legacy import T_COMPONENT, T_EXPORT, T_EXPORT_DETAIL, Legacy, src, top_keyword
from .pages import PageMigration, Registry, emit_lookups
from .snapshot import PAGES, Snapshot, dump_snapshot, read_snapshot

if TYPE_CHECKING:
    from cost_platform.contracts.ports import ConnectionFactory

TYPE_ORDER = ("entity", "page", "operation", "rule", "approvalFlow", "role", "menu", "dict", "lookup", "export")

PROCEDURE_NOTES: dict[str, tuple[str, str]] = {
    "P_COST_BOM_INSERT": (
        "删除这张成本单的全部明细，再按 ERP 的 BOM 树（T_COST_BOM_GOODS_TREE_V、PUB_GOODS_V）插入原辅料和包材明细"
        "（物料、数量、单价、分类等），最后重算这张单据",
        "通用动作中没有新增明细的动作（updateTargets、updateRecords 只更新已有的行），改写不了；可以登记为逃生舱"
        "（写明 procedure 和 writes），或者不迁移"),
    "P_COST_BOM_INSERT_LQ": ("液体成本核算的“由BOM生成明细”，写法同 P_COST_BOM_INSERT", "同 P_COST_BOM_INSERT"),
    "P_PINGGU_COMPUTE_ALL": (
        "不看选中行：把全部成本单明细的单价改为物料表 T_COST_GOODS 的参考价 PRICE（排除产成品、半成品），再逐张重算全部成本单",
        "可以改写成按钮操作：updateRecords 按 GOODSID 找物料清单、把 PRICE 写到明细单价，再 recalculate；但通用动作只处理"
        "选中的单据（C02 第 1 节），旧过程处理全部成本单，范围不同"),
    "P_PINGGU_COMPUTE_ALL_LQ": ("液体成本核算的“同步采购价”，写法同 P_PINGGU_COMPUTE_ALL", "同 P_PINGGU_COMPUTE_ALL"),
}
"""存储过程做什么：d_cg 看不到 cmx 的过程源码（ALL_SOURCE 为 0 行），取自旧项目
D:\\chonggou\\my-project\\sql20260523\\03_program_units.sql（2026-05-23 导出，未核对是否为当前版本）。"""


@dataclass(frozen=True)
class GenerateResult:
    output_dir: Path
    items: dict[str, int]
    lists: dict[str, int]
    withheld: list[str]


@dataclass
class Migration:
    inventory: Inventory
    registry: Registry
    legacy: Legacy


def generate(connection_factory: ConnectionFactory, output_dir: Path | str,
             confirmed_rewrites: Mapping[str, str] | None = None) -> GenerateResult:
    """只读连接 cmx 读取旧元数据，生成到 `output_dir`。

    `confirmed_rewrites`：用户确认过的人工改写，键为人工改写清单的编号，值为改写后的文本（SQL 或行权限 JSON）；
    给出时按确认的文本生成原先暂缓的配置项。
    """
    return generate_from_snapshot(read_snapshot(connection_factory), output_dir, confirmed_rewrites)


def generate_from_snapshot(snapshot: Snapshot, output_dir: Path | str,
                           confirmed_rewrites: Mapping[str, str] | None = None) -> GenerateResult:
    migration = build(snapshot, confirmed_rewrites)
    return write_outputs(Path(output_dir), snapshot, migration)


def build(snapshot: Snapshot, confirmed_rewrites: Mapping[str, str] | None = None) -> Migration:
    legacy = Legacy(snapshot)
    inv = Inventory(confirmed=dict(confirmed_rewrites or {}))
    reg = Registry()
    for old_page in PAGES:
        PageMigration(legacy, inv, reg, old_page).run()
    emit_lookups(legacy, inv, reg)
    _shared_tables(legacy, inv, reg)
    migrate_roles(legacy, inv, reg)
    _escape_entries(inv, reg)
    migrate_menu(legacy, inv, reg)
    migrate_flows(legacy, inv, reg)
    inv.note("编码", "页面编码为旧页面编码转大写、“-”换成“_”；实体编码为旧 TABLE_CODE 的驼峰转大写下划线；保存操作为“页面编码.save”；"
             "Lookup 编码按同样的驼峰规则；字典编码为“实体.字段”；导出编码沿用旧 EXPORT_CODE；计算规则编码为“实体.字段”，"
             "行样式规则为“页面.style.序号”")
    return Migration(inv, reg, legacy)


def _shared_tables(legacy: Legacy, inv: Inventory, reg: Registry) -> None:
    """同一张表对应多个旧实体时，列出区分方式（T-MG-1 验收，交用户确认）。"""
    by_table: dict[str, list[Any]] = {}
    for e in reg.entities.values():
        by_table.setdefault(e.table, []).append(e)
    for table, entities in sorted(by_table.items()):
        if len(entities) < 2:
            continue
        parts = []
        for e in entities:
            text = legacy.views.get(e.read_view or "", "")
            where = top_keyword(text, "WHERE")
            cond = " ".join(text[where + 5:].split()) if where >= 0 else "（没有查询视图，无法区分）"
            parts.append(f"{e.code}（{e.row['TABLE_NAME']}）经 {e.read_view} 读取，条件 {cond}")
        inv.note("同一张表对应多个实体（交用户确认）",
                 f"{'、'.join(e.code for e in entities)} 都写入 {table}，按各自的查询视图区分：{'；'.join(parts)}。"
                 "新增和修改都写这张表；保存后一行出现在哪个明细，由视图条件决定，与旧系统相同（例如在原辅料页签选了"
                 "一个分类为包材的物料，保存后这一行出现在包材页签）。审批流中按明细找行的 SQL 查各自的视图")


def _escape_entries(inv: Inventory, reg: Registry) -> None:
    for page in reg.pages.values():
        for key, info in page.procedure_buttons.items():
            b, e = info["button"], info["entity"]
            proc = b["procedure"]
            what, how = PROCEDURE_NOTES.get(proc, ("d_cg 看不到过程源码", "需要按过程的实际写法判断"))
            roles = "、".join(info["roles"]) or "没有角色"
            inv.entry(Entry(
                "escape", f"EH-{page.code}-{key}", page.code, f"{e.row['TABLE_NAME']}的按钮“{b.get('label')}”（{b.get('action')}）",
                [src(T_COMPONENT, e.component)], json.dumps(b, ensure_ascii=False),
                f"按钮调用存储过程 {proc}：{what}。有这个按钮权限的角色：{roles}",
                "没有生成按钮和操作，角色中也没有这个按钮；默认改写成通用动作，由用户逐条决定", proposal=how,
                scenario=(f"{page.title}页面{'选中一张单据' if b.get('requiresRow') else '（不需要选中行）'}点“{b.get('label')}”："
                          f"旧系统调用 {proc}。不迁移时页面上没有这个按钮；登记为逃生舱时行为与旧系统相同，但写入不经过新平台的"
                          "冻结检查（OP-04）")))


# ============================================================ 输出

def write_outputs(out: Path, snapshot: Snapshot, migration: Migration) -> GenerateResult:
    inv = migration.inventory
    out.mkdir(parents=True, exist_ok=True)
    config_dir = out / "config"
    if config_dir.exists():
        shutil.rmtree(config_dir)
    config_dir.mkdir()
    items = sorted(inv.items.values(), key=lambda i: (TYPE_ORDER.index(i.type), i.key))
    for item in items:
        parse_config_content(item.type, item.content)  # 生成的内容必须能按 C06 解析
        draft = {"type": item.type, "key": item.key, "name": item.name, "content": item.content}
        _write_json(config_dir / f"{item.type}.{item.key}.json", draft)
    _write_json(out / "来源.json", [{"type": i.type, "key": i.key, "name": i.name,
                                    "sources": [{"table": s.table, "key": s.key} for s in i.sources]} for i in items])
    _write_json(out / "清单.json", [_entry_json(e) for e in inv.entries])
    for list_name, title in LIST_TITLES.items():
        _write_text(out / f"{title}.md", _render_list(list_name, title, [e for e in inv.entries if e.list == list_name]))
    _write_text(out / "迁移报告.md", _render_report(inv, items))
    _write_json(out / "业务表清单.json", _business_tables(migration))
    dump_snapshot(snapshot, out / "cmx-snapshot.json")
    counts = {t: sum(1 for i in items if i.type == t) for t in TYPE_ORDER}
    lists = {title: sum(1 for e in inv.entries if e.list == name) for name, title in LIST_TITLES.items()}
    return GenerateResult(out, counts, lists, [f"{t}/{k}（{eid}）" for (t, k), eid in sorted(inv.withheld.items())])


def _write_json(path: Path, data: Any) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _entry_json(e: Entry) -> dict[str, Any]:
    return {"list": e.list, "id": e.id, "page": e.page, "title": e.title,
            "sources": [{"table": s.table, "key": s.key} for s in e.sources], "original": e.original,
            "reason": e.reason, "handling": e.handling, "proposal": e.proposal, "scenario": e.scenario}


def _sources_text(sources: list[Source]) -> str:
    grouped: dict[str, list[str]] = {}
    for s in sources:
        grouped.setdefault(s.table, []).append(s.key)
    return "；".join(f"`{t}` {', '.join(keys)}" for t, keys in grouped.items())


_LIST_INTRO = {
    "manual": "不能原样迁移的 SQL、JS 和公式，以及新平台没有对应配置项的旧配置（MG-02）。没有生成近似配置；"
              "标明“确认后生成”的项，用户确认改写后把编号和改写文本传给 `generate(..., confirmed_rewrites=…)` 重新生成。",
    "escape": "旧按钮和审批动作调用的存储过程（MG-02）。默认改写成通用动作，由用户逐条决定。",
    "approval": "新旧审批规则有差异的审批流（MG-02、MG-09）。",
}


def _render_list(list_name: str, title: str, entries: list[Entry]) -> str:
    lines = [f"# {title}", "", "本文件由 `cost_platform.migration.generator` 生成，同样的旧数据生成同样的内容。", "",
             _LIST_INTRO[list_name], "", f"共 {len(entries)} 项。", ""]
    for e in entries:
        lines += [f"## {e.id} {e.title}", ""]
        if e.page:
            lines.append(f"- 页面：{e.page}")
        lines.append(f"- 来源：{_sources_text(e.sources)}")
        lines.append(f"- 原因：{e.reason}")
        lines.append(f"- 本次处理：{e.handling}")
        if e.scenario:
            lines.append(f"- 场景：{e.scenario}")
        if e.proposal:
            lines += ["- 改写建议：", "", "```text", e.proposal, "```"]
        lines += ["- 原文：", "", "```text", e.original, "```", ""]
    return "\n".join(lines)


_SECTIONS = ("编码", "同一张表对应多个实体（交用户确认）", "按旧系统行为取值（MG-10）", "转换说明（MG-12）", "转换说明（MG-13）", "转换说明（MG-14）", "转换说明",
             "不进实体的列（MG-13）", "未迁移的旧配置（MG-08）", "未迁移的旧配置", "暂缓生成的权限")


def _render_report(inv: Inventory, items: list[Item]) -> str:
    lines = ["# 迁移报告", "", "本文件由 `cost_platform.migration.generator` 生成，同样的旧数据生成同样的内容。旧数据为同目录的 "
             "`cmx-snapshot.json`（只读查询 cmx 得到）。", "", "## 生成的配置项", "",
             "| 类型 | 数量 |", "|---|---|"]
    for t in TYPE_ORDER:
        lines.append(f"| {t} | {sum(1 for i in items if i.type == t)} |")
    lines += ["", "每个配置项一个文件，在 `config/` 下，文件名为“类型.编码.json”；来源（旧表名和行的主键）见 `来源.json`。", ""]
    for i in items:
        lines.append(f"- {i.type} `{i.key}`（{i.name}）：{_sources_text(i.sources)}")
    lines += ["", "## 暂缓生成的配置项", ""]
    if inv.withheld:
        lines += [f"- {t} `{k}`：见人工改写清单 {eid}" for (t, k), eid in sorted(inv.withheld.items())]
    else:
        lines.append("无。")
    sections = list(_SECTIONS) + sorted(s for s in inv.notes if s not in _SECTIONS)
    for section in sections:
        if section in inv.notes:
            lines += ["", f"## {section}", ""] + [f"- {n}" for n in inv.notes[section]]
    lines += ["", "## 清单", ""]
    for name, title in LIST_TITLES.items():
        lines.append(f"- {title}：{sum(1 for e in inv.entries if e.list == name)} 项，见 `{title}.md`")
    return "\n".join(lines) + "\n"


def _business_tables(migration: Migration) -> dict[str, Any]:
    reg = migration.registry
    tables: dict[str, dict[str, Any]] = {}
    views: dict[str, dict[str, Any]] = {}
    for e in reg.entities.values():
        t = tables.setdefault(e.table, {"entities": [], "columns": []})
        t["entities"].append(e.code)
        t["columns"] += [f["column"] for f in e.fields.values() if f["column"] and f["column"] not in t["columns"]]
        if e.read_view:
            views[e.read_view] = {"table": e.table, "entity": e.code, "columns": list(e.fields),
                                  "note": "实体的 readView；d_cg 中按实体字段建立，只基于这张表的列和关联表，"
                                          "不再引用没有复制的列（DELETED、CREATE_*、UPDATE_*、明细上的主表值副本等）"}
    lookups = {}
    for item in migration.inventory.items.values():
        if item.type == "lookup":
            src_obj = item.content["table"]
            lookups.setdefault(src_obj, {"lookups": [], "columns": []})
            lookups[src_obj]["lookups"].append(item.key)
            lookups[src_obj]["columns"] += [c for c in item.content["columns"] if c not in lookups[src_obj]["columns"]]
    exports: dict[str, list[str]] = {}
    legacy = migration.legacy
    for row in legacy.s[T_EXPORT]:
        if row["PAGE_CODE"] not in reg.pages:
            continue
        sqls = [row["MASTER_SQL"]] + [d["DETAIL_SQL"] for d in legacy.s[T_EXPORT_DETAIL] if d["EXPORT_CONFIG_ID"] == row["ID"]]
        for sql in sqls:
            for obj in re.findall(r"\bFROM\s+([A-Za-z_][\w$#]*)", sql, re.I):
                codes = exports.setdefault(obj.upper(), [])
                if row["EXPORT_CODE"] not in codes:
                    codes.append(row["EXPORT_CODE"])
    return {"说明": "迁移后的配置引用的业务表、视图、Lookup 数据源和导出 SQL 中的对象（交 T-DB-3）。tables 的 columns 为实体字段对应的列；"
                    "旧 Lookup 查询都带 DELETED = 0，数据源中不应有已删除的行。",
            "tables": dict(sorted(tables.items())), "views": dict(sorted(views.items())),
            "lookupSources": dict(sorted(lookups.items())),
            "exportObjects": {k: {"exports": v} for k, v in sorted(exports.items())}}
