"""会话存储（模块说明第 2、5 节；ID-03、ID-05、ID-10）。

两种键：
- 会话 `{ns}:session:{sid}`：登录时写入，过期时间为空闲时长，用户的有效操作会重新计时；内容见 `SessionData`。
- 账号状态 `{ns}:user:{uid}:ver`：账号的当前版本，以及该版本下的启用状态、角色、账号名、姓名和部门（`AccountState`）。
  账号修改提交后写入新版本。会话里记着建立（或上次刷新）时的版本，两者不一致时按账号状态判断会话是否还有效，
  不用再查 Oracle。

会话编号为 `<userId>.<随机串>`：认证时由编号得出账号编号，一次读取同时取回会话和账号状态（Redis 为一条 MGET）。

`MemorySessions` 用于模拟验证和本机没有 Redis 的开发环境（进程重启会话即丢失，多进程之间不共享）；
`RedisSessions` 是上线用的实现，真实验证的测试标了 `redis`，本次没有运行。
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class SessionData:
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    role_code: str | None          # 还没有选定角色时为 None
    csrf_token: str
    version: int                   # 建立或上次刷新时的账号版本
    department_name: str | None = None  # 部门名称（C04 v2）；登录时、账号改了部门时、`/api/me` 时按数据库更新

    def refreshed(self, state: AccountState) -> SessionData:
        """账号改了账号名、姓名、部门等、但会话仍然有效时，按账号的当前状态刷新。"""
        return replace(self, username=state.username, display_name=state.display_name,
                       department_id=state.department_id, department_name=state.department_name,
                       version=state.version)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> SessionData:
        return cls(**json.loads(raw))


@dataclass(frozen=True)
class AccountState:
    user_id: str
    version: int
    enabled: bool
    role_codes: tuple[str, ...]
    username: str
    display_name: str
    department_id: str | None
    department_name: str | None = None

    def to_json(self) -> str:
        return json.dumps({**asdict(self), "role_codes": list(self.role_codes)}, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> AccountState:
        data = json.loads(raw)
        return cls(**{**data, "role_codes": tuple(data["role_codes"])})


class SessionStore(Protocol):
    """identity 内部的会话存储。`now`、`idle` 由服务按 `Clock` 和空闲时长给出；Redis 实现用自己的过期时间，不用 `now`。"""

    def put(self, session_id: str, data: SessionData, now: datetime, idle: timedelta) -> None:
        """写入会话，从 now 起重新计时。"""
        ...

    def replace(self, session_id: str, data: SessionData) -> None:
        """改写会话内容，过期时间不变；会话已不存在时不写。"""
        ...

    def read(self, session_id: str, user_id: str, now: datetime) -> tuple[SessionData | None, AccountState | None]:
        """一次读取会话和该账号的状态；会话不存在或已过期时第一项为 None。"""
        ...

    def touch(self, session_id: str, now: datetime, idle: timedelta) -> None:
        """从 now 起重新计时（ID-10）。"""
        ...

    def delete(self, session_id: str) -> None: ...

    def put_state(self, state: AccountState) -> None:
        """写入账号状态；已有的状态版本不低于 state 时不写。"""
        ...


class MemorySessions:
    """进程内存中的会话（模拟验证、本机开发）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, tuple[SessionData, datetime]] = {}
        self._states: dict[str, AccountState] = {}
        self._lock = threading.Lock()

    def put(self, session_id: str, data: SessionData, now: datetime, idle: timedelta) -> None:
        with self._lock:
            self._sessions[session_id] = (data, now + idle)

    def replace(self, session_id: str, data: SessionData) -> None:
        with self._lock:
            found = self._sessions.get(session_id)
            if found is not None:
                self._sessions[session_id] = (data, found[1])

    def read(self, session_id: str, user_id: str, now: datetime) -> tuple[SessionData | None, AccountState | None]:
        with self._lock:
            found = self._sessions.get(session_id)
            if found is not None and found[1] <= now:
                del self._sessions[session_id]
                found = None
            return (found[0] if found else None), self._states.get(user_id)

    def touch(self, session_id: str, now: datetime, idle: timedelta) -> None:
        with self._lock:
            found = self._sessions.get(session_id)
            if found is not None:
                self._sessions[session_id] = (found[0], now + idle)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def put_state(self, state: AccountState) -> None:
        with self._lock:
            current = self._states.get(state.user_id)
            if current is None or current.version < state.version:
                self._states[state.user_id] = state


def _millis(idle: timedelta) -> int:
    return int(idle.total_seconds() * 1000)


class RedisSessions:
    """Redis 中的会话。`client` 为 redis-py 的 `Redis`；`namespace` 取 `.env` 的 `PLATFORM_REDIS_NAMESPACE`。

    过期由 Redis 自己判断（`PX`、`PEXPIRE`），不用参数中的 `now`。
    """

    def __init__(self, client: Any, namespace: str) -> None:
        self._redis = client
        self._ns = namespace

    @classmethod
    def from_url(cls, url: str, namespace: str) -> RedisSessions:
        import redis

        return cls(redis.Redis.from_url(url), namespace)

    def _session_key(self, session_id: str) -> str:
        return f"{self._ns}:session:{session_id}"

    def _state_key(self, user_id: str) -> str:
        return f"{self._ns}:user:{user_id}:ver"

    def put(self, session_id: str, data: SessionData, now: datetime, idle: timedelta) -> None:
        self._redis.set(self._session_key(session_id), data.to_json(), px=_millis(idle))

    def replace(self, session_id: str, data: SessionData) -> None:
        self._redis.set(self._session_key(session_id), data.to_json(), keepttl=True, xx=True)

    def read(self, session_id: str, user_id: str, now: datetime) -> tuple[SessionData | None, AccountState | None]:
        session, state = self._redis.mget([self._session_key(session_id), self._state_key(user_id)])
        return (SessionData.from_json(session) if session else None), (AccountState.from_json(state) if state else None)

    def touch(self, session_id: str, now: datetime, idle: timedelta) -> None:
        self._redis.pexpire(self._session_key(session_id), _millis(idle))

    def delete(self, session_id: str) -> None:
        self._redis.delete(self._session_key(session_id))

    def put_state(self, state: AccountState) -> None:
        key, payload = self._state_key(state.user_id), state.to_json()

        def write_if_newer(pipe: Any) -> None:
            current = pipe.get(key)
            if current and AccountState.from_json(current).version >= state.version:
                return
            pipe.multi()
            pipe.set(key, payload)

        self._redis.transaction(write_if_newer, key)
