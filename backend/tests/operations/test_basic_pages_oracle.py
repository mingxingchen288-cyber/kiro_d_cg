"""第 8 批 G1 三个基础资料页的真实验证（d_cg）：产品信息维护、客户信息（含分销商）、外币管理"同步ERP汇率"。

组装同 `test_sql_actions_oracle.py` 的 `Platform`（真实的 db-core、authz、写入管道、operations、approval，配置取
`backend/seed/config` 在内存中生成，不写 PF_CONFIG_ITEM），命令经 `CommandRunner` 执行。admin（系统管理员，三个页面 ["*"]，
同旧系统 T_COST_ROLE_PAGE 的系统管理员）。

测试数据自己建、自己删（不改 d_cg 已有的行）：
- 客户信息：新增客户"PF_TEST 客户甲"和它的分销商"PF_TEST 分销商甲"（一条命令，主表新增、明细新增）；改客户名称后，成本核算
  客户选择的数据源 V_COST_CUSTOMER_LOOKUP 里是新名称；最后删除客户（连同分销商）。
- 产品信息维护：新增产品"PF_TEST 产品甲"，客户选上面的客户（Lookup 回填客户 ID、分销商 ID）；视图 T_COST_GOODS_V 带出
  客户名称、国家、分销商名称，华益代码为 'OV' || 产品ID（本地产品，同 cmx 视图），创建人、修改人为 admin（旧系统新增写
  CREATE_BY、UPDATE_BY = 登录名）；成本核算产品选择 V_COST_GOODS_LOOKUP 里能选到它（BOM 状态"ERP未搭建BOM"）。
- 外币管理：直接在 T_COST_FORMONEY 建两行测试外币（写法同 tests/e2e/sample_two.py 的 CreatedData）：一行 CREATE_BY = 'system'、
  本地汇率 9.99，一行 CREATE_BY = 'PF_TEST'、本地汇率 2.5。点"同步ERP汇率"（旧按钮 SQL：UPDATE T_COST_FORMONEY SET FMRATE =
  NULL … WHERE CREATE_BY = 'system'）：system 的那行本地汇率清空，PF_TEST 的不变；人民币、欧元、英镑、美元 4 行的汇率与
  ERP（CMX.ERP_FORMONEY_V）相同。命令的加锁语句都锁 T_COST_FORMONEY，不对经 ERP 链接的视图 FOR UPDATE。按钮的 SQL 只选本地
  汇率不为空的行（本地汇率本来就为空的行，写成空也不变），所以命令只改了测试外币甲这一行，d_cg 的 4 行外币没有被锁、没有写。

运行：`uv run --with <wheel> pytest -m oracle tests/operations/test_basic_pages_oracle.py`。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, text

from cost_platform.contracts import types as t
from cost_platform.pipeline.tracing import SqlTracer

from .test_sql_actions_oracle import Platform, engine, seed_drafts  # noqa: F401 - fixture

pytestmark = pytest.mark.oracle

D = Decimal
_tracer = SqlTracer()


def _tmp() -> str:
    return f"tmp-{uuid.uuid4()}"


def _run(platform: Platform, page: str, operation: str, documents: list[dict[str, Any]],
         params: dict[str, Any] | None = None) -> t.CommandResult:
    key = str(uuid.uuid4())
    platform.request_keys.append(key)
    command = t.parse_wire(t.Command, {"requestKey": key, "page": page, "operation": operation, "documents": documents,
                                       "params": params or {}})
    return platform.runner.execute(command, platform.config.context())


def _one(engine: Engine, sql: str, **binds: Any) -> dict[str, Any] | None:  # noqa: F811
    with engine.connect() as conn:
        row = conn.execute(text(sql), binds).mappings().first()
        return None if row is None else dict(row)


@pytest.fixture
def platform(engine: Engine) -> Iterator[Platform]:  # noqa: F811
    made = Platform(seed_drafts())
    yield made
    with engine.begin() as conn:
        for key in made.request_keys:
            conn.execute(text("DELETE FROM pf_command WHERE request_key = :k"), {"k": key})
    made.close()


def test_customer_with_distributor_and_product_flow_into_cost_lookups(engine: Engine, platform: Platform) -> None:  # noqa: F811
    customer: str | None = None
    product: str | None = None
    try:
        # 客户信息：新增客户和一个分销商（一次保存）
        saved = _run(platform, "CUSTOMER_MANAGE", "CUSTOMER_MANAGE.save", [{
            "entity": "COST_CUSTOMER",
            "master": {"op": "add", "clientRowId": (master := _tmp()), "values": {"CUSTOMNAME": "PF_TEST 客户甲", "ZONE": "PF_TEST 国家"}},
            "details": [{"entity": "COST_TRANPOSER", "op": "add", "clientRowId": _tmp(), "values": {"TRANPOSNAME": "PF_TEST 分销商甲"}}]}])
        assert saved.outcome == "saved"
        customer = saved.id_map[master]
        tranposer = _one(engine, "SELECT tranposid, iserp FROM t_cost_tranposer WHERE customid = :c", c=int(customer))
        assert tranposer is not None and tranposer["iserp"] == 0
        found = _one(engine, "SELECT customname, country, livery, tranposid FROM v_cost_customer_lookup WHERE customid = :c",
                     c=int(customer))
        assert found == {"customname": "PF_TEST 客户甲", "country": "PF_TEST 国家", "livery": "PF_TEST 分销商甲",
                         "tranposid": tranposer["tranposid"]}

        # 产品信息维护：新增产品，客户经 Lookup 选上面的客户（回填客户 ID、分销商 ID；名称类字段只在视图中，不提交）
        added = _run(platform, "GOODS_MANAGE", "GOODS_MANAGE.save", [{
            "entity": "COST_GOODS",
            "master": {"op": "add", "clientRowId": (row := _tmp()), "values": {
                "GOODSNAME": "PF_TEST 产品甲", "GOODSTYPE": "10mg", "PACKTYPE": "30片/盒", "GOODSNAME_EN": "PF_TEST Product A",
                "ZX_CUSTOMERID": customer, "TRANPOSID": str(tranposer["tranposid"])}},
            "details": []}])
        assert added.outcome == "saved"
        product = added.id_map[row]
        view = _one(engine, "SELECT goodsno, customname, zone, tranposname, iserp, create_by FROM t_cost_goods_v WHERE goodsid = :g",
                    g=int(product))
        assert view == {"goodsno": f"OV{product}", "customname": "PF_TEST 客户甲", "zone": "PF_TEST 国家",
                        "tranposname": "PF_TEST 分销商甲", "iserp": 0, "create_by": "admin"}
        stored = _one(engine, "SELECT useflag, update_by FROM t_cost_goods WHERE goodsid = :g", g=int(product))
        assert stored == {"useflag": "产成品", "update_by": "admin"}
        lookup = _one(engine, "SELECT goodsname, customid, customname, memo, strength, livery FROM v_cost_goods_lookup "
                              "WHERE goodsid = :g", g=int(product))
        assert lookup == {"goodsname": "PF_TEST 产品甲", "customid": D(customer), "customname": "PF_TEST 客户甲",
                          "memo": "ERP未搭建BOM", "strength": "10mg", "livery": "PF_TEST 分销商甲"}

        # 客户信息改客户名称：成本核算的客户选择、产品信息维护都看到新名称；修改不改创建人
        renamed = _run(platform, "CUSTOMER_MANAGE", "CUSTOMER_MANAGE.save", [{
            "entity": "COST_CUSTOMER", "master": {"op": "modify", "rowKey": customer, "changes": {"CUSTOMNAME": "PF_TEST 客户甲（改）"}},
            "details": []}])
        assert renamed.outcome == "saved"
        assert _one(engine, "SELECT customname FROM v_cost_customer_lookup WHERE customid = :c",
                    c=int(customer)) == {"customname": "PF_TEST 客户甲（改）"}
        assert _one(engine, "SELECT customname FROM v_cost_goods_lookup WHERE goodsid = :g",
                    g=int(product)) == {"customname": "PF_TEST 客户甲（改）"}

        # 删除产品；删除客户连同分销商
        assert _run(platform, "GOODS_MANAGE", "GOODS_MANAGE.save", [{
            "entity": "COST_GOODS", "master": {"op": "delete", "rowKey": product}, "details": []}]).outcome == "saved"
        product = None
        assert _run(platform, "CUSTOMER_MANAGE", "CUSTOMER_MANAGE.save", [{
            "entity": "COST_CUSTOMER", "master": {"op": "delete", "rowKey": customer}, "details": []}]).outcome == "saved"
        assert _one(engine, "SELECT COUNT(*) AS n FROM t_cost_tranposer WHERE customid = :c", c=int(customer)) == {"n": 0}
        customer = None
    finally:
        with engine.begin() as conn:
            if product is not None:
                conn.execute(text("DELETE FROM t_cost_goods WHERE goodsid = :g"), {"g": int(product)})
            if customer is not None:
                conn.execute(text("DELETE FROM t_cost_tranposer WHERE customid = :c"), {"c": int(customer)})
                conn.execute(text("DELETE FROM t_cost_customer WHERE customid = :c"), {"c": int(customer)})


@pytest.fixture
def test_currencies(engine: Engine) -> Iterator[tuple[str, str]]:  # noqa: F811
    """两行测试外币：system 建的（同步时清空本地汇率）和 PF_TEST 建的（不动）；结束时删掉。"""
    with engine.begin() as conn:
        keys = [str(conn.execute(text("SELECT t_cost_formoney_seq.NEXTVAL FROM dual")).scalar_one()) for _ in range(2)]
        for key, name, by, rate in ((keys[0], "PF_TEST 外币甲", "system", D("9.99")), (keys[1], "PF_TEST 外币乙", "PF_TEST", D("2.5"))):
            conn.execute(text("INSERT INTO t_cost_formoney (fmid, fmname, fmrate, usestatus, create_by) VALUES (:k, :n, :r, 1, :b)"),
                         {"k": int(key), "n": name, "r": rate, "b": by})
    yield keys[0], keys[1]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM t_cost_formoney WHERE fmid IN (:a, :b)"), {"a": int(keys[0]), "b": int(keys[1])})


def test_sync_erp_rate_clears_system_rates_and_shows_erp_rates(engine: Engine, platform: Platform,  # noqa: F811
                                                               test_currencies: tuple[str, str]) -> None:
    system, other = test_currencies
    assert _one(engine, "SELECT fmrate FROM t_cost_formoney_v WHERE fmid = :k", k=int(system)) == {"fmrate": D("9.99")}
    with _tracer.capture() as trace:
        result = _run(platform, "FORMONEY_MANAGE", "FORMONEY_MANAGE.syncErpRate", [], {"selectedRows": []})
    assert result.outcome == "saved"
    assert [r.row_key for r in result.rows] == [system]
    locks = [s for s in trace.texts if "FOR UPDATE" in s]
    assert locks and all("FROM T_COST_FORMONEY WHERE" in s for s in locks), locks
    assert _one(engine, "SELECT fmrate FROM t_cost_formoney WHERE fmid = :k", k=int(system)) == {"fmrate": None}
    assert _one(engine, "SELECT fmrate FROM t_cost_formoney_v WHERE fmid = :k", k=int(system)) == {"fmrate": None}
    assert _one(engine, "SELECT fmrate FROM t_cost_formoney_v WHERE fmid = :k", k=int(other)) == {"fmrate": D("2.5")}
    with engine.connect() as conn:
        shown = dict(conn.execute(text("SELECT fmid, fmrate FROM t_cost_formoney_v WHERE fmid IN (0, 1, 21, 22)")).all())
        erp = dict(conn.execute(text("SELECT fmid, fmrate FROM cmx.erp_formoney_v WHERE fmid IN (0, 1, 21, 22)")).all())
    assert shown == erp and len(shown) == 4
