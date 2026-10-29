"""求值前按 Lookup 带出没有物理列的字段（`pipeline.lookups`，WP-08 的准备）：新增的行、换了物料的行，计算请求中带上
从 Lookup 的表查出的物料名称和分类（原辅料的每批数量按这两个字段取公式）。

配置按 seed 的成本核算页：原辅料 GOODSID 的 Lookup `costMaterialEffective`（表 T_COST_GOODS_PRICE_V），回填 GOODSNAME、
DTL_USEFLAG←USEFLAG（明细中没有物理列）和 PRICE←ZX_PRICE（有物理列，由前端提交）。support 的原辅料实体在这里补上
DTL_USEFLAG、PER_HL 两个字段。Lookup 的表建在 `Pipeline` 的 SQLite 事务库中，按 d_cg 物料表的名称和分类放三种物料：
68 预胶化淀粉、310 玉米淀粉、115 硬脂酸镁（都是辅料）；查询走真实的 SQL。计算用 rules-core 的替代实现。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeConfigSnapshot

from . import support
from .support import MATERIAL, MATERIAL_ENTITY, MATERIAL_WRITABLE, PAGE, TMP_1, Pipeline, Setup, command, cost_page_view, fld, master_none

LOOKUP = "costMaterialEffective"
FILL = {"GOODSID": "GOODSID", "GOODSNAME": "GOODSNAME", "PRICE": "ZX_PRICE", "DTL_USEFLAG": "USEFLAG"}
MATERIAL_WITH_FLAG = MATERIAL_ENTITY.model_copy(update={"fields": [
    *MATERIAL_ENTITY.fields, fld("DTL_USEFLAG", column=None), fld("PER_HL", "number")]})


class LookupSetup(Setup):
    """成本核算页：原辅料 GOODSID 配物料 Lookup，PER_HL 可写。"""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.permission.set_writable(PAGE, MATERIAL, (*MATERIAL_WRITABLE, "PER_HL"))

    def snapshot(self) -> FakeConfigSnapshot:
        view = cost_page_view(self.audit, self.required)
        fields = support.view_fields(MATERIAL_WITH_FLAG, (*MATERIAL_WRITABLE, "PER_HL"))
        setting = t.LookupSetting(code=LOOKUP, fill=FILL)
        fields = [f.model_copy(update={"lookup": setting}) if f.name == "GOODSID" else f for f in fields]
        view.details[0] = view.details[0].model_copy(update={"fields": fields})
        lookup = t.LookupConfig(table="T_COST_GOODS_PRICE_V", columns=["GOODSID", "GOODSNAME", "ZX_PRICE", "USEFLAG"],
                                keyword_columns=["GOODSID", "GOODSNAME"])
        role = t.RoleConfig(name="成本会计", admin=False, pages={})
        return FakeConfigSnapshot(version=1, role_code="COST_ACCOUNTANT", role=role, page_views={PAGE: view},
                                  entities=support.ENTITIES, operations={support.SAVE: support.save_operation()},
                                  packs={PAGE: self.pack}, rule_fields=self.rule_fields, lookups={LOOKUP: lookup})


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> Pipeline:
    # MemoryStore 按 support.ENTITIES 找实体编码，快照也用它：原辅料换成补了 DTL_USEFLAG、PER_HL 的实体
    monkeypatch.setitem(support.ENTITIES, MATERIAL, MATERIAL_WITH_FLAG)
    found = Pipeline(setup=LookupSetup(rule_fields={PAGE: {
        support.MASTER: frozenset({"APEX_PL"}),
        MATERIAL: frozenset({"GOODSNAME", "DTL_USEFLAG", "PER_HL", "PRICE", "COST_BATCH"})}}))
    with found.factory.engine.begin() as connection:
        connection.execute(text("CREATE TABLE T_COST_GOODS_PRICE_V (GOODSID NUMBER, GOODSNAME VARCHAR2(200), "
                                "ZX_PRICE NUMBER, USEFLAG VARCHAR2(20))"))
        connection.execute(text("INSERT INTO T_COST_GOODS_PRICE_V VALUES (68, '预胶化淀粉', 12.5, '辅料'), "
                                "(310, '玉米淀粉', 22, '辅料'), (115, '硬脂酸镁', 63, '辅料')"))
    return found


def _detail(request: t.EvaluationRequest, key: str) -> t.EvalRow:
    return next(r for r in request.document.details[MATERIAL] if key in (r.row_key, r.client_row_id))


def test_new_material_row_gets_name_and_flag_from_lookup(pipeline: Pipeline) -> None:
    """成本单 1001 新增一行原辅料，只给 GOODSID 310、PER_HL 42.5、PRICE 22：计算请求中这一行带上玉米淀粉、辅料；
    这两个字段不写库，命令结果中能看到名称。"""
    cmd = command([master_none("1001", [{"entity": MATERIAL, "op": "add", "clientRowId": TMP_1,
                                         "values": {"GOODSID": "310", "PER_HL": "42.5", "PRICE": "22"}}])])
    result = pipeline.execute(cmd, pipeline.setup.context())
    [request] = pipeline.setup.engine.requests
    added = _detail(request, TMP_1)
    assert (added.values["GOODSNAME"], added.values["DTL_USEFLAG"]) == ("玉米淀粉", "辅料")
    assert (added.values["PER_HL"], added.values["PRICE"]) == ("42.5", "22")
    [insert] = [w for w in pipeline.store.writes if w.op == "insert"]
    assert "GOODSNAME" not in insert.rows[0] and "DTL_USEFLAG" not in insert.rows[0]
    row = next(r for r in result.rows if isinstance(r, t.ResultRow) and r.client_row_id == TMP_1)
    assert row.values["GOODSNAME"] == "玉米淀粉" and row.values["GOODSID"] == "310"


def test_changed_material_gets_new_name_and_is_recalculated(pipeline: Pipeline) -> None:
    """成本单 1001 的原辅料 5002 物料 116 换成 68、单价不变：规则不读 GOODSID，但读它带出的名称，照样求值；
    计算请求中 5002 带上预胶化淀粉、辅料，没换物料的 5001 仍是视图读到的硬脂酸镁。"""
    cmd = command([master_none("1001", [{"entity": MATERIAL, "op": "modify", "rowKey": "5002", "changes": {"GOODSID": "68"}}])])
    result = pipeline.execute(cmd, pipeline.setup.context())
    [request] = pipeline.setup.engine.requests
    changed = _detail(request, "5002")
    assert (changed.values["GOODSID"], changed.values["GOODSNAME"], changed.values["DTL_USEFLAG"]) == ("68", "预胶化淀粉", "辅料")
    assert _detail(request, "5001").values["GOODSNAME"] == "硬脂酸镁"
    assert [(w.op, w.rows) for w in pipeline.store.writes] == [("update", [{"rowKey": "5002", "GOODSID": Decimal(68)}])]
    row = next(r for r in result.rows if isinstance(r, t.ResultRow) and r.row_key == "5002")
    assert row.values["GOODSNAME"] == "预胶化淀粉"
