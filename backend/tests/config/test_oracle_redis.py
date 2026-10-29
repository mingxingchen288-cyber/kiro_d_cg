"""真实验证（d_cg + Redis）：在 Oracle 和 Redis 上重复保存各步之后的中断（T-CF-3）、读取快照的 Redis 往返次数（T-CF-4）、
启动预热（T-CF-5）。这次不运行；前提见 real_support.py。Redis 用单独的命名空间，测试结束时删除。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine

from cost_platform.config.redis_cache import RedisConfigCache
from cost_platform.config.runtime import ConfigRuntime, RecoveryTask
from cost_platform.contracts.types import ErrorCode, PlatformError

from .real_support import OracleEnv, drop_namespace, engine, fresh_namespace, redis_client  # noqa: F401 - fixture
from .support import KilledProcess, draft, kill_after
from .test_cache import CountingRedis
from .test_oracle import _items

pytestmark = [pytest.mark.oracle, pytest.mark.redis]


@pytest.fixture
def real(engine: Engine) -> Iterator[OracleEnv]:  # noqa: F811
    client, namespace = redis_client(), fresh_namespace()
    env = OracleEnv(engine, RedisConfigCache(client, namespace))
    env.counter = CountingRedis(client)  # type: ignore[attr-defined]
    env.cleanup()
    env.service.save(_items(), "1")
    yield env
    env.hook = None
    env.cleanup()
    drop_namespace(client, namespace)


def _revoke(env: OracleEnv) -> None:
    role = _items()[3]
    env.service.save([draft("role", "CT_ORA_ROLE", {**role.content, "pages": {}})], "1")


def test_e18_killed_after_commit(real: OracleEnv) -> None:
    """E18：提交后、写 Redis 前进程退出：下一个请求返回 403，只为它查一次 Oracle；Redis 被补写，发布配置变更。"""
    real.new_reader().read("CT_ORA_ROLE")
    real.hook = kill_after("committed")
    with pytest.raises(KilledProcess):
        _revoke(real)
    real.hook = None
    reader = real.new_reader()
    with pytest.raises(PlatformError) as caught:
        reader.read("CT_ORA_ROLE").page_view("CT_ORA_PAGE")
    assert caught.value.code is ErrorCode.PERMISSION_DENIED and reader.oracle_reads == 1
    assert real.cache.status() == (real.generation(), {})
    assert [e.payload.pages for e in real.publisher.events][-1] == ["CT_ORA_PAGE"]


def test_recovery_task_after_commit(real: OracleEnv) -> None:
    real.hook = kill_after("committed")
    with pytest.raises(KilledProcess):
        _revoke(real)
    real.hook = None
    task = RecoveryTask(real.uow, real.cache, real.publisher, real.clock, real.ids)
    assert task.run_once() == ["CT_ORA_PAGE"]
    assert real.cache.status() == (real.generation(), {})


def test_killed_before_commit(real: OracleEnv) -> None:
    generation = real.generation()
    real.hook = kill_after("pending")
    with pytest.raises(KilledProcess):
        _revoke(real)
    real.hook = None
    assert real.generation() == generation
    assert real.new_reader().read("CT_ORA_ROLE").page_view("CT_ORA_PAGE").page_code == "CT_ORA_PAGE"
    real.clock.advance(timedelta(seconds=61))
    RecoveryTask(real.uow, real.cache, real.publisher, real.clock, real.ids).run_once()
    assert real.cache.status()[1] == {}


def test_read_is_one_redis_round_trip(real: OracleEnv) -> None:
    """工程约定第 6 节：统计每个请求发往 Redis 的命令数，读取配置快照只有一次。"""
    reader = real.new_reader()
    reader.read("CT_ORA_ROLE")
    counter: Any = real.counter  # type: ignore[attr-defined]
    counter.commands.clear()
    reader.read("CT_ORA_ROLE")
    assert counter.commands == ["EVALSHA"] and reader.oracle_reads == 0


def test_warm_up_on_d_cg_and_redis(real: OracleEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """用 d_cg 中的配置在 Redis 上预热，记录角色数、规则包数和耗时（写到测试输出）。"""
    reader = real.new_reader()
    report = ConfigRuntime(real.uow, real.cache, reader).warm_up()
    print(f"预热：角色 {report.roles} 个，规则包 {report.packs} 个，耗时 {report.seconds:.3f} 秒，代号 {report.generation}")
    assert report.roles >= 1 and report.generation == real.generation()
    counter: Any = real.counter  # type: ignore[attr-defined]
    counter.commands.clear()
    reader.read("CT_ORA_ROLE")
    assert counter.commands == ["EVALSHA"] and reader.oracle_reads == 0
