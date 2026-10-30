"""物料清单页保存的 SQL 条数（WP-10）的真实验证（d_cg），用 SQL 追踪统计（计数口径同 `test_oracle_sql_count.py`）。

物料清单页（GOODS_PRICE_MANAGE）配了往前冻结的审批流 GOODS_TO_COST（改执行价冻结含这个物料的成本单），按用户 2026-10-30
固定加锁层级的规则 3、4，每次保存都推迟加锁：先普通读取物料，算完入口条件，再按统一顺序锁住，锁住后核对。锁住和核对
合成一条带数据的加锁语句（`pipeline/locks.py`），比普通保存只多 1 条加锁前的普通读取。

组装同 `test_oracle_updated_by.py` 的 `Platform`：配置取 `backend/seed/config`（内存中的配置库，不写 PF_CONFIG_ITEM），
权限、写入管道、审批阶段都是真实实现。数据自己建、自己删：新增一个本地物料（ISERP = 0），没有成本单用到它；结束时删掉
这个物料和本测试的命令记录。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from cost_platform.contracts import types as t
from cost_platform.pipeline.tracing import SqlTracer

from .test_oracle_updated_by import ENTITY, PAGE, SAVE, Platform, engine  # noqa: F401  fixture

pytestmark = pytest.mark.oracle

GOODS_NAME = "B1保存条数测试辅料"
_tracer = SqlTracer()
_log = logging.getLogger(__name__)
"""每条 SQL 记日志（`-o log_cli=true --log-cli-level=INFO` 可以看到）。"""


@pytest.fixture
def local_goods(engine: Engine) -> Iterator[str]:  # noqa: F811
    """新增一个本地物料（不是 ERP 行），结束时删掉。"""
    with engine.begin() as conn:
        goodsid = str(conn.execute(text("SELECT t_cost_goods_seq.NEXTVAL FROM dual")).scalar_one())
        conn.execute(text("INSERT INTO t_cost_goods (goodsid, goodsname, price, useflag, iserp, update_by) "
                          "VALUES (:g, :n, 10, '辅料', 0, 'admin')"), {"g": int(goodsid), "n": GOODS_NAME})
    yield goodsid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM t_cost_goods WHERE goodsid = :g"), {"g": int(goodsid)})


def _save(platform: Platform, goodsid: str, changes: dict[str, str]) -> t.Command:
    return t.parse_wire(t.Command, {
        "requestKey": platform.key(), "page": PAGE, "operation": SAVE, "params": {},
        "documents": [{"entity": ENTITY, "master": {"op": "modify", "rowKey": goodsid, "changes": changes}, "details": []}]})


def _kinds(sql: list[str]) -> list[str]:
    """每条 SQL 的种类：加锁（带 FOR UPDATE）、入口条件（FROM DUAL）、其余按第一个词。"""
    return ["LOCK" if "FOR UPDATE" in s else "DUAL" if " FROM DUAL" in s else s.split(" ")[0] for s in sql]


def test_goods_page_save_without_approval_7_statements(engine: Engine, local_goods: str) -> None:  # noqa: F811
    """admin 在物料清单页改本地物料的规格（不改执行价，GOODS_TO_COST 的入口条件不成立）：插入命令记录、加锁前普通读取、
    入口条件、锁住物料并读出数据（一条，锁住后用它核对）、查冻结、改物料（同一条写修改人）、完成命令记录，共 7 条；
    原来锁和核对重读各一条，共 8 条（`.reports/batch5-20261030/b1-pipeline/`）。不推迟加锁的保存（例如成本核算改主表）
    没有加锁前的普通读取，其余相同，所以只多这 1 条。"""
    platform = Platform(engine)
    try:
        ctx = platform.ctx("admin")
        # 先保存一次：进程内第一次写 T_COST_GOODS 时读列定义（WP-15，平台启动时预读，这里没有预读），不计入
        assert platform.executor.execute(_save(platform, local_goods, {"GOODSTYPE": "B1-1"}), ctx).outcome == "saved"
        with _tracer.capture() as trace:
            result = platform.executor.execute(_save(platform, local_goods, {"GOODSTYPE": "B1-2"}), ctx)
        sql = trace.texts
        _log.info("物料清单页保存 %s 条：%s", len(sql), sql)
        assert result.outcome == "saved"
        assert _kinds(sql) == ["INSERT", "SELECT", "DUAL", "LOCK", "SELECT", "UPDATE", "UPDATE"], sql
        assert "FROM T_COST_GOODS_PRICE_V" in sql[3] and "GOODSTYPE" in sql[3]  # 加锁语句同时读出物料的数据
        with engine.connect() as conn:
            row = conn.execute(text("SELECT goodstype, update_by FROM t_cost_goods WHERE goodsid = :g"),
                               {"g": int(local_goods)}).one()
        assert tuple(row) == ("B1-2", "admin")
    finally:
        with engine.begin() as conn:
            for key in platform.request_keys:
                conn.execute(text("DELETE FROM pf_command WHERE request_key = :k"), {"k": key})
