"""行权限条件、可写字段、来源为审批（AZ-02、AZ-03、AZ-04、AZ-05）。"""

from __future__ import annotations

import pytest

from cost_platform.authz import RolePermissionChecker
from cost_platform.contracts.types import ErrorCode, Origin, PlatformError, SqlCondition, parse_config_content

from .samples import (
    COST_GOODS_PRICE,
    COST_MATERIAL,
    COST_PINGGU,
    GOODS_MANAGE,
    GOODS_PRICE_MANAGE,
    MATERIAL_LOOKUP,
    SAVE,
    context,
    role,
    seed,
    snapshot,
)

checker = RolePermissionChecker()
APPROVAL = Origin(kind="approval", approval_id="203")


# ---------------------------------------------------------------- AZ-03 行权限

def test_visual_row_policy_of_the_selected_role() -> None:
    """技术中心的行权限（cmx 原样的可视化写法）取 `sql`，加括号便于与筛选条件用 AND 组合；只用选定角色的，
    不与 001 的 `USESTATUS = '商业化'` 合并（旧系统多角色用 OR 合并）。"""
    tech = context(snapshot("技术中心"))
    assert checker.row_condition(tech, COST_PINGGU, COST_PINGGU) == SqlCondition(
        sql="(USESTATUS = '评估中' OR USESTATUS = '已立项')", binds={})
    other = context(snapshot("001"))
    assert checker.row_condition(other, COST_PINGGU, COST_PINGGU) == SqlCondition(sql="(USESTATUS = '商业化')", binds={})


def test_row_policy_applies_to_master_only() -> None:
    """行权限只作用于主表，明细随主表。"""
    assert checker.row_condition(context(snapshot("技术中心")), COST_PINGGU, COST_MATERIAL) is None


def test_no_row_policy_is_none() -> None:
    """技术中心在物料清单页、ADMIN 在成本核算页都没有 ROW_POLICY：可以访问全部行。"""
    assert checker.row_condition(context(snapshot("技术中心")), GOODS_PRICE_MANAGE, COST_GOODS_PRICE) is None
    assert checker.row_condition(context(snapshot("ADMIN")), COST_PINGGU, COST_PINGGU) is None


def test_visual_dynamic_value_becomes_bind_variable() -> None:
    """可视化写法中的动态值 `${username}` 换成绑定变量，不拼进 SQL 文本。cmx 现有行权限都是固定值，
    样例取 C06 第 8 节的写法（旧权限界面"当前用户"选项，permission/index.vue:689）。"""
    rows = {"mode": "visual", "logic": "AND", "sql": "CREATE_BY = ${username}",
            "conditions": [{"field": "CREATE_BY", "fieldLabel": "创建人", "op": "eq", "valueType": "dynamic", "value": "${username}"}]}
    ctx = context(snapshot("技术中心", role("技术中心", **{COST_PINGGU: {"rows": rows}})))
    condition = checker.row_condition(ctx, COST_PINGGU, COST_PINGGU)
    assert condition == SqlCondition(sql="(CREATE_BY = :rp_username)", binds={"rp_username": "HY190510"})


def test_custom_sql_row_policy_binds_both_placeholders() -> None:
    """自定义 SQL 写法取整个字符串；`${userId}`、`${username}` 都换成绑定变量（旧权限界面自定义 SQL 的说明，
    permission/index.vue:1600–1610）。"""
    rows = "CREATE_BY = ${username} OR CREATE_USER_ID = ${userId}"
    ctx = context(snapshot("技术中心", role("技术中心", **{COST_PINGGU: {"rows": rows}})))
    condition = checker.row_condition(ctx, COST_PINGGU, COST_PINGGU)
    assert condition == SqlCondition(sql="(CREATE_BY = :rp_username OR CREATE_USER_ID = :rp_user_id)",
                                     binds={"rp_username": "HY190510", "rp_user_id": "381"})
    assert "${" not in condition.sql and "HY190510" not in condition.sql and "381" not in condition.sql


def test_row_condition_on_page_not_in_role_is_denied() -> None:
    """AZ-02：角色配置中没有该页面时不能访问它的列表和单据：技术中心查产品信息维护页返回 403。"""
    with pytest.raises(PlatformError) as caught:
        checker.row_condition(context(snapshot("技术中心")), GOODS_MANAGE, "GOODS")
    assert caught.value.code is ErrorCode.PERMISSION_DENIED


# ---------------------------------------------------------------- AZ-04 可写字段

def test_writable_fields_follow_page_view_and_role_columns() -> None:
    """成本核算主表：保存操作允许写旧系统 EDITABLE=1 的 16 个字段；技术中心的列权限把其中 11 个设为不可编辑。
    原辅料的单价技术中心不可编辑，但它是物料 Lookup 的回填目标，换物料时照样写（E31，见下一个用例）。"""
    admin = context(snapshot("ADMIN"))
    assert checker.writable_fields(admin, COST_PINGGU, COST_PINGGU) == frozenset(
        {"ANNUAL_QTY", "APEX_PL", "P_PERPACK", "S_PERBACK", "PACKTYPE", "X_PERBACK", "M_PERPACK", "USESTATUS", "DOSAGE",
         "YIELD", "OUT_PRICE_F", "COST_PERQP", "MEMO", "FMRATE", "PINGGU_CLASS", "BUSINESS_USER"})
    tech = context(snapshot("技术中心"))
    assert checker.writable_fields(tech, COST_PINGGU, COST_PINGGU) == frozenset({"APEX_PL", "PACKTYPE", "DOSAGE", "YIELD", "MEMO"})
    assert checker.writable_fields(tech, COST_PINGGU, COST_MATERIAL) == frozenset(
        {"GOODSID", "CUSTOMER_SPECIFIED", "PER_HL", "EXADD_MATER", "PRICE", "MEMO"})


def test_lookup_fill_targets_are_writable() -> None:
    """E31：5002 行物料 116 换成 117、单价随回填 70→72。原辅料明细 GOODSID 的 Lookup 回填 GOODSNAME、PRICE 等字段，
    旧前端回填时不看目标列能否编辑、旧后端照样保存，所以回填目标可写（只要保存操作允许写）。

    按迁移 MG-10：GOODSID 配了 Lookup 按可编辑生成，保存操作的 writableFields 加上回填目标（旧虚拟列除外）。"""
    material = seed("entity", COST_MATERIAL)
    defaults = {k: v for k, v in material.field_defaults.items() if k != "GOODSID"}
    material = material.model_copy(update={"field_defaults": defaults})
    save = seed("operation", SAVE)
    writable = dict(save.writable_fields)
    writable[COST_MATERIAL] = ["GOODSID", "GOODSNAME", "DTL_USEFLAG", "CUSTOMER_SPECIFIED", "PRICE", "MEMO"]
    save = parse_config_content("operation", {"label": save.label, "kind": "save", "propagation": "continue",
                                              "writableFields": writable, "impact": save.impact})
    ctx = context(snapshot("技术中心", material=material, save_operation=save,
                           lookups={COST_MATERIAL: {"GOODSID": MATERIAL_LOOKUP}}))
    assert checker.writable_fields(ctx, COST_PINGGU, COST_MATERIAL) == frozenset(
        {"GOODSID", "GOODSNAME", "DTL_USEFLAG", "CUSTOMER_SPECIFIED", "PRICE", "MEMO"})


def test_erp_row_entity_keeps_erp_columns_but_not_erp_row_column() -> None:
    """物料清单（有 erpRow，ISERP=1 为 ERP 行）：ERP 列照样可写，由 write-pipeline 在 ERP 行上按行拒绝；
    ISERP 本身不可写；技术中心的列权限把 PRICE 设为不可编辑。"""
    fields = checker.writable_fields(context(snapshot("技术中心")), GOODS_PRICE_MANAGE, COST_GOODS_PRICE)
    assert fields == frozenset({"GOODSNAME", "USEFLAG", "GOODSTYPE", "PACKTYPE", "FACTORYNAME", "STANDARDTYPE", "ZX_PRICE"})


# ---------------------------------------------------------------- AZ-05 来源为审批

def test_approval_origin_skips_row_policy_and_writable_fields() -> None:
    """来源为审批的写入不检查行权限和可写字段，只拒绝计算字段和 ERP 列（C08 第 7 节）。"""
    ctx = context(snapshot("技术中心"), origin=APPROVAL)
    assert checker.row_condition(ctx, COST_PINGGU, COST_PINGGU) is None
    entity = seed("entity", COST_PINGGU)
    expected = {f.name for f in entity.fields if f.role != "calculated"}
    fields = checker.writable_fields(ctx, COST_PINGGU, COST_PINGGU)
    assert fields == frozenset(expected)
    assert {"USESTATUS", "GOODSID"} <= fields and "TOTAL_COST" not in fields
    goods = checker.writable_fields(ctx, GOODS_PRICE_MANAGE, COST_GOODS_PRICE)
    assert "ISERP" not in goods and {"PRICE", "GOODSNAME", "ZX_PRICE"} <= goods
