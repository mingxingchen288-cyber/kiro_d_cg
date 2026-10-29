"""逃生舱的真实验证（T-OP-2，d_cg）：在 Oracle 的命令事务内调用真实存储过程。

前提（任务卡 T-OP-2）：用户同意在 d_cg 中建一个测试用存储过程（名称以 `PF_TEST_` 开头）。本文件的 fixture 建表
`PF_TEST_ESCAPE_LOG` 和存储过程 `PF_TEST_ESCAPE_HATCH`，结束时删除；它们只在这里的测试配置中登记启用。

验收：逃生舱在命令事务内执行，之后的动作失败时它的写入一起回滚；调用记录写进 `state.escape_hatch_calls`（随命令记录
写入 PF_COMMAND 的真实验证见 tests/pipeline/test_oracle_command_log.py）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from cost_platform.assembly.settings import Settings
from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeRelatedQuery
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.operations import (
    ActionStage,
    EscapeHatchRegistration,
    EscapeHatchRegistry,
    EscapeParam,
    ProcedureCall,
    StatementCall,
)

from .support import D, MASTER, command, context, cost_doc, material, operation, ref, snapshot

pytestmark = pytest.mark.oracle

TABLE = "PF_TEST_ESCAPE_LOG"
PROCEDURE = "PF_TEST_ESCAPE_HATCH"
CODE = "COST_PINGGU.pfTestEscape"
NOT_ENABLED = "COST_PINGGU.pfTestNotEnabled"
PROCEDURE_SQL = f"""CREATE OR REPLACE PROCEDURE {PROCEDURE}(P_DOCID IN NUMBER, P_NOTE IN VARCHAR2, P_COUNT IN OUT NUMBER,
                                                    P_MESSAGE OUT VARCHAR2) AS
BEGIN
  INSERT INTO {TABLE} (DOCID, NOTE) VALUES (P_DOCID, P_NOTE);
  P_COUNT := NVL(P_COUNT, 0) + 1;
  P_MESSAGE := '已处理 ' || P_DOCID;
END;"""

PARAMS = (EscapeParam("P_DOCID", "document.recordKey", "number"), EscapeParam("P_NOTE", "context.userName"),
          EscapeParam("P_COUNT", "constant", "number", "INOUT", Decimal(41)),
          EscapeParam("P_MESSAGE", mode="OUT", prompt=True))


@pytest.fixture(scope="module")
def engine() -> Iterator[Any]:
    s = Settings.load()
    engine = create_oracle_engine(s.db_user, s.db_password, s.db_dsn)
    with engine.begin() as c:
        c.exec_driver_sql(f"CREATE TABLE {TABLE} (DOCID NUMBER, NOTE VARCHAR2(200))")
        c.exec_driver_sql(PROCEDURE_SQL)
    yield engine
    with engine.begin() as c:
        c.exec_driver_sql(f"DROP PROCEDURE {PROCEDURE}")
        c.exec_driver_sql(f"DROP TABLE {TABLE} PURGE")


@pytest.fixture(autouse=True)
def empty_log(engine: Any) -> Iterator[None]:
    yield
    with engine.begin() as c:
        c.execute(text(f"DELETE FROM {TABLE}"))


def _config() -> Any:
    escape = operation([], kind="escapeHatch", procedure=PROCEDURE, writes={}, label="测试逃生舱")
    later = operation([{"action": "escapeHatch", "operation": CODE}, {"action": "escapeHatch", "operation": NOT_ENABLED}])
    return snapshot({CODE: escape, "COST_PINGGU.escapeThenFail": later,
                     NOT_ENABLED: operation([], kind="escapeHatch", procedure="PF_TEST_NOT_ENABLED")})


def _state(op: str) -> t.CommandState:
    """选中成本单 D 的命令，已"加锁读取"（D 的数据放在内存中，这里只验证逃生舱，不读业务表）。"""
    state = t.CommandState(command=command(op, [(MASTER, D)]))
    state.involved.append(ref(D))
    state.current[ref(D)] = cost_doc(D, [material("5001", D, 115, "80")])
    return state


def _rows(engine: Any) -> list[tuple[Any, ...]]:
    with engine.connect() as c:
        return [tuple(r) for r in c.execute(text(f"SELECT DOCID, NOTE FROM {TABLE} ORDER BY DOCID"))]


def _stage(call: Any, code: str = CODE) -> ActionStage:
    return ActionStage(FakeRelatedQuery(), EscapeHatchRegistry([EscapeHatchRegistration(code, call)]))


def test_procedure_runs_in_the_command_transaction_and_commits_with_it(engine: Any) -> None:
    """调用 PF_TEST_ESCAPE_HATCH(D, 执行人, 41, OUT)：命令提交后表中有这一行；INOUT 取回 42，OUT 的提示随命令返回；
    调用记录有逃生舱、参数、执行人、时间和请求键。"""
    stage = _stage(ProcedureCall(PROCEDURE, PARAMS))
    ctx = context(_config())
    state = _state(CODE)
    state.actions.append(t.EscapeHatch(action="escapeHatch", operation=CODE))
    with OracleUnitOfWorkFactory(engine).begin() as uow:
        stage.run(uow, state, ctx)
        assert _rows(engine) == []  # 还没有提交，别的连接看不到
        uow.commit()
    assert _rows(engine) == [(2550, "张三")]
    call, = state.escape_hatch_calls  # 写命令记录的 JSON：值按 C01 写成文本
    assert call["params"] == {"P_DOCID": "2550", "P_NOTE": "张三", "P_COUNT": "41"}
    assert call["outputs"] == {"P_COUNT": "42", "P_MESSAGE": "已处理 2550"}
    assert (call["userId"], call["requestKey"]) == ("112", state.command.request_key)
    assert [p.message for p in state.prompts] == ["已处理 2550"]


def test_procedure_writes_roll_back_when_a_later_action_fails(engine: Any) -> None:
    """逃生舱之后的动作失败（下一个逃生舱没有登记启用）：整个命令回滚，存储过程写的行也没有了。"""
    stage = _stage(ProcedureCall(PROCEDURE, PARAMS))
    ctx = context(_config())
    state = _state("COST_PINGGU.escapeThenFail")
    state.actions += [t.EscapeHatch(action="escapeHatch", operation=CODE),
                      t.EscapeHatch(action="escapeHatch", operation=NOT_ENABLED)]
    with pytest.raises(t.PlatformError), OracleUnitOfWorkFactory(engine).begin() as uow:
        stage.run(uow, state, ctx)
        stage.run(uow, state, ctx)
        uow.commit()
    assert _rows(engine) == []


def test_source_fingerprint_is_checked_before_the_call(engine: Any) -> None:
    """登记时写下源码指纹（旧系统 ActionWriteGuard 的 sources），调用前核对一致才执行。"""
    with engine.connect() as c:
        lines = c.execute(text("SELECT TEXT FROM USER_SOURCE WHERE NAME = :n AND TYPE = 'PROCEDURE' ORDER BY LINE"),
                          {"n": PROCEDURE}).scalars().all()
    fingerprint = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    stage = _stage(ProcedureCall(PROCEDURE, PARAMS, {f"{PROCEDURE}/PROCEDURE": fingerprint}))
    ctx = context(_config())
    state = _state(CODE)
    state.actions.append(t.EscapeHatch(action="escapeHatch", operation=CODE))
    with OracleUnitOfWorkFactory(engine).begin() as uow:
        stage.run(uow, state, ctx)
        uow.commit()
    assert _rows(engine) == [(2550, "张三")]


def test_registered_statement_runs_in_the_command_transaction(engine: Any) -> None:
    """登记的语句（旧 sql 执行器）在命令事务内执行，参数用绑定变量。"""
    with engine.begin() as c:
        c.execute(text(f"INSERT INTO {TABLE} (DOCID, NOTE) VALUES (2550, 'system')"))
    call = StatementCall("改备注", f"UPDATE {TABLE} SET NOTE = :note WHERE DOCID = :docid",
                         (EscapeParam("note", "context.userName"), EscapeParam("docid", "document.recordKey", "number")))
    stage = _stage(call)
    ctx = context(snapshot({CODE: operation([], kind="escapeHatch", label="测试语句")}))
    state = _state(CODE)
    state.actions.append(t.EscapeHatch(action="escapeHatch", operation=CODE))
    with OracleUnitOfWorkFactory(engine).begin() as uow:
        stage.run(uow, state, ctx)
        uow.commit()
    assert _rows(engine) == [(2550, "张三")]
