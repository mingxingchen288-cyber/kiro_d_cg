"""T-WP-1 的真实验证（d_cg）：两个连接用同一请求键并发提交，只执行一次；仍在处理时等待，超时返回 REQUEST_IN_PROGRESS；
先提交的那个回滚后，等待的这个照常执行。逃生舱的调用记录随命令记录写入 ESCAPE_HATCH_CALLS 并能读回（OP-04）。
前提：已执行 `platform db upgrade`（PF_COMMAND，wp_0001、wp_0002）。命令记录由 fixture 在结束时删除。"""

from __future__ import annotations

import json
import threading
import time
import uuid

import pytest
from sqlalchemy import Engine

from cost_platform.contracts import types as t
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.document_store import OracleDocumentStore

from .oracle_support import NOW, PAGE, USERS, WpSetup, engine, fetch, inspector, rows  # noqa: F401  fixtures
from .support import Pipeline, command, master_modify

pytestmark = pytest.mark.oracle


def a_command() -> t.Command:
    return command([master_modify("1001", {"MEMO": "并发"})], request_key=str(uuid.uuid4()), page="WP_PAGE", operation="WP_PAGE.save")


def saved(cmd: t.Command) -> t.CommandResult:
    return t.CommandResult(request_key=cmd.request_key, outcome="saved", rows=[], id_map={}, prompts=[], skipped=[], approvals=[])


def hold_then(factory: OracleUnitOfWorkFactory, recorder: OracleCommandRecorder, cmd: t.Command, seconds: float,
              commit: bool, inserted: threading.Event) -> None:
    """第一个命令：插入命令记录后保持事务 `seconds` 秒，再完成并提交（或回滚）。"""
    with factory.begin() as uow:
        assert recorder.begin(uow, USERS[0], cmd, NOW) is None
        inserted.set()
        time.sleep(seconds)
        if commit:
            recorder.finish(uow, USERS[0], cmd, saved(cmd), None, NOW)
            uow.commit()


def second(factory: OracleUnitOfWorkFactory, recorder: OracleCommandRecorder, cmd: t.Command) -> t.CommandResult | None:
    with factory.begin() as uow:
        return recorder.begin(uow, USERS[0], cmd, NOW)


def test_same_key_concurrent_waits_and_returns_original(rows: Engine) -> None:
    factory, recorder, cmd = OracleUnitOfWorkFactory(rows), OracleCommandRecorder(5), a_command()
    inserted = threading.Event()
    first = threading.Thread(target=hold_then, args=(factory, recorder, cmd, 1.5, True, inserted))
    first.start()
    inserted.wait(10)
    started = time.monotonic()
    replay = second(factory, recorder, cmd)
    first.join(30)
    assert replay == saved(cmd)  # 第二次没有执行业务流程，返回第一次的结果
    assert 1.0 <= time.monotonic() - started < 5
    assert len(fetch(rows, "SELECT * FROM pf_command WHERE request_key = :k", k=cmd.request_key)) == 1


def test_still_running_after_wait_is_request_in_progress(rows: Engine) -> None:
    factory, recorder, cmd = OracleUnitOfWorkFactory(rows), OracleCommandRecorder(2), a_command()
    inserted = threading.Event()
    first = threading.Thread(target=hold_then, args=(factory, recorder, cmd, 5, True, inserted))
    first.start()
    inserted.wait(10)
    started = time.monotonic()
    with pytest.raises(t.PlatformError) as caught:
        second(factory, recorder, cmd)
    waited = time.monotonic() - started
    first.join(30)
    assert caught.value.code is t.ErrorCode.REQUEST_IN_PROGRESS
    assert 1.5 <= waited < 4.5
    assert second(factory, recorder, cmd) == saved(cmd)  # 第一个完成后再提交，返回它的结果


def test_first_rolled_back_second_executes(rows: Engine) -> None:
    factory, recorder, cmd = OracleUnitOfWorkFactory(rows), OracleCommandRecorder(5), a_command()
    inserted = threading.Event()
    first = threading.Thread(target=hold_then, args=(factory, recorder, cmd, 1, False, inserted))
    first.start()
    inserted.wait(10)
    assert second(factory, recorder, cmd) is None  # 第一个回滚，命令记录撤销，这个照常执行
    first.join(30)


def test_escape_hatch_calls_written_with_the_command_record(rows: Engine) -> None:
    """按钮"由BOM生成明细"只调用了逃生舱（operations 的展开动作写 `state.escape_hatch_calls`，这里用替代展开）：
    命令结果为 saved 并提交，ESCAPE_HATCH_CALLS 读回的就是这条调用记录。"""
    code = f"{PAGE}.generateFromBom"
    pipeline = Pipeline(setup=WpSetup(), store=OracleDocumentStore(5), factory=OracleUnitOfWorkFactory(rows),  # type: ignore[arg-type]
                        inspector=inspector())
    cmd = command([], request_key=str(uuid.uuid4()), page=PAGE, operation=code,
                  params={"selectedRows": [{"entity": "WP_DOC", "rowKey": "1001"}]})
    call = {"operation": code, "kind": "procedure", "target": "P_COST_BOM_INSERT", "params": {"P_DOCID": "1001"},
            "outputs": {"P_MESSAGE": "已按 BOM 生成 12 行明细"}, "writes": {"WP_DOC": ["TOTAL_COST"]}, "userId": USERS[0],
            "userName": "张三", "at": "2026-10-29T10:00:00", "requestKey": cmd.request_key, "approvalId": None}
    pipeline.actions = [lambda state, ctx: state.escape_hatch_calls.append(call)]
    result = pipeline.execute(cmd, pipeline.setup.context())
    assert result.outcome == "saved"
    [row] = fetch(rows, "SELECT status, escape_hatch_calls FROM pf_command WHERE user_id = :u AND request_key = :k",
                  u=USERS[0], k=cmd.request_key)
    assert row["status"] == "done" and json.loads(row["escape_hatch_calls"]) == [call]
