"""T-WP-4：WP-10 的 SQL 条数，用 SQL 追踪统计（一次 execute 或 executemany 计 1 条，提交、回滚和连接池探活不计）。

目标：改主表一个字段 4 条；提交的值与当前值相同 2 条；改一条明细并重算汇总 6 条。

已知冲突（汇报给用户决定，见 .reports/modules/write-pipeline/contract-gaps.md 第 1 条）：主从页上改主表字段时，WP-08 要求按
整张单据求值，所以要读出明细（一条语句），`test_e01_master_detail_master_field` 实际为 5 条、
`test_same_values_master_detail` 实际为 3 条。单表页（物料清单）上两个目标都能达到。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import Engine

from cost_platform.contracts import types as t
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.tracing import SqlTracer

from .oracle_support import (  # noqa: F401  fixtures
    DOC,
    GOODS,
    GOODS_PAGE,
    GOODS_SAVE,
    MATERIAL,
    PAGE,
    SAVE,
    WpSetup,
    engine,
    inspector,
    master_modify,
    master_none,
    rows,
)
from .support import Pipeline, command

pytestmark = pytest.mark.oracle


def run(engine: Engine, documents: list[dict[str, Any]], page: str = PAGE, operation: str = SAVE,
        computed: list[t.EvalRowResult] | None = None) -> tuple[t.CommandResult, list[str]]:
    tracer = SqlTracer()
    p = Pipeline(setup=WpSetup(), store=OracleDocumentStore(5), factory=OracleUnitOfWorkFactory(engine),  # type: ignore[arg-type]
                 inspector=inspector())
    if computed:
        p.setup.engine.respond(t.EvalComputed(ok=True, rows=computed, effects=[]))
    ctx = p.setup.context()
    # 列的小数位取自替代的 SchemaInspector（不发 SQL）；真实的 SchemaInspector 每张表在进程内只读一次（ColumnScales）
    with tracer.capture() as trace:
        result = p.execute(command(documents, request_key=str(uuid.uuid4()), page=page, operation=operation), ctx)
    return result, trace.texts


def total(entity: str, key: str, value: str) -> t.EvalRowResult:
    return t.EvalRowResult(entity=entity, row_key=key, computed={"TOTAL_COST": value}, fields={}, style=t.RowStyle(row=None, cells={}))


def test_single_table_master_field_4_statements(rows: Engine) -> None:
    result, sql = run(rows, [master_modify("116", {"ZX_PRICE": "48"}, entity=GOODS)], GOODS_PAGE, GOODS_SAVE)
    assert result.outcome == "saved"
    assert [s.split(" ")[0] for s in sql] == ["INSERT", "SELECT", "UPDATE", "UPDATE"], sql


def test_single_table_same_values_2_statements(rows: Engine) -> None:
    result, sql = run(rows, [master_modify("116", {"ZX_PRICE": "47"}, entity=GOODS)], GOODS_PAGE, GOODS_SAVE)
    assert result.outcome == "unchanged"
    assert [s.split(" ")[0] for s in sql] == ["INSERT", "SELECT"], sql


def test_e01_master_detail_master_field(rows: Engine) -> None:
    """E01 的形状：成本核算主表 MEMO 改为"测试"，4 条。"""
    result, sql = run(rows, [master_modify("1001", {"MEMO": "测试"})])
    assert result.outcome == "saved"
    assert len(sql) == 4, sql


def test_same_values_master_detail(rows: Engine) -> None:
    result, sql = run(rows, [master_modify("1002", {"MEMO": "旧备注"})])
    assert result.outcome == "unchanged"
    assert len(sql) == 2, sql


def test_detail_change_with_recalculated_total_6_statements(rows: Engine) -> None:
    """改一条明细并重算汇总：插入命令记录、锁主表行、读明细（两个明细实体一条语句）、改明细、改主表、完成命令记录。"""
    result, sql = run(rows, [master_none("1001", [{"entity": MATERIAL, "op": "modify", "rowKey": "5001", "changes": {"PRICE": "3.80"}}])],
                      computed=[total(DOC, "1001", "54.6")])
    assert result.outcome == "saved"
    assert [s.split(" ")[0] for s in sql] == ["INSERT", "SELECT", "SELECT", "UPDATE", "UPDATE", "UPDATE"], sql
    assert "UNION ALL" in sql[2] and "FOR UPDATE" in sql[1]
