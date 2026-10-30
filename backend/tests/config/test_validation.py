"""C06 第 10 节的校验（CF-01，T-CF-1）：每条校验各有通过和不通过的样例。

基础配置是 seed 的成本核算、物料清单、液体成本核算和 C06 7.8～7.10 三个审批流（support.base_world、flow_samples），
已经保存；每个样例在它上面改一两项，经 `POST /api/config/validate` 的同一个入口（`ConfigService.validate`）校验，不写入。
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from cost_platform.contracts.types import ConfigDraft, PackInvalidError

from .support import Env, base_world, draft, flow_samples

WORLD = {(d.type, d.key): d for d in [*base_world(), *flow_samples()]}


def edited(config_type: str, key: str, change: Callable[[dict[str, Any]], Any]) -> ConfigDraft:
    """基础配置中的一项，按 `change` 改过内容。"""
    base = WORLD[(config_type, key)]
    content = copy.deepcopy(base.content)
    change(content)
    return draft(config_type, key, content, base.name)


@pytest.fixture(scope="module")
def env() -> Env:
    env = Env()
    env.save(base_world())
    env.save(flow_samples())
    return env


def problems(env: Env, *items: ConfigDraft) -> list[tuple[str | None, str | None, str | None, str]]:
    return [(d.config_type, d.config_key, d.path, d.message or "") for d in env.service.validate(list(items))]


def assert_rejected(found: list[tuple[str | None, str | None, str | None, str]], path: str, text: str = "") -> None:
    assert any(p == path and text in m for _, _, p, m in found), found


def test_whole_world_passes(env: Env) -> None:
    """通过：基础配置（含三个审批流样例）整体校验没有错误。"""
    assert problems(env, *WORLD.values()) == []


def test_every_page_view_and_pack_generated(env: Env) -> None:
    records = env.records()
    assert {k for k, r in records.items() if r.type == "rulesPack"} == {
        "rulesPack/COST_PINGGU", "rulesPack/COST_GOODS_PRICE", "rulesPack/COST_PINGGU_LQ"}
    assert {k for k, r in records.items() if r.type == "pageView"} == {"pageView/COST_PINGGU|ADMIN"}


# ---------------------------------------------------------------- 引用的实体、字段、操作、页面、审批流、Lookup、字典都存在

GOODS_LOOKUP = draft("lookup", "GOODS", {"table": "T_COST_GOODS", "columns": ["GOODSID", "GOODSNAME"],
                                          "keywordColumns": ["GOODSID", "GOODSNAME"], "orderBy": "GOODSID"})
STATUS_DICT = draft("dict", "USESTATUS", {"items": [{"value": "评估中", "label": "评估中", "order": 1}]})


def _lookup_field(code: str, dict_type: str) -> Callable[[dict[str, Any]], None]:
    def change(c: dict[str, Any]) -> None:
        c["master"]["fields"] = {"GOODSID": {"lookup": {"code": code, "fill": {"GOODSID": "GOODSID", "GOODSNAME": "GOODSNAME"}}},
                                 "USESTATUS": {"dictType": dict_type}}
    return change


def test_references_pass(env: Env) -> None:
    page = edited("page", "COST_PINGGU", _lookup_field("GOODS", "USESTATUS"))
    assert problems(env, page, GOODS_LOOKUP, STATUS_DICT) == []


APPENDED = len(WORLD[("operation", "COST_PINGGU.save")].content["writableFields"]["COST_PINGGU"])
"""保存操作主表 writableFields 末尾追加一项时它的下标。"""


def test_references_rejected(env: Env) -> None:
    found = problems(env, edited("page", "COST_PINGGU", _lookup_field("NO_LOOKUP", "NO_DICT")))
    assert_rejected(found, "master.fields.GOODSID.lookup.code", "Lookup NO_LOOKUP 不存在")
    assert_rejected(found, "master.fields.USESTATUS.dictType", "字典 NO_DICT 不存在")
    found = problems(env, edited("operation", "COST_PINGGU.save", lambda c: c["writableFields"]["COST_PINGGU"].append("NO_FIELD")))
    assert_rejected(found, f"writableFields.COST_PINGGU[{APPENDED}]", "NO_FIELD")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c.update(page="NO_PAGE")))
    assert_rejected(found, "page", "页面 NO_PAGE 不存在")


# ---------------------------------------------------------------- 表和列在数据库中存在

def test_tables_and_columns_rejected(env: Env) -> None:
    found = problems(env, edited("entity", "COST_PINGGU", lambda c: c["fields"][1].update(column="NO_COL")))
    assert_rejected(found, "fields[1].column", "列 NO_COL 不在表 T_COST_PINGGU 中")
    found = problems(env, edited("entity", "COST_PINGGU", lambda c: c.update(table="T_NO_TABLE")))
    assert_rejected(found, "table", "不存在")
    extra = {"name": "NO_VIEW_COL", "column": None, "label": "x", "type": "text", "source": "own", "role": "input"}
    found = problems(env, edited("entity", "COST_MATERIAL", lambda c: c["fields"].append(extra)))
    assert_rejected(found, "readView", "NO_VIEW_COL")
    found = problems(env, draft("lookup", "GOODS", {**GOODS_LOOKUP.content, "columns": ["GOODSID", "SPEC"]}))
    assert_rejected(found, "columns[1]", "SPEC")


# ---------------------------------------------------------------- ERP 列不能设为可写

def _erp_goodsname(c: dict[str, Any]) -> None:
    """成本核算主表的产品名称改成 ERP 列（成本核算主表没有 erpRow）。"""
    next(f for f in c["fields"] if f["name"] == "GOODSNAME")["source"] = "erp"


def test_erp_columns_pass(env: Env) -> None:
    """有 erpRow 的物料清单：ERP 列可以在页面上设为可编辑（本地行、新增行可改）。"""
    page = edited("page", "GOODS_PRICE_MANAGE", lambda c: c["master"].update(fields={"PRICE": {"editable": True}}))
    assert problems(env, page) == []


def test_erp_columns_rejected(env: Env) -> None:
    entity = edited("entity", "COST_PINGGU", _erp_goodsname)
    page = edited("page", "COST_PINGGU", lambda c: c["master"].update(fields={"GOODSNAME": {"editable": True}}))
    assert_rejected(problems(env, entity, page), "master.fields.GOODSNAME.editable", "ERP 列 GOODSNAME")
    operation = edited("operation", "COST_PINGGU.save", lambda c: c["writableFields"]["COST_PINGGU"].append("GOODSNAME"))
    assert_rejected(problems(env, entity, operation), f"writableFields.COST_PINGGU[{APPENDED}]", "ERP 列 GOODSNAME")
    sync = draft("operation", "COST_PINGGU.sync", {
        "label": "同步", "kind": "action", "writableFields": {"COST_PINGGU": ["MEMO", "GOODSNAME"]}, "propagation": "continue",
        "actions": [{"action": "updateTargets", "targets": [{"entity": "COST_PINGGU", "fieldMapping": [
            {"from": "COST_PINGGU.MEMO", "to": "GOODSNAME"}]}]}]})
    found = problems(env, entity, sync)
    assert_rejected(found, "actions[0].targets[0].fieldMapping[0].to", "ERP 列 GOODSNAME")
    found = problems(env, edited("operation", "GOODS_PRICE_MANAGE.save",
                                 lambda c: c["writableFields"]["COST_GOODS_PRICE"].append("ISERP")))
    assert_rejected(found, "writableFields.COST_GOODS_PRICE[1]", "erpRow.column")
    hatch = draft("operation", "GOODS.recalc", {"label": "重算", "kind": "escapeHatch", "procedure": "P_RECALC",
                                                "writes": {"T_COST_GOODS": ["ZX_PRICE", "PRICE"]}, "propagation": "end"})
    assert_rejected(problems(env, hatch), "writes.T_COST_GOODS[1]", "ERP 列")


# ---------------------------------------------------------------- 下层只能收紧可见、可编辑，必填只能增加

def test_layers_pass(env: Env) -> None:
    page = edited("page", "COST_PINGGU", lambda c: c["master"].update(fields={"MEMO": {"editable": False}}))
    role = edited("role", "ADMIN", lambda c: c["pages"]["COST_PINGGU"].update(columns={"master": {"MEMO": {"required": True}}}))
    assert problems(env, page, role) == []


def test_layers_rejected(env: Env) -> None:
    page = edited("page", "COST_PINGGU", lambda c: c["master"].update(fields={"GOODSID": {"editable": True}}))
    assert_rejected(problems(env, page), "master.fields.GOODSID.editable", "只能收紧可编辑")
    page = edited("page", "COST_PINGGU", lambda c: c["master"].update(fields={"MEMO": {"visible": False, "required": True}}))
    role = edited("role", "ADMIN", lambda c: c["pages"]["COST_PINGGU"].update(
        columns={"master": {"MEMO": {"visible": True, "required": False}}}))
    found = problems(env, page, role)
    assert_rejected(found, "pages.COST_PINGGU.columns.master.MEMO.visible", "只能收紧可见")
    assert_rejected(found, "pages.COST_PINGGU.columns.master.MEMO.required", "只能增加必填")


# ---------------------------------------------------------------- formLayout 不越出 24 列，不引用不存在的字段

def _layout(*cells: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    return lambda c: c["master"].update(formLayout=list(cells))


def test_form_layout_pass(env: Env) -> None:
    page = edited("page", "COST_PINGGU", _layout({"field": "GOODSNAME", "x": 0, "y": 0, "w": 12, "h": 1},
                                                {"field": "MEMO", "x": 12, "y": 0, "w": 12, "h": 2}))
    assert problems(env, page) == []


def test_form_layout_rejected(env: Env) -> None:
    found = problems(env, edited("page", "COST_PINGGU", _layout({"field": "MEMO", "x": 12, "y": 0, "w": 13, "h": 1})))
    assert_rejected(found, "master.formLayout[0]", "越出 24 列")
    found = problems(env, edited("page", "COST_PINGGU", _layout({"field": "NO_FIELD", "x": 0, "y": 0, "w": 6, "h": 1})))
    assert_rejected(found, "master.formLayout[0].field", "NO_FIELD")


# ---------------------------------------------------------------- 规则包能编译通过（真实的依赖成环见 test_packs）

MEMO_RULE = draft("rule", "R_MEMO", {"layer": "entity", "target": "COST_PINGGU", "category": "calc", "field": "MEMO", "order": 1,
                                     "expression": "GOODSNAME"})


def test_pack_compiles_pass(env: Env) -> None:
    """新规则和 seed 的 17 条计算规则一起编进成本核算的规则包（按规则编码排列）。"""
    assert problems(env, MEMO_RULE) == []
    assert env.engine.packs[-1].pack.pack_id == "COST_PINGGU"
    seed_rules = [key for config_type, key in WORLD if config_type == "rule"]
    assert [r.id for r in env.engine.packs[-1].pack.rules] == sorted([*seed_rules, "R_MEMO"])


def test_pack_compile_failure_rejected(env: Env) -> None:
    env.engine.fail("load_pack", PackInvalidError("计算规则的依赖成环：R_A → R_B → R_A"))
    found = problems(env, MEMO_RULE)
    assert_rejected(found, None, "规则包 COST_PINGGU 不能编译：计算规则的依赖成环")


# ---------------------------------------------------------------- 关联 SQL、数据项 SQL、导出 SQL

def _sync_price(sql: str, rows: str | None = None, find: dict[str, Any] | None = None) -> ConfigDraft:
    """物料清单页的按钮：按关联 SQL 找含这个物料的成本单明细，写单价（C06 6.1 的例子）。"""
    finder = find or {"kind": "sql", "entity": "COST_MATERIAL", "sql": sql, "binds": {"goodsId": "COST_GOODS_PRICE.GOODSID"},
                      "recordKeyColumn": "DOC_ID", "rowKeyColumns": ["DTL_ID"]}
    return draft("operation", "GOODS_PRICE_MANAGE.syncPrice", {
        "label": "同步价格", "kind": "action", "writableFields": {"COST_MATERIAL": ["PRICE"]}, "impact": ["COST_MATERIAL"],
        "propagation": "end",
        "actions": [{"action": "updateRecords", "find": finder,
                     "fieldMapping": [{"from": "COST_GOODS_PRICE.ZX_PRICE", "to": "PRICE"}]}]})


RELATED = "SELECT D.DOCID AS DOC_ID{extra} FROM T_COST_PINGGU_DTL D WHERE D.GOODSID = :goodsId ORDER BY D.DOCID"


def test_related_sql_pass(env: Env) -> None:
    assert problems(env, _sync_price(RELATED.format(extra=", D.DTLID AS DTL_ID"))) == []


def test_related_sql_missing_row_key_column_rejected(env: Env) -> None:
    """C06 第 10 节的例子：rowKeyColumns 填了 DTL_ID 而 SQL 没有选出这一列时，拒绝保存，提示缺少的列。"""
    found = problems(env, _sync_price(RELATED.format(extra="")))
    assert_rejected(found, "actions[0].find.sql", "关联 SQL 的结果缺少列：DTL_ID")
    found = problems(env, _sync_price(RELATED.format(extra=", D.DTLID AS DTL_ID") + "; DELETE FROM T_COST_GOODS"))
    assert_rejected(found, "actions[0].find.sql", "只能是一条查询语句")


def test_bom_sql_selecting_a_calculated_field_rejected(env: Env) -> None:
    """C06 第 10 节的例子（v18）：seed 的"由BOM生成明细"能保存（`test_whole_world_passes`）；SQL 多选了 BATCH_QTY
    （每批数量，计算字段）时拒绝保存，提示这一列由计算规则得出。"""
    def change(c: dict[str, Any]) -> None:
        c["actions"][0]["sql"] = c["actions"][0]["sql"].replace("F.PRICE AS PRICE", "F.PRICE AS PRICE, 0 AS BATCH_QTY")
    found = problems(env, edited("operation", "COST_PINGGU.generateFromBom", change))
    assert_rejected(found, "actions[0].sql", "BATCH_QTY 是计算字段，由计算规则得出")


DATA_RULE = {"layer": "entity", "target": "COST_MATERIAL", "category": "calc", "field": "PRICE", "order": 5,
             "expression": "data.price", "dataItems": [{"name": "price", "sql": "SELECT NVL(ZX_PRICE, PRICE) AS P FROM T_COST_GOODS "
                                                       "WHERE GOODSID = :goodsId", "binds": {"goodsId": "GOODSID"}}]}


def test_data_item_sql(env: Env) -> None:
    assert problems(env, draft("rule", "R_PRICE", DATA_RULE)) == []
    broken = copy.deepcopy(DATA_RULE)
    broken["dataItems"][0]["sql"] = "UPDATE T_COST_GOODS SET PRICE = 0"
    assert_rejected(problems(env, draft("rule", "R_PRICE", broken)), "dataItems[0].sql", "只能是一条查询语句")


def test_export_sql(env: Env) -> None:
    """C06 第 9 节的导出样例能保存；导出 SQL 的结果缺少 keyColumn 时拒绝。"""
    from .support import doc_json

    sample = doc_json("C06", 13)
    assert problems(env, draft("export", "cost-pinggu-export", sample)) == []
    sample["master"]["keyColumn"] = "NO_KEY"
    assert_rejected(problems(env, draft("export", "cost-pinggu-export", sample)), "master.sql", "缺少 keyColumn NO_KEY")


# ---------------------------------------------------------------- 审批流的 SQL 片段

def _entry(condition: str) -> Callable[[dict[str, Any]], None]:
    return lambda c: c["levels"][0]["nodes"][0].update(condition=condition)


def test_flow_fragments_rejected(env: Env) -> None:
    good = WORLD[("approvalFlow", "COST_TO_GOODS")].content["levels"][0]["nodes"][0]["condition"]
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", _entry(good + "; DELETE FROM T_COST_GOODS")))
    assert_rejected(found, "levels[0].nodes[0].condition", "不能有分号")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS",
                                 _entry(":new_PRICE > (SELECT NO_SUCH_COLUMN FROM T_COST_GOODS WHERE GOODSID = :new_GOODSID)")))
    assert_rejected(found, "levels[0].nodes[0].condition", "数据库解析不通过：列不存在或写法不对：NO_SUCH_COLUMN")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", _entry("DECODE(:new_PRICE, :old_PRICE, 0, 1) = 1 AND")))
    assert_rejected(found, "levels[0].nodes[0].condition", "SQL 语法错误")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", _entry(":new_NO_FIELD = 1")))
    assert_rejected(found, "levels[0].nodes[0].condition", ":new_NO_FIELD")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", _entry(":row_PRICE = 1")))
    assert_rejected(found, "levels[0].nodes[0].condition", ":row_PRICE")
    found = problems(env, edited("approvalFlow", "TECH_CUSTOMER_MATERIAL", _entry(":master_old_NO_FIELD = '评估中'")))
    assert_rejected(found, "levels[0].nodes[0].condition", ":master_old_NO_FIELD")


def test_flow_value_fragment_with_row_and_params_passes(env: Env) -> None:
    """取值可以用 `:row_列名`（修改表这一行的当前值）和 `:params_名称`。"""
    def change(c: dict[str, Any]) -> None:
        c["params"] = [{"name": "rate", "label": "比例", "type": "number", "source": "constant", "required": True, "value": 1}]
        c["display"][3]["actions"][0]["fields"][0]["value"] = "NVL(:new_PRICE, :row_ZX_PRICE) * :params_rate"
    assert problems(env, edited("approvalFlow", "COST_TO_GOODS", change)) == []


# ---------------------------------------------------------------- 审批流的所属页面和审核操作

def test_flow_operations_rejected(env: Env) -> None:
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c.update(operations={"COST_GOODS_PRICE": ["modify"]})))
    assert_rejected(found, "operations.COST_GOODS_PRICE", "不是页面 COST_PINGGU 的主表实体或明细实体")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c.update(operations={"COST_MATERIAL": []})))
    assert_rejected(found, "operations", "至少一个表格要选一项审核操作")
    entity = edited("entity", "COST_MATERIAL", lambda c: c.update(freezable=False))
    assert_rejected(problems(env, entity), "operations.COST_MATERIAL", "freezable 为 false")


# ---------------------------------------------------------------- 审批流的级别、节点、审批人、部门

def test_flow_levels_rejected(env: Env) -> None:
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c["levels"][1].update(level=3)))
    assert_rejected(found, "levels[1].level", "从 1 开始连续")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c["levels"][1].update(nodes=[])))
    assert_rejected(found, "levels[1].nodes", "至少要有一个节点")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c["levels"][0]["nodes"][0].update(approvers=[])))
    assert_rejected(found, "levels[0].nodes[0].approvers", "至少要有一个审批人")
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c["levels"][0]["nodes"][0].pop("condition")))
    assert_rejected(found, "levels[0].nodes[0].condition", "必须写 condition")
    found = problems(env, edited("approvalFlow", "TECH_CUSTOMER_MATERIAL",
                                 lambda c: c["levels"][0]["nodes"][0].update(department="9999")))
    assert_rejected(found, "levels[0].nodes[0].department", "部门 9999 不存在")


# ---------------------------------------------------------------- 冻结表

def _freeze(table: str) -> Callable[[dict[str, Any]], None]:
    return lambda c: c["freeze"].__setitem__(0, {"table": table, "condition": "GOODSID = :new_GOODSID", "enabled": True})


def test_freeze_table_rejected(env: Env) -> None:
    assert_rejected(problems(env, edited("approvalFlow", "COST_TO_GOODS", _freeze("T_COST_GOODS_PRICE_V"))),
                    "freeze[0].table", "是视图")
    assert_rejected(problems(env, edited("approvalFlow", "COST_TO_GOODS", _freeze("PF_COMMAND"))),
                    "freeze[0].table", "平台自己的表")
    entity = edited("entity", "COST_GOODS_PRICE", lambda c: c.update(freezable=False))
    flow = edited("approvalFlow", "COST_TO_GOODS", _freeze("T_COST_GOODS"))
    assert_rejected(problems(env, entity, flow), "freeze[0].table", "freezable 为 false，不能冻结")


def test_freeze_unregistered_table_passes(env: Env) -> None:
    """冻结表可以不在平台注册（C06 7.4）。"""
    flow = edited("approvalFlow", "COST_TO_GOODS", lambda c: c["freeze"].append(
        {"table": "T_CT_GOODS", "condition": "GOODSID = :new_GOODSID", "enabled": True}))
    assert problems(env, flow) == []


# ---------------------------------------------------------------- 展示数据

def _block(index: int, **changes: Any) -> Callable[[dict[str, Any]], None]:
    def change(c: dict[str, Any]) -> None:
        for key, value in changes.items():
            if value is None:
                c["display"][index].pop(key, None)
            else:
                c["display"][index][key] = value
    return change


def test_display_rejected(env: Env) -> None:
    flow = "COST_TO_GOODS"
    cases = [
        (_block(1, key="cost"), "display[1].key", "重复"),
        (_block(0, source="COST_MATERIAL"), "display[0].source", "主表实体 COST_PINGGU"),
        (_block(1, source="COST_GOODS_PRICE"), "display[1].source", "明细实体"),
        (_block(0, selection="all"), "display[0]", "不写 targetTable"),
        (_block(3, condition=None), "display[3].condition", "必须写 condition"),
        (_block(3, selection=None), "display[3].selection", "必须写 selection"),
        (_block(3, targetTable=None), "display[3]", "必须写 targetTable 和 keyColumn"),
        (_block(3, targetTable="PF_COMMAND"), "display[3].targetTable", "平台自己的表"),
        (_block(3, keyColumn="NO_KEY"), "display[3].keyColumn", "NO_KEY"),
        (_block(3, columns=[{"field": "NO_COL", "label": "x"}]), "display[3].columns[0].field", "NO_COL"),
        (_block(3, columns=[{"field": "GOODSID", "label": "x", "targetColumn": "NO_COL"}]), "display[3].columns[0].targetColumn",
         "NO_COL"),
    ]
    for change, path, text in cases:
        assert_rejected(problems(env, edited("approvalFlow", flow, change)), path, text)


def test_display_master_columns_and_protected_columns_rejected(env: Env) -> None:
    unregistered = {"key": "ct", "title": "未注册的表", "region": "affected", "source": "T_CT_GOODS",
                    "condition": "GOODSID = :new_GOODSID", "columns": [{"field": "master.DOCID", "label": "单据号"}],
                    "selection": "checked", "actions": []}
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c["display"].append(unregistered)))
    assert_rejected(found, "display[4].columns[0].field", "没有在平台注册，不能用 master. 列")

    def calculated(c: dict[str, Any]) -> None:
        c["display"][1]["actions"][0]["fields"][0]["column"] = "COST_BATCH"
    found = problems(env, edited("approvalFlow", "GOODS_TO_COST", calculated))
    assert_rejected(found, "display[1].actions[0].fields[0].column", "COST_BATCH 是计算字段")

    def insert_platform(c: dict[str, Any]) -> None:
        c["display"][1]["actions"].append({"action": "insertRows", "table": "PF_COMMAND",
                                           "fields": [{"column": "STATUS", "value": "'x'"}]})
    found = problems(env, edited("approvalFlow", "GOODS_TO_COST", insert_platform))
    assert_rejected(found, "display[1].actions[1].table", "平台自己的表")


def test_display_unregistered_table_passes(env: Env) -> None:
    """展示表可以不在平台注册，`source` 是表时省略 targetTable、keyColumn（取表的主键）。"""
    block = {"key": "ct", "title": "未注册的表", "region": "affected", "source": "T_CT_GOODS", "condition": "GOODSID = :new_GOODSID",
             "columns": [{"field": "NAME", "label": "名称"}], "selection": "hidden",
             "actions": [{"action": "updateFields", "fields": [{"column": "PRICE", "value": ":new_PRICE"}]},
                         {"action": "insertRows", "table": "T_CT_GOODS", "fields": [{"column": "NAME", "value": ":row_NAME"}]}]}
    assert problems(env, edited("approvalFlow", "COST_TO_GOODS", lambda c: c["display"].append(block))) == []


# ---------------------------------------------------------------- 区域按钮

def _buttons(*buttons: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    return lambda c: c["master"].update(buttons=list(buttons))


def test_buttons_pass(env: Env) -> None:
    page = edited("page", "GOODS_PRICE_MANAGE", _buttons(
        {"action": "addRow", "label": "新增"}, {"action": "copyRow", "label": "复制"},
        {"action": "syncPrice", "label": "同步价格", "operation": "GOODS_PRICE_MANAGE.syncPrice", "requiresSelection": True}))
    assert problems(env, page, _sync_price(RELATED.format(extra=", D.DTLID AS DTL_ID"))) == []


def test_buttons_rejected(env: Env) -> None:
    found = problems(env, edited("page", "GOODS_PRICE_MANAGE", _buttons({"action": "copyRow", "label": "复制", "requiresSelection": True})))
    assert_rejected(found, "master.buttons[0]", "内置动作 copyRow 不能写 operation 和 requiresSelection")
    found = problems(env, edited("page", "GOODS_PRICE_MANAGE", _buttons(
        {"action": "syncPrice", "label": "同步价格", "operation": "GOODS_PRICE_MANAGE.save"})))
    assert_rejected(found, "master.buttons[0]", "必须写 operation 和 requiresSelection")


# ---------------------------------------------------------------- updateRecords 按关联键查找时 rows 只能为 all

def test_relation_key_rows(env: Env) -> None:
    finder = {"kind": "relationKey", "entity": "COST_MATERIAL", "targetKey": "GOODSID", "sourceKey": "COST_GOODS_PRICE.GOODSID",
              "rows": "all"}
    assert problems(env, _sync_price("", find=finder)) == []
    found = problems(env, _sync_price("", find={**finder, "rows": "changed"}))
    assert_rejected(found, "actions[0].find.rows", "rows 只能为 all")


# ---------------------------------------------------------------- approvalRequired 至少有一个启用的审批流

def _required(pages: list[str]) -> Callable[[dict[str, Any]], None]:
    rule = {"fields": ["ZX_PRICE"], "when": {"logic": "AND", "conditions": [{"field": "ISERP", "op": "eq", "value": "1"}]},
            "sourcePages": pages}
    return lambda c: c.update(approvalRequired=[rule])


def test_approval_required(env: Env) -> None:
    """E25 的物料表规则：sourcePages 中的物料清单有启用的审批流（C06 7.10）时通过，没有时拒绝。"""
    assert problems(env, edited("entity", "COST_GOODS_PRICE", _required(["GOODS_PRICE_MANAGE"]))) == []
    found = problems(env, edited("entity", "COST_GOODS_PRICE", _required(["COST_PINGGU_LQ"])))
    assert_rejected(found, "approvalRequired[0].sourcePages", "没有启用的审批流")


# ---------------------------------------------------------------- 序列 <表名>_SEQ 必须已经存在

def test_sequence_must_exist(env: Env) -> None:
    entity = WORLD[("entity", "COST_PINGGU_LQ")]
    assert problems(env, entity) == []
    env.sequences.names.discard("T_COST_PINGGU_LQ_SEQ")
    try:
        assert_rejected(problems(env, entity), "table", "序列 T_COST_PINGGU_LQ_SEQ 不存在")
    finally:
        env.sequences.names.add("T_COST_PINGGU_LQ_SEQ")


# ---------------------------------------------------------------- 审批人 SQL、compare.source、人工参数的级别

def _approver(sql: str) -> Callable[[dict[str, Any]], None]:
    return lambda c: c["levels"][0]["nodes"][0].update(
        approvers=[{"type": "sql", "sql": sql, "binds": {"goodsId": "GOODSID"}}])


def test_approver_sql(env: Env) -> None:
    ok = "SELECT GOODSID AS USER_ID FROM T_COST_GOODS WHERE GOODSID = :goodsId"
    assert problems(env, edited("approvalFlow", "COST_TO_GOODS", _approver(ok))) == []
    found = problems(env, edited("approvalFlow", "COST_TO_GOODS", _approver("UPDATE T_COST_GOODS SET PRICE = 0")))
    assert_rejected(found, "levels[0].nodes[0].approvers[0].sql", "只能是一条查询语句")


def _compare(source: str) -> Callable[[dict[str, Any]], None]:
    def change(c: dict[str, Any]) -> None:
        field = next(f for f in c["fields"] if f["name"] == "ZX_PRICE")
        field["compare"] = {"mode": "query", "source": source, "keys": [{"current": "GOODSID", "compare": "GOODSID"}],
                            "field": "PRICE", "format": "percent"}
    return change


def test_compare_source(env: Env) -> None:
    assert problems(env, edited("entity", "COST_GOODS_PRICE", _compare("T_COST_GOODS_PRICE_V"))) == []
    assert problems(env, edited("entity", "COST_GOODS_PRICE", _compare("SELECT GOODSID, PRICE FROM T_COST_GOODS"))) == []
    found = problems(env, edited("entity", "COST_GOODS_PRICE", _compare("DELETE FROM T_COST_GOODS")))
    assert_rejected(found, "fields[3].compare.source", "只能是一条查询语句")


def test_manual_param_level(env: Env) -> None:
    def params(level: int) -> Callable[[dict[str, Any]], None]:
        return lambda c: c.update(params=[{"name": "effectiveDate", "label": "生效日期", "type": "date", "source": "manual",
                                           "required": True, "level": level}])
    assert problems(env, edited("approvalFlow", "COST_TO_GOODS", params(2))) == []
    assert_rejected(problems(env, edited("approvalFlow", "COST_TO_GOODS", params(3))), "params[0].level", "不是本审批流已有的级别")


# ---------------------------------------------------------------- 行权限（C06 第 8 节）

def _rows(rows: Any) -> Callable[[dict[str, Any]], None]:
    return lambda c: c["pages"]["COST_PINGGU"].update(rows=rows)


def test_row_policy(env: Env) -> None:
    visual = {"mode": "visual", "logic": "AND", "conditions": [
        {"field": "BUSINESS_USER", "fieldLabel": "商务人员", "op": "eq", "valueType": "dynamic", "value": "${username}"}],
        "sql": "BUSINESS_USER = ${username}"}
    assert problems(env, edited("role", "ADMIN", _rows(visual))) == []
    assert problems(env, edited("role", "ADMIN", _rows("BUSINESS_USER = ${username} OR MEMO = ${userId}"))) == []
    found = problems(env, edited("role", "ADMIN", _rows("BUSINESS_USER = ${username}; DELETE FROM T_COST_PINGGU")))
    assert_rejected(found, "pages.COST_PINGGU.rows", "不能含分号和数据修改语句")
    found = problems(env, edited("role", "ADMIN", _rows("NO_COL = ${username}")))
    assert_rejected(found, "pages.COST_PINGGU.rows", "列不存在或写法不对")


# ---------------------------------------------------------------- C06 正文的其他样例

def test_c06_rule_samples_can_be_saved(env: Env) -> None:
    """C06 第 5 节的两条规则：包材批量的计算规则（成本核算），ERP 物料整行不能编辑的界面规则（物料管理页）。"""
    from .support import doc_json

    calc = doc_json("C06", 4)
    ui = doc_json("C06", 5)
    page = draft("page", "GOODS_MANAGE", {**WORLD[("page", "GOODS_PRICE_MANAGE")].content, "title": "物料管理"})
    assert problems(env, draft("rule", "R_PKG_BATCH_QTY", calc), draft("rule", "R_GOODS_ERP_LOCK", ui), page) == []


def test_c06_menu_and_dict_samples_can_be_saved(env: Env) -> None:
    from .support import doc_json

    assert problems(env, draft("menu", "main", doc_json("C06", 10)), draft("dict", "STATUS", doc_json("C06", 11))) == []
