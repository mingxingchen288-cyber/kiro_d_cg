"""旧系统 cmx 的 7 个业务角色迁成 seed 的角色配置（config 的 CF-21，T-CF-14，业务例子 E44；模拟验证）。

用户 2026-10-31："角色你迁移过来"。来源：cmx T_COST_ROLE 121～127 和它们在 T_COST_ROLE_PAGE 中的行（只读查询
`.reports/batch9-20261031/a-roles/q02-角色页面内容.out.txt`），转换规则同 seed 的 role.技术中心.json（C06 v24 第 8 节），
每一项的对照见同目录 `迁移对照.md`。这里核对：整份 seed 能保存（config 保存时的全部校验）；每个角色读到的菜单与旧系统授给它的页面
相同；采购（008）在成本核算、物料清单页的按钮、列、导出与旧策略一致；行权限照旧。
"""

from __future__ import annotations

import pytest

from cost_platform.config.snapshot import Snapshot

from .support import MIGRATED_ROLE_PAGES, Env, seed_drafts

NAMES = {"001": "海外营销中心-商业运营", "002": "海外营销中心-商务", "003": "海外营销中心-项目维护", "005": "海外营销中心-调研",
         "006": "海外营销中心-注册", "007": "生产", "008": "采购"}
"""编码、名称同 cmx T_COST_ROLE 121～127；能访问的页面（MIGRATED_ROLE_PAGES）为 T_COST_ROLE_PAGE 中新平台有的页面，按菜单的顺序。"""
ROLES = {code: (name, list(MIGRATED_ROLE_PAGES[code])) for code, name in NAMES.items()}


@pytest.fixture(scope="module")
def env() -> Env:
    env = Env()
    env.save(seed_drafts())  # 整份 seed 一次保存：角色引用的页面、区域、字段，行权限的 SQL 都经过保存时的校验
    return env


def read(env: Env, role: str) -> Snapshot:
    return env.reader.read(role)


def menu_pages(snapshot: Snapshot) -> list[str]:
    return [c.page_code or "" for m in snapshot.menus() for c in (m.children or [m])]


@pytest.mark.parametrize("code", list(ROLES))
def test_menu_shows_the_pages_the_old_role_had(env: Env, code: str) -> None:
    """E44：左侧菜单只有旧系统授给这个角色的页面（旧 MenuService 按页面权限过滤，目录跟着子页面显示）；
    这些角色都不是管理员，没有配置、系统管理，也没有审计追踪。"""
    name, pages = ROLES[code]
    snapshot = read(env, code)
    assert (snapshot.role().name, snapshot.role().admin) == (name, False)
    assert menu_pages(snapshot) == pages
    assert [m.key for m in snapshot.menus()] == (["cost", "basic"])


def test_purchasing_cost_pinggu_buttons_and_columns(env: Env) -> None:
    """E44：采购（008）在成本核算（旧 cmx T_COST_ROLE_PAGE 338）：有保存、高级查询；主表有新增、复制、由BOM生成明细、保存列配置，
    没有删除（旧策略没有"系统默认按钮:deleteRow"）；主表能改（有保存）。列权限照旧：批量、收率不能改，出厂价(RMB)、
    每批销售额等不显示，每批原料成本照常显示；原料/辅料的每片含量、客户指定不能改。"""
    view = read(env, "008").page_view("COST_PINGGU")
    assert view.system_buttons == ["save", "advancedSearch"]
    assert [b.key for b in view.master.buttons] == ["master:addRow", "master:copyRow", "master:generateFromBom",
                                                     "master:saveGridConfig"]
    assert view.master.can_modify is True
    fields = {f.name: f for f in view.master.fields}
    assert not fields["APEX_PL"].editable and not fields["YIELD"].editable and fields["MEMO"].editable
    assert [n for n in ("OUT_PRICE_RMB", "SALEMONEY", "JGF_BATCH", "OUT_PRICE_F", "Y_SALE") if fields[n].visible] == []
    assert fields["TOTAL_YL"].visible and fields["TOTAL_COST"].visible
    material = next(d for d in view.details if d.entity == "COST_MATERIAL")
    assert [b.key for b in material.buttons] == ["COST_MATERIAL:addRow", "COST_MATERIAL:copyRow", "COST_MATERIAL:deleteRow",
                                                 "COST_MATERIAL:saveGridConfig"]
    flags = {f.name: f.editable for f in material.fields}
    assert (flags["PER_HL"], flags["CUSTOMER_SPECIFIED"], flags["MEMO"]) == (False, False, True)


def test_purchasing_goods_price_and_formoney(env: Env) -> None:
    """E44：采购在物料清单页有"产品选择(按物料)导出"（旧"自定义导出:goods-price-pgoods-export"）、新增、复制，没有删除；
    外币管理有"同步ERP汇率"（旧"外币管理:SYNC_ERP_RATE"）。"""
    snapshot = read(env, "008")
    grant = snapshot.role().pages["GOODS_PRICE_MANAGE"]
    assert "export:goods-price-pgoods-export" in grant.buttons
    assert snapshot.exports("GOODS_PRICE_MANAGE")["goods-price-pgoods-export"].name == "产品选择(按物料)导出"
    view = snapshot.page_view("GOODS_PRICE_MANAGE")
    assert [b.key for b in view.master.buttons] == ["master:addRow", "master:copyRow", "master:saveGridConfig"]
    formoney = snapshot.page_view("FORMONEY_MANAGE")
    assert [b.label for b in formoney.master.buttons] == ["新增", "复制", "保存列配置", "同步ERP汇率"]


def test_row_policies_as_old(env: Env) -> None:
    """行权限照旧（可视化写法原样）；003 在成本核算的"创建人 = 委托转移"去掉：d_cg 的 T_COST_PINGGU 没有 CREATE_BY 列，
    cmx 中满足它的单据 0 行，与其他条件是 OR，能看到的单据不变（CF-21）。采购、生产没有行权限，看全部单据。"""
    sql = {code: {p: (g.rows.sql if g.rows is not None and not isinstance(g.rows, str) else g.rows)
                  for p, g in read(env, code).role().pages.items() if p.startswith("COST_PINGGU")} for code in ROLES}
    assert sql["001"] == {"COST_PINGGU": "USESTATUS = '商业化'", "COST_PINGGU_LQ": "USESTATUS = '商业化'"}
    assert sql["002"] == {"COST_PINGGU": None, "COST_PINGGU_LQ": "USESTATUS = '评估中' OR USESTATUS = '已立项'"}
    assert sql["003"] == {"COST_PINGGU": "USESTATUS = '委托研发' OR USESTATUS = '评估中'",
                          "COST_PINGGU_LQ": "USESTATUS = '委托研发' OR USESTATUS = '委托转移' OR USESTATUS = '评估中'"}
    assert sql["005"] == {"COST_PINGGU": "USESTATUS = '已立项' OR USESTATUS = '自主'",
                          "COST_PINGGU_LQ": "USESTATUS = '已立项' OR USESTATUS = '自主'"}
    assert sql["006"] == {"COST_PINGGU": "USESTATUS = '已立项' OR USESTATUS = '自主'",
                          "COST_PINGGU_LQ": "USESTATUS = '自主' OR USESTATUS = '已立项'"}  # 旧 322 的条件顺序如此
    assert sql["007"] == sql["008"] == {"COST_PINGGU": None, "COST_PINGGU_LQ": None}


def test_production_cannot_change_detail_quantities(env: Env) -> None:
    """生产（007，旧 334）在成本核算：客户名称、客户ID 不显示；原料/辅料的每片含量、额外投料量、备注不能改，包材的每批数量不能改。"""
    view = read(env, "007").page_view("COST_PINGGU")
    master = {f.name: f for f in view.master.fields}
    assert not master["CUSTOMNAME"].visible and not master["CUSTOMID"].visible
    material = {f.name: f.editable for f in next(d for d in view.details if d.entity == "COST_MATERIAL").fields}
    assert (material["PER_HL"], material["EXADD_MATER"], material["MEMO"]) == (False, False, False)
    package = {f.name: f.editable for f in next(d for d in view.details if d.entity == "COST_PACKAGE").fields}
    assert package["BATCH_QTY"] is False
