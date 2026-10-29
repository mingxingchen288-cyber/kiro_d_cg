"""新建页面向导（CF-14，T-CF-6 的模拟验证）。用物料清单（视图 T_COST_GOODS_PRICE_V、表 T_COST_GOODS）和成本核算的主从结构生成页面。"""

from __future__ import annotations

from typing import Any

import pytest

from cost_platform.contracts.types import ErrorCode, PlatformError, WizardColumnsRequest, WizardGenerateRequest, parse_wire

from .support import Env, seed_drafts

GOODS = {"entity": "COST_GOODS_PRICE", "name": "物料清单", "table": "T_COST_GOODS", "readView": "T_COST_GOODS_PRICE_V",
         "erpRow": {"column": "ISERP", "value": "1", "localValue": "0"}, "erpColumns": ["GOODSNAME", "PRICE"],
         "labels": {"ZX_PRICE": "执行价"}}


def _request(**changes: Any) -> WizardGenerateRequest:
    body = {"parentMenu": "cost", "pageCode": "GOODS_PRICE_MANAGE", "title": "物料清单及成本", "layout": "single",
            "detailMode": "stack", "audit": False, "master": GOODS, "details": [], **changes}
    return parse_wire(WizardGenerateRequest, body)


@pytest.fixture
def env() -> Env:
    env = Env()
    env.save(seed_drafts())
    env.publisher.events.clear()
    return env


def test_columns_reads_structure_only(env: Env) -> None:
    """读结构：视图的每一列，表中也有的列 inTable 为 true；主键取表的主键；序列已存在。什么都不写。"""
    generation = env.generation()
    found = env.service.wizard_columns(WizardColumnsRequest(read_view="T_COST_GOODS_PRICE_V", table="T_COST_GOODS"))
    assert found.primary_key == "GOODSID"
    assert (found.sequence.name, found.sequence.exists) == ("T_COST_GOODS_SEQ", True)
    columns = {c.name: c for c in found.columns}
    assert len(columns) == 17 and columns["ZX_PRICE"].in_table and columns["ZX_PRICE"].type == "number"
    assert not columns["ROW_CLASS_FLAG"].in_table and columns["CREATE_TIME"].type == "datetime"
    assert env.generation() == generation


def test_generate_single_page(env: Env) -> None:
    """生成的实体、页面、保存操作、菜单和 ADMIN 权限在一个事务中写入，配置代号只加一；字段与视图列一致，视图独有的列只读。"""
    generation = env.generation()
    menu_before = env.stored("menu", "main")
    result = env.service.wizard_generate(_request(), "1")
    assert result.generation == generation + 1 == env.generation()
    assert set(result.versions) == {("entity", "COST_GOODS_PRICE"), ("page", "GOODS_PRICE_MANAGE"),
                                    ("operation", "GOODS_PRICE_MANAGE.save"), ("menu", "main"), ("role", "ADMIN")}
    entity = env.stored("entity", "COST_GOODS_PRICE")
    fields = {f["name"]: f for f in entity["fields"]}
    view_only = {"DELETED", "CREATE_TIME", "UPDATE_TIME", "CREATE_BY", "UPDATE_BY", "ROW_CLASS_FLAG"}
    assert len(fields) == 17 and {n for n, f in fields.items() if f["column"] is None} == view_only
    assert (entity["primaryKey"], fields["GOODSID"]["role"], fields["ZX_PRICE"]["label"]) == ("GOODSID", "system", "执行价")
    page = env.stored("page", "GOODS_PRICE_MANAGE")
    assert (page["audit"], page["detailMode"], page["saveOperation"]) == (False, "stack", "GOODS_PRICE_MANAGE.save")
    assert [b["action"] for b in page["master"]["buttons"]] == ["addRow", "deleteRow", "saveGridConfig"]
    operation = env.stored("operation", "GOODS_PRICE_MANAGE.save")
    assert (operation["kind"], operation["propagation"], operation["impact"]) == ("save", "continue", ["COST_GOODS_PRICE"])
    assert "rowNotFound" not in operation  # 取默认的 skip
    writable = operation["writableFields"]["COST_GOODS_PRICE"]
    assert "GOODSID" not in writable and "ISERP" not in writable and not view_only & set(writable)
    assert {"ZX_PRICE", "PRICE", "GOODSNAME", "USEFLAG"} <= set(writable)  # 有 erpRow：ERP 列在本地行上可写
    menu = env.stored("menu", "main")
    cost = menu["items"][0]
    assert cost["children"][:-1] == menu_before["items"][0]["children"]
    assert cost["children"][-1] == {"key": "GOODS_PRICE_MANAGE", "title": "物料清单及成本", "kind": "page",
                                    "pageCode": "GOODS_PRICE_MANAGE"}
    admin = env.stored("role", "ADMIN")
    assert admin["pages"]["GOODS_PRICE_MANAGE"] == {"buttons": ["*"]}
    assert admin["pages"]["COST_PINGGU"] == {"buttons": ["*"]}
    view = env.reader.read("ADMIN").page_view("GOODS_PRICE_MANAGE")
    assert {f.name for f in view.master.fields if not f.editable} >= view_only | {"GOODSID", "ISERP"}
    assert [e.payload.pages for e in env.publisher.events] == [["GOODS_PRICE_MANAGE"]]


def test_generate_master_detail(env: Env) -> None:
    """主从页：明细关联字段和主键不可写；没有 erpRow 的实体不含 ERP 列。"""
    master = {"entity": "COST_PINGGU2", "name": "成本核算二", "table": "T_COST_PINGGU", "erpColumns": ["GOODSNAME"]}
    detail = {"entity": "COST_MATERIAL2", "name": "原辅料二", "title": "原辅料", "table": "T_COST_PINGGU_DTL",
              "readView": "V_COST_PINGGU_MATERIAL", "parentKey": "DOCID"}
    result = env.service.wizard_generate(_request(pageCode="COST_PINGGU2", title="成本核算二", layout="masterDetail",
                                                  master=master, details=[detail]), "1")
    assert ("entity", "COST_MATERIAL2") in result.versions
    assert env.stored("entity", "COST_PINGGU2")["details"] == [{"entity": "COST_MATERIAL2", "parentKey": "DOCID"}]
    writable = env.stored("operation", "COST_PINGGU2.save")["writableFields"]
    assert "GOODSNAME" not in writable["COST_PINGGU2"] and "DOCID" not in writable["COST_PINGGU2"]
    assert "MEMO" in writable["COST_PINGGU2"]
    assert not {"DTLID", "DOCID", "GOODSNAME", "DTL_USEFLAG"} & set(writable["COST_MATERIAL2"])
    assert {"PRICE", "MEMO", "CUSTOMER_SPECIFIED"} <= set(writable["COST_MATERIAL2"])
    page = env.stored("page", "COST_PINGGU2")
    assert page["details"][0]["title"] == "原辅料" and page["details"][0]["buttons"][0]["label"] == "明细新增"


def _rejected(env: Env, request: WizardGenerateRequest, text: str) -> None:
    generation, records = env.generation(), env.records()
    with pytest.raises(PlatformError) as caught:
        env.service.wizard_generate(request, "1")
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert any(text in (d.message or "") for d in caught.value.details), caught.value.details
    assert env.generation() == generation and env.records() == records


def test_existing_items_are_rejected_and_nothing_written(env: Env) -> None:
    """要新建的实体、页面或保存操作已存在，或菜单、ADMIN 角色中已有这个页面时，返回 422 且什么都不写。"""
    _rejected(env, _request(master={**GOODS, "entity": "COST_PINGGU"}), "实体 COST_PINGGU 已存在")
    _rejected(env, _request(pageCode="COST_PINGGU"), "页面 COST_PINGGU 已存在")


def test_sequence_missing_is_rejected(env: Env) -> None:
    """序列 <表名>_SEQ 不存在时返回 422，提示用户自己建立，什么都不写。"""
    env.sequences.names.discard("T_COST_GOODS_SEQ")
    _rejected(env, _request(), "序列 T_COST_GOODS_SEQ 不存在")
