"""产品信息维护页保存的 SQL 条数（WP-10、WP-03 的例外）的真实验证（d_cg），用 SQL 追踪统计（计数口径同
`test_oracle_goods_save_sql_count.py`）。

产品信息维护的读取视图 T_COST_GOODS_V 关联客户、分销商表（`SchemaInspector.view_sources`），所以只锁一行时也先锁
T_COST_GOODS 的这一行、再普通读视图，比没有读取视图的保存多 1 条（T-WP-15 复核建议 1：这一条原来只由代码推算）。
页面没有审批流，不推迟加锁。

组装同 `test_oracle_updated_by.py` 的 `Platform`：配置取 `backend/seed/config`（内存中的配置库，不写 PF_CONFIG_ITEM）。
数据自己建、自己删：新增一个本地产品（产成品，ISERP = 0），结束时删掉这个产品和本测试的命令记录。
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from cost_platform.contracts import types as t
from cost_platform.pipeline.tracing import SqlTracer

from .test_oracle_updated_by import Platform, engine  # noqa: F401  fixture

pytestmark = pytest.mark.oracle

PAGE, SAVE, ENTITY = "GOODS_MANAGE", "GOODS_MANAGE.save", "COST_GOODS"
GOODS_NAME = "PF_TEST产品保存条数"
_tracer = SqlTracer()
_log = logging.getLogger(__name__)


@pytest.fixture
def local_product(engine: Engine) -> Iterator[str]:  # noqa: F811
    """新增一个本地产品（产成品、不是 ERP 行），结束时删掉。"""
    with engine.begin() as conn:
        goodsid = str(conn.execute(text("SELECT t_cost_goods_seq.NEXTVAL FROM dual")).scalar_one())
        conn.execute(text("INSERT INTO t_cost_goods (goodsid, goodsname, useflag, iserp, update_by) "
                          "VALUES (:g, :n, '产成品', 0, 'admin')"), {"g": int(goodsid), "n": GOODS_NAME})
    yield goodsid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM t_cost_goods WHERE goodsid = :g"), {"g": int(goodsid)})


def _save(platform: Platform, goodsid: str, changes: dict[str, str]) -> t.Command:
    return t.parse_wire(t.Command, {
        "requestKey": platform.key(), "page": PAGE, "operation": SAVE, "params": {},
        "documents": [{"entity": ENTITY, "master": {"op": "modify", "rowKey": goodsid, "changes": changes}, "details": []}]})


def _kinds(sql: list[str]) -> list[str]:
    return ["LOCK" if "FOR UPDATE" in s else s.split(" ")[0] for s in sql]


def test_goods_manage_save_6_statements(engine: Engine, local_product: str) -> None:  # noqa: F811
    """admin 在产品信息维护改本地产品的规格：插入命令记录、锁住产品表的这一行、经读取视图读出、查冻结、改产品
    （同一条写修改人）、完成命令记录，共 6 条；没有读取视图的可冻结页面改主表一个字段为 5 条（WP-10）。"""
    platform = Platform(engine)
    try:
        ctx = platform.ctx("admin")
        # 先保存一次：进程内第一次写 T_COST_GOODS 时读列定义、第一次用 T_COST_GOODS_V 时读它读取的表（插件 start 时预读，
        # 这里没有预读），不计入
        assert platform.executor.execute(_save(platform, local_product, {"GOODSTYPE": "S-1"}), ctx).outcome == "saved"
        with _tracer.capture() as trace:
            result = platform.executor.execute(_save(platform, local_product, {"GOODSTYPE": "S-2"}), ctx)
        sql = trace.texts
        _log.info("产品信息维护保存 %s 条：%s", len(sql), sql)
        assert result.outcome == "saved"
        assert _kinds(sql) == ["INSERT", "LOCK", "SELECT", "SELECT", "UPDATE", "UPDATE"], sql
        assert "FROM T_COST_GOODS WHERE" in sql[1] and "FROM T_COST_GOODS_V" in sql[2]
        with engine.connect() as conn:
            row = conn.execute(text("SELECT goodstype, update_by FROM t_cost_goods WHERE goodsid = :g"),
                               {"g": int(local_product)}).one()
        assert tuple(row) == ("S-2", "admin")
    finally:
        with engine.begin() as conn:
            for key in platform.request_keys:
                conn.execute(text("DELETE FROM pf_command WHERE request_key = :k"), {"k": key})
