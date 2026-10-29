"""T-WP-1 的真实验证（d_cg）：两个连接用同一请求键并发提交，只执行一次；仍在处理时等待，超时返回 REQUEST_IN_PROGRESS；
先提交的那个回滚后，等待的这个照常执行。前提：已执行 `platform db upgrade`（PF_COMMAND）。"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from sqlalchemy import Engine

from cost_platform.contracts import types as t
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.pipeline.command_log import OracleCommandRecorder

from .oracle_support import NOW, USERS, engine, fetch, rows  # noqa: F401  fixtures
from .support import command, master_modify

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
