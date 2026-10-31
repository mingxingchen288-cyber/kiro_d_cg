"""启动预热（CF-13，T-CF-5 的模拟验证）。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from cost_platform.config.cache import SyncBatch
from cost_platform.config.runtime import ConfigStartupError
from cost_platform.contracts.types import ErrorCode, PackInvalidError, PlatformError

from .support import Env, draft, seed_drafts

ROLE_R = {"name": "成本会计", "admin": False, "pages": {"COST_PINGGU": {"buttons": ["system:save"]}}}


@pytest.fixture
def env() -> Env:
    env = Env()
    env.save([*seed_drafts(), draft("role", "R", ROLE_R)])
    return env


def test_after_warm_up_first_request_needs_no_oracle_and_no_compile(env: Env) -> None:
    """预热后，每个角色的第一个请求不再回查 Oracle，也不再编译规则包。"""
    reader = env.new_reader()
    runtime = env.runtime(reader)
    assert runtime.ready is False
    report = runtime.warm_up()
    assert runtime.ready is True
    # 角色：seed 的 ADMIN、技术中心和 R；规则包：成本核算、物料清单、审计追踪、产品信息维护、客户信息、外币管理
    assert (report.roles, report.packs, report.generation) == (3, 6, env.generation())
    compiled = reader.parsed.compiled
    env.cache.calls.clear()
    begins = len(env.uow.calls_to("begin"))
    for role in ("ADMIN", "R"):
        snapshot = reader.read(role)
        snapshot.page_view("COST_PINGGU")
        snapshot.rules_pack("COST_PINGGU")
    assert env.cache.calls == ["read", "read"] and reader.oracle_reads == 0
    assert len(env.uow.calls_to("begin")) == begins and reader.parsed.compiled == compiled == 6


def test_newer_redis_version_is_not_overwritten(env: Env) -> None:
    """Redis 中已有更新的版本时，预热的补写不覆盖它；缺少的项补上。"""
    newer = replace(env.records()["role/R"], name="更新的", generation=env.generation() + 1)
    env.cache.apply(SyncBatch(newer.generation, [newer]))
    del env.cache.index["page/COST_PINGGU"], env.cache.items["page/COST_PINGGU"]
    env.runtime(env.new_reader()).warm_up()
    assert env.cache.items["role/R"].name == "更新的"
    assert "page/COST_PINGGU" in env.cache.index


def test_pack_compile_failure_fails_startup(env: Env) -> None:
    env.engine.fail("load_pack", PackInvalidError("JDM 含不允许的节点"))
    runtime = env.runtime(env.new_reader())
    with pytest.raises(ConfigStartupError, match="规则包 [A-Z_]+ 编译失败"):
        runtime.warm_up()
    assert runtime.ready is False


def test_oracle_unavailable_fails_startup(env: Env) -> None:
    env.uow.fail("begin", PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "数据库暂时不可用"))
    with pytest.raises(ConfigStartupError):
        env.runtime(env.new_reader()).warm_up()


def test_redis_unavailable_retries_every_5_seconds(env: Env) -> None:
    """Redis 不可用时每 5 秒重试一次，期间 ready 保持 false；恢复后自动完成。"""
    env.cache.unavailable = True
    waits: list[float] = []
    runtime = env.runtime(env.new_reader(), sleep=lambda s: (waits.append(s), runtime_ready.append(runtime.ready),
                                                             setattr(env.cache, "unavailable", len(waits) < 2)))
    runtime_ready: list[bool] = []
    runtime.warm_up()
    assert waits == [5.0, 5.0] and runtime_ready == [False, False] and runtime.ready is True
    assert env.cache.generation == env.generation()
