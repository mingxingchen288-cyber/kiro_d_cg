"""命令审查（WP-17、C09 第 7a 节，T-WP-5）：关闭时不记录、Redis 中没有记录；开启后成功和失败的命令都有记录，
含每条 SQL；关闭时删除记录和开关；接口只给管理员。`RedisCommandMonitor` 通过 `CommandMonitor` 的契约测试（Redis 用
`FakeRedis`，真实 Redis 见 `test_redis_review.py`）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import text

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeClock, FakeUnitOfWorkFactory
from cost_platform.pipeline.review import LIMIT, RedisCommandMonitor, RedisCommandReview, command_review_router
from cost_platform.pipeline.tracing import SqlTracer

from ..contracts.test_command_monitor import CommandMonitorContract
from .fake_redis import FakeRedis
from .support import KEY_1, KEY_2, Setup, command, master_modify

NS = "cp"
NOW = datetime(2026, 10, 29, 10, 0, 0)


def monitor_of(redis: FakeRedis) -> RedisCommandMonitor:
    return RedisCommandMonitor(RedisCommandReview(redis, NS), SqlTracer(), FakeClock(NOW))


def run(monitor: RedisCommandMonitor, cmd: t.Command, fail: bool = False) -> None:
    """被审查的命令：在事务中执行两条 SQL；`fail` 时第二条之后规则拒绝，事务回滚。"""
    factory = FakeUnitOfWorkFactory()
    with monitor.watch(cmd, Setup().context()), factory.begin() as uow:
        uow.connection.execute(text("SELECT 1"))
        uow.connection.execute(text("SELECT :a"), {"a": 2})
        if fail:
            raise t.PlatformError(t.ErrorCode.RULE_REJECTED, "价格超出范围")
        uow.commit()


def test_disabled_records_nothing() -> None:
    redis = FakeRedis()
    run(monitor_of(redis), command([master_modify("1001", {"MEMO": "测试"})]))
    assert redis.data == {}


def test_enabled_records_saved_and_failed_commands_with_sql() -> None:
    redis = FakeRedis()
    review = RedisCommandReview(redis, NS)
    review.set_enabled(True)
    monitor = monitor_of(redis)
    run(monitor, command([master_modify("1001", {"MEMO": "测试"})], request_key=KEY_1))
    with pytest.raises(t.PlatformError):
        run(monitor, command([master_modify("1001", {"MEMO": "x"})], request_key=KEY_2), fail=True)
    listed = review.list(0, 50)
    assert listed.enabled is True and listed.total == 2
    failed, saved = listed.rows  # 最新的在前
    assert (saved.request_key, saved.result, saved.error_code, saved.user, saved.page) == (KEY_1, "saved", None, "user112", "COST_PINGGU")
    assert saved.sql_count == 2 and [s.text for s in saved.sql] == ["SELECT 1", "SELECT ?"]
    assert saved.sql[1].binds == {"1": 2} and saved.started_at == NOW
    assert (failed.result, failed.error_code, failed.message, failed.sql_count) == (
        "rejected", t.ErrorCode.RULE_REJECTED, "价格超出范围", 2)
    assert [r.request_key for r in review.list(0, 50, result="rejected").rows] == [KEY_2]
    assert review.list(0, 50, user="nobody").total == 0


def test_disable_deletes_records_and_switch() -> None:
    redis = FakeRedis()
    review = RedisCommandReview(redis, NS)
    review.set_enabled(True)
    run(monitor_of(redis), command([master_modify("1001", {"MEMO": "测试"})]))
    assert set(redis.data) == {"cp:cmdlog", "cp:cmdlog:enabled"}
    review.set_enabled(False)
    assert redis.data == {}


def test_write_failure_does_not_affect_command() -> None:
    redis = FakeRedis()
    RedisCommandReview(redis, NS).set_enabled(True)
    redis.fail_writes = True
    run(monitor_of(redis), command([master_modify("1001", {"MEMO": "测试"})]))  # 不抛异常


def test_keeps_latest_10000() -> None:
    redis = FakeRedis()
    review = RedisCommandReview(redis, NS, limit=3)
    review.set_enabled(True)
    log = t.CommandLog(request_key=KEY_1, user="admin", page=None, operation="x", result="saved", error_code=None, message=None,
                       started_at=datetime(2026, 10, 29), duration_ms=1, sql_count=0, sql_ms=0, sql=[])
    for _ in range(5):
        review.record(log)
    assert review.list(0, 50).total == 3


# ---------------------------------------------------------------- CommandMonitor 的契约测试

class FakeRedisHarness:
    def __init__(self) -> None:
        self.review = RedisCommandReview(FakeRedis(), NS)
        self.monitor = RedisCommandMonitor(self.review, SqlTracer(), FakeClock(NOW))

    def enable(self) -> None:
        self.review.set_enabled(True)

    def results(self) -> list[tuple[str, str]]:
        return [(log.request_key, log.result) for log in reversed(self.review.list(0, LIMIT).rows)]


class TestRedisCommandMonitor(CommandMonitorContract):
    @pytest.fixture
    def harness(self) -> FakeRedisHarness:
        return FakeRedisHarness()


# ---------------------------------------------------------------- 接口

def app(redis: FakeRedis, admin: bool) -> TestClient:
    setup = Setup()
    review = RedisCommandReview(redis, NS)

    def context(request: Request, is_write: bool) -> t.ExecutionContext:
        ctx = setup.context()
        snapshot = ctx.config
        snapshot._role = t.RoleConfig(name="系统管理员" if admin else "成本会计", admin=admin, pages={})  # type: ignore[attr-defined]
        return ctx

    api = FastAPI()
    api.include_router(command_review_router(review, context))

    @api.exception_handler(t.PlatformError)
    async def platform_error(_request: Request, exc: t.PlatformError) -> JSONResponse:
        return JSONResponse(t.dump_wire(t.ErrorResponse, exc.to_response()), status_code=exc.http_status)

    return TestClient(api)


def test_http_toggle_and_list() -> None:
    redis = FakeRedis()
    client = app(redis, admin=True)
    assert client.put("/api/admin/command-review", json={"enabled": True}).status_code == 204
    body = client.get("/api/admin/command-review", params={"startRow": 0, "endRow": 50}).json()
    assert body == {"enabled": True, "rows": [], "total": 0}
    assert client.put("/api/admin/command-review", json={"enabled": False}).status_code == 204
    assert redis.data == {}


def test_http_admin_only() -> None:
    client = app(FakeRedis(), admin=False)
    response = client.get("/api/admin/command-review")
    assert response.status_code == 403 and response.json()["code"] == "PERMISSION_DENIED"
