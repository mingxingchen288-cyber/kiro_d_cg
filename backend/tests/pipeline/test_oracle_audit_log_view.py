"""审计追踪视图（WP-22）的真实验证（d_cg）：迁移 wp_0003 的查询把命令记录的审计差异展开成一个字段一行。

直接执行迁移中的查询（`wp_0003_audit_log_view.SELECT`），不依赖视图已经建好（视图由 `platform db upgrade` 建）。
测试自己插一条命令记录（用户 1，即 admin；新的请求键），审计差异按写入管道的写法生成（`command_log.audit_rows`，
`json.dumps(..., ensure_ascii=False)`，与 `OracleCommandRecorder._finish` 相同）；结束时删掉这条记录。字段标题取 d_cg 中
成本核算实体配置当前的 label。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from cost_platform.contracts.types import DocumentRef, RowChange
from cost_platform.pipeline.command_log import audit_rows
from cost_platform.pipeline.migrations.wp_0003_audit_log_view import SELECT

pytestmark = pytest.mark.oracle


@pytest.fixture
def engine() -> Iterator[Engine]:
    from cost_platform.assembly.settings import Settings
    from cost_platform.db_core.engine import create_oracle_engine

    settings = Settings.load()
    found = create_oracle_engine(settings.db_user, settings.db_password, settings.db_dsn)
    yield found
    found.dispose()


def test_audit_diff_expanded_one_field_per_row(engine: Engine) -> None:
    """admin 在成本核算改了单据 200680 主表的备注（空 → PF_TEST审计）、原辅料一行的客户指定（否 → 是），又删了一行
    原辅料：视图给出每个字段一行，操作类型写成旧系统的 UPDATE、DELETE，字段标题、表名称取实体配置，用户为登录名。"""
    doc = DocumentRef("COST_PINGGU", "200680")
    changes = [
        RowChange(document=doc, entity="COST_PINGGU", op="modify", row_key="200680", client_row_id=None,
                  values={"MEMO": "PF_TEST审计"}, old={"MEMO": None}),
        RowChange(document=doc, entity="COST_MATERIAL", op="modify", row_key="206323", client_row_id=None,
                  values={"CUSTOMER_SPECIFIED": True}, old={"CUSTOMER_SPECIFIED": False}),
        RowChange(document=doc, entity="COST_MATERIAL", op="delete", row_key="208528", client_row_id=None,
                  values={}, old={"DTLID": Decimal("208528"), "PER_HL": Decimal("5")}),
    ]
    key = str(uuid.uuid4())
    now = datetime(2026, 10, 31, 12, 0, 0)  # 写入管道的请求时间到秒（d_cg 的命令记录都没有小数秒）
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO pf_command (user_id, request_key, operation, page, digest, status, audit_diff, "
                          "created_at, finished_at) VALUES ('1', :k, 'COST_PINGGU.save', 'COST_PINGGU', 'x', 'done', :a, :t, :t)"),
                     {"k": key, "a": json.dumps(audit_rows(changes), ensure_ascii=False), "t": now})
    try:
        with engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM ({SELECT}) v WHERE v.ID LIKE :p ORDER BY v.ID"), {"p": f"%-{key}-%"}).mappings()]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pf_command WHERE request_key = :k"), {"k": key})
    got = [(r["record_id"], r["table_code"], r["table_name"], r["operation_type"], r["field_code"], r["field_name"],
            r["old_value"], r["new_value"]) for r in rows]
    assert got == [
        ("200680", "COST_PINGGU", "物料成本核算表", "UPDATE", "MEMO", "备注", None, "PF_TEST审计"),
        ("206323", "COST_MATERIAL", "原辅料明细", "UPDATE", "CUSTOMER_SPECIFIED", "客户指定", "false", "true"),
        ("208528", "COST_MATERIAL", "原辅料明细", "DELETE", "DTLID", "ID", "208528", None),
        ("208528", "COST_MATERIAL", "原辅料明细", "DELETE", "PER_HL", "每片含量", "5", None),
    ], got
    assert {r["user_name"] for r in rows} == {"admin"} and {r["page_code"] for r in rows} == {"COST_PINGGU"}
    assert {r["operation_time"] for r in rows} == {now} and {r["create_time"] for r in rows} == {now}
    assert rows[0]["id"] == f"20261031120000000000-1-{key}-00001-0001"
