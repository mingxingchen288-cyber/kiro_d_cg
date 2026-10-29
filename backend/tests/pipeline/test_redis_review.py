"""T-WP-5 的真实验证（Redis 和 d_cg）：开启后一条失败的命令也有记录，SQL 条数与 T-WP-4 的追踪一致；关闭后 `{ns}:cmdlog`
被删除；`RedisCommandMonitor` 在真实 Redis 上通过 `CommandMonitor` 的契约测试。键名加 `:wptest` 后缀，不碰正式的命令审查
记录。连接取根目录 `.env` 的 PLATFORM_REDIS_URL、PLATFORM_REDIS_NAMESPACE。"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeClock
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.review import LIMIT, RedisCommandMonitor, RedisCommandReview
from cost_platform.pipeline.tracing import SqlTracer

from ..contracts.test_command_monitor import CommandMonitorContract
from .oracle_support import GOODS, GOODS_PAGE, GOODS_SAVE, WpSetup, engine, inspector, rows  # noqa: F401  fixtures
from .support import Pipeline, command, master_modify

pytestmark = pytest.mark.redis

NOW = datetime(2026, 10, 29, 10, 0, 0)


@pytest.fixture
def redis_client() -> Iterator[tuple[Any, str]]:
    import redis

    from cost_platform.assembly.settings import ROOT, _read_env

    env = {**_read_env(ROOT / ".env"), **os.environ}
    client = redis.Redis.from_url(env["PLATFORM_REDIS_URL"])
    namespace = f"{env.get('PLATFORM_REDIS_NAMESPACE', 'cp')}:wptest"
    yield client, namespace
    client.delete(f"{namespace}:cmdlog", f"{namespace}:cmdlog:enabled")


@pytest.mark.oracle
def test_failed_command_recorded_and_disable_clears(rows: Engine, redis_client: tuple[Any, str]) -> None:
    client, namespace = redis_client
    review = RedisCommandReview(client, namespace)
    review.set_enabled(True)
    monitor = RedisCommandMonitor(review, SqlTracer(), FakeClock(NOW))
    inner = Pipeline(setup=WpSetup(), store=OracleDocumentStore(5), factory=OracleUnitOfWorkFactory(rows),  # type: ignore[arg-type]
                     inspector=inspector())
    cmd = command([master_modify("115", {"PRICE": "3.80"}, entity=GOODS)], request_key=str(uuid.uuid4()), page=GOODS_PAGE,
                  operation=GOODS_SAVE)
    ctx = inner.setup.context()
    with pytest.raises(t.PlatformError), monitor.watch(cmd, ctx):
        inner.execute(cmd, ctx)  # ERP 行的 ERP 列：FIELD_NOT_WRITABLE
    [log] = review.list(0, 10).rows
    assert (log.request_key, log.result, log.error_code) == (cmd.request_key, "rejected", t.ErrorCode.FIELD_NOT_WRITABLE)
    assert log.sql_count == 2 and [s.text.split(" ")[0] for s in log.sql] == ["INSERT", "SELECT"]
    review.set_enabled(False)
    assert client.exists(f"{namespace}:cmdlog") == 0 and client.exists(f"{namespace}:cmdlog:enabled") == 0


class RedisHarness:
    def __init__(self, client: Any, namespace: str) -> None:
        self.review = RedisCommandReview(client, namespace)
        self.monitor = RedisCommandMonitor(self.review, SqlTracer(), FakeClock(NOW))

    def enable(self) -> None:
        self.review.set_enabled(True)

    def results(self) -> list[tuple[str, str]]:
        return [(log.request_key, log.result) for log in reversed(self.review.list(0, LIMIT).rows)]


class TestRedisCommandMonitorOnRedis(CommandMonitorContract):
    @pytest.fixture
    def harness(self, redis_client: tuple[Any, str]) -> RedisHarness:
        return RedisHarness(*redis_client)
