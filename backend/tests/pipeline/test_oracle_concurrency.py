"""T-WP-4 的并发验证（d_cg）：两人同时改同一单据的不同明细行，两人的修改都保留；先后改同一字段时以后取得锁的为准。

第一个命令加锁读取后停 1.5 秒再继续（在冻结检查的位置），第二个命令这时开始，等单据锁；第一个提交后，第二个读到
已提交的数据，只合并自己改的字段。"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from sqlalchemy import Engine

from cost_platform.contracts.fakes import FakeStage
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.pipeline.document_store import OracleDocumentStore

from .oracle_support import MATERIAL, USERS, WpSetup, engine, fetch, inspector, master_none, rows  # noqa: F401  fixtures
from .support import Pipeline, command

pytestmark = pytest.mark.oracle


def memo(key: str, value: str) -> list[dict[str, object]]:
    return [master_none("1001", [{"entity": MATERIAL, "op": "modify", "rowKey": key, "changes": {"MEMO": value}}])]


def pipeline(engine: Engine, pause: float) -> Pipeline:
    stage = FakeStage("冻结检查", effect=lambda uow, state, ctx: time.sleep(pause))
    return Pipeline(setup=WpSetup(), store=OracleDocumentStore(10), factory=OracleUnitOfWorkFactory(engine),  # type: ignore[arg-type]
                    inspector=inspector(), freeze=stage)


def both(engine: Engine, first: list[dict[str, object]], second: list[dict[str, object]]) -> None:
    a, b = pipeline(engine, 1.5), pipeline(engine, 0)
    ctx_a, ctx_b = a.setup.context(USERS[0], "张三"), b.setup.context(USERS[1], "李四")
    thread = threading.Thread(target=a.execute, args=(command(first, request_key=str(uuid.uuid4()), page="WP_PAGE",
                                                                operation="WP_PAGE.save"), ctx_a))
    thread.start()
    time.sleep(0.5)
    b.execute(command(second, request_key=str(uuid.uuid4()), page="WP_PAGE", operation="WP_PAGE.save"), ctx_b)
    thread.join(30)


def test_two_users_different_detail_rows_both_kept(rows: Engine) -> None:
    both(rows, memo("5001", "张三改"), memo("5002", "李四改"))
    found = {r["dtlid"]: r["memo"] for r in fetch(rows, "SELECT DTLID, MEMO FROM T_WP_DTL WHERE DOCID = 1001")}
    assert found[5001] == "张三改" and found[5002] == "李四改"


def test_same_field_later_lock_wins(rows: Engine) -> None:
    both(rows, memo("5001", "先"), memo("5001", "后"))
    assert fetch(rows, "SELECT MEMO FROM T_WP_DTL WHERE DTLID = 5001")[0]["memo"] == "后"
