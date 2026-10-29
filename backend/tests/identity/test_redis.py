"""会话在 Redis 上的真实验证（T-ID-2 验收标准"会话在 Redis 上按时过期"）。本次没有运行（本机没有 Redis），由合并后统一运行。

连接取根目录 `.env` 的 `PLATFORM_REDIS_URL`、`PLATFORM_REDIS_NAMESPACE`；测试的键放在 `<namespace>:ct-identity` 下，结束后删除。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from cost_platform.contracts.types import AccountUpdate, ErrorCode, PlatformError
from cost_platform.identity.sessions import AccountState, RedisSessions, SessionData

from .support import ACCOUNTANT, Env, read_env

pytestmark = pytest.mark.redis

NOW = datetime(2026, 10, 24, 10, 0, 0)
DATA = SessionData(user_id="112", username="HY260404", display_name="程苏慧", department_id="581",
                   role_code=ACCOUNTANT, csrf_token="csrf-112", version=1)
STATE = AccountState(user_id="112", version=1, enabled=True, role_codes=(ACCOUNTANT,), username="HY260404",
                     display_name="程苏慧", department_id="581")


@pytest.fixture
def redis_sessions() -> Iterator[RedisSessions]:
    import redis

    env = read_env("PLATFORM_REDIS_URL", "PLATFORM_REDIS_NAMESPACE")
    client = redis.Redis.from_url(env["PLATFORM_REDIS_URL"])
    namespace = f"{env.get('PLATFORM_REDIS_NAMESPACE', 'cp')}:ct-identity"

    def cleanup() -> None:
        for key in client.scan_iter(f"{namespace}:*"):
            client.delete(key)

    cleanup()
    yield RedisSessions(client, namespace)
    cleanup()


def test_session_expires_on_time(redis_sessions: RedisSessions) -> None:
    redis_sessions.put("112.a", DATA, NOW, timedelta(seconds=2))
    assert redis_sessions.read("112.a", "112", NOW)[0] == DATA
    time.sleep(2.5)
    assert redis_sessions.read("112.a", "112", NOW)[0] is None


def test_touch_restarts_idle_time(redis_sessions: RedisSessions) -> None:
    redis_sessions.put("112.a", DATA, NOW, timedelta(seconds=2))
    time.sleep(1.2)
    redis_sessions.touch("112.a", NOW, timedelta(seconds=2))
    time.sleep(1.2)
    assert redis_sessions.read("112.a", "112", NOW)[0] == DATA
    time.sleep(1.2)
    assert redis_sessions.read("112.a", "112", NOW)[0] is None


def test_session_and_state_read_together(redis_sessions: RedisSessions) -> None:
    redis_sessions.put("112.a", DATA, NOW, timedelta(minutes=5))
    redis_sessions.put_state(STATE)
    redis_sessions.put_state(replace(STATE, version=3, enabled=False))
    redis_sessions.put_state(replace(STATE, version=2))  # 旧版本不覆盖新版本
    session, state = redis_sessions.read("112.a", "112", NOW)
    assert session == DATA and state is not None and (state.version, state.enabled) == (3, False)


def test_disabled_account_session_ends_on_redis(redis_sessions: RedisSessions) -> None:
    """ID-05 在 Redis 上：停用账号后，已登录的会话下一次请求为 SESSION_REQUIRED。账号数据仍在模拟的事务中。"""
    env = Env(sessions=redis_sessions)  # type: ignore[arg-type]
    uid = env.add_account("HY260404", "Abc123..", [ACCOUNTANT], display_name="程苏慧")
    session_id, _ = env.identity.login("HY260404", "Abc123..")
    assert env.identity.authenticate(session_id, None, False).user_id == uid
    env.admin.update_account(uid, AccountUpdate(display_name="程苏慧", department_id="581", role_codes=[ACCOUNTANT],
                                                enabled=False))
    with pytest.raises(PlatformError) as caught:
        env.identity.authenticate(session_id, None, False)
    assert caught.value.code is ErrorCode.SESSION_REQUIRED
