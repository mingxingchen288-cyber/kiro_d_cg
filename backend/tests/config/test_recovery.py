"""发布状态与崩溃恢复（CF-04、CF-05，T-CF-3 的模拟验证；业务例子 E18）。在保存的每一步之后让进程退出，检查之后的请求和恢复任务。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from cost_platform.config.cache import CacheUnavailable
from cost_platform.contracts.types import ErrorCode, PlatformError

from .support import Env, KilledProcess, draft, kill_after, seed_drafts

ROLE_R = {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["system:save"]}}}


@pytest.fixture
def env() -> Env:
    env = Env()
    env.save([*seed_drafts(), draft("role", "R", ROLE_R)])
    env.reader.read("R")
    env.publisher.events.clear()
    return env


def _revoke_page(env: Env) -> None:
    env.save([draft("role", "R", {**ROLE_R, "pages": {}})])


def test_e18_killed_after_commit_next_request_uses_oracle_once(env: Env) -> None:
    """E18：去掉角色 R 对成本核算页的访问并保存，在 Oracle 提交之后、写 Redis 之前进程退出：R 的下一个请求返回 403，
    只为这个请求查一次 Oracle；同时补写 Redis、发布配置变更，之后的请求不再查 Oracle。"""
    generation = env.generation()
    env.hook = kill_after("committed")
    with pytest.raises(KilledProcess):
        _revoke_page(env)
    assert env.generation() == generation + 1 and env.cache.generation == generation  # 已生效，Redis 还是旧的
    other = env.new_reader()  # 其他进程，或者重启后的进程
    for reader in (env.reader, other):
        before = reader.oracle_reads
        with pytest.raises(PlatformError) as caught:
            reader.read("R").page_view("COST_PINGGU")
        assert caught.value.code is ErrorCode.PERMISSION_DENIED
        assert reader.oracle_reads - before <= 1
    assert env.reader.oracle_reads + other.oracle_reads == 1
    assert env.cache.generation == generation + 1 and env.cache.pending == {}
    assert [(e.payload.pages, e.payload.version) for e in env.publisher.events] == [(["COST_PINGGU"], generation + 1)]
    reads = env.reader.oracle_reads
    env.reader.read("R")
    assert env.reader.oracle_reads == reads


def test_e18_recovery_task_rewrites_redis_and_publishes(env: Env) -> None:
    """E18：提交后、写 Redis 前退出，没有请求进来时，恢复任务（每 5 秒一次）按 Oracle 补写 Redis，并发布 config.changed。"""
    env.hook = kill_after("committed")
    with pytest.raises(KilledProcess):
        _revoke_page(env)
    pages = env.recovery().run_once()
    assert pages == ["COST_PINGGU"]
    assert env.cache.generation == env.generation() and env.cache.pending == {}
    assert "pageView/COST_PINGGU|R" not in env.cache.index
    assert [e.payload.pages for e in env.publisher.events] == [["COST_PINGGU"]]
    assert env.recovery().run_once() == []  # 已经一致：下一轮只读一行代号，什么都不做
    with pytest.raises(PlatformError) as caught:
        env.new_reader().read("R").page_view("COST_PINGGU")
    assert caught.value.code is ErrorCode.PERMISSION_DENIED


def test_killed_before_commit_config_unchanged_and_registration_removed_after_60s(env: Env) -> None:
    """Oracle 提交前退出：配置不变；读取时 Oracle 代号小于登记的代号，继续用原来的配置；60 秒后恢复任务删除登记。"""
    generation, records = env.generation(), env.records()
    env.hook = kill_after("pending")
    with pytest.raises(KilledProcess):
        _revoke_page(env)
    assert env.generation() == generation and env.records() == records
    assert list(env.cache.pending) == [generation + 1]
    assert env.new_reader().read("R").page_view("COST_PINGGU").page_code == "COST_PINGGU"
    env.clock.advance(timedelta(seconds=59))
    env.recovery().run_once()
    assert list(env.cache.pending) == [generation + 1]
    env.clock.advance(timedelta(seconds=2))
    env.recovery().run_once()
    assert env.cache.pending == {} and env.cache.generation == generation and env.publisher.events == []


def test_redis_unavailable_save_returns_config_unavailable(env: Env) -> None:
    """Redis 不可用时保存返回 503 CONFIG_UNAVAILABLE，配置不变。"""
    generation, records = env.generation(), env.records()
    env.cache.unavailable = True
    with pytest.raises(PlatformError) as caught:
        _revoke_page(env)
    assert caught.value.code is ErrorCode.CONFIG_UNAVAILABLE and caught.value.http_status == 503
    assert env.generation() == generation and env.records() == records


def test_redis_write_fails_after_commit_save_succeeds(env: Env) -> None:
    """第 4 步提交后第 5 步写 Redis 失败：接口照常返回保存成功，恢复任务补齐。"""
    original = env.cache.apply
    failures = []

    def broken(batch):  # type: ignore[no-untyped-def]
        failures.append(batch.generation)
        raise CacheUnavailable("Redis 断开")

    env.cache.apply = broken  # type: ignore[method-assign]
    result = env.save([draft("role", "R", {**ROLE_R, "name": "成本会计（改）"})])
    env.cache.apply = original  # type: ignore[method-assign]
    assert failures == [result.generation] and env.generation() == result.generation
    env.publisher.events.clear()
    env.recovery().run_once()
    assert env.cache.generation == result.generation
    assert env.new_reader().read("R").role().name == "成本会计（改）"


def test_saves_run_one_after_another(env: Env) -> None:
    """两次保存依次执行，代号各加一，Redis 跟着切换。"""
    first = env.save([draft("role", "R", {**ROLE_R, "name": "一"})])
    second = env.save([draft("role", "R", {**ROLE_R, "name": "二"})])
    assert second.generation == first.generation + 1 == env.generation()
    assert env.cache.generation == second.generation
    assert env.reader.read("R").role().name == "二"
