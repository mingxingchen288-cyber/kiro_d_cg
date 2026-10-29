"""assembly 的插件 `http` 提供的 `ContextProvider`（`RequestContexts`，C08 第 15 节）：跑 contracts 的契约测试。

会话、配置快照、时钟和编号用 contracts 的替代实现；请求用 starlette 的 `Request(scope)` 构造：cookie `cp_session` 为会话编号，
`origin` 为允许的来源，写请求带 `x-csrf-token`。"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from cost_platform.assembly.plugins import SESSION_COOKIE, RequestContexts
from cost_platform.contracts.fakes import FakeAuthenticator, FakeClock, FakeConfigSnapshotReader, FakeIdGenerator

from ..contracts.support import identity, snapshot
from ..contracts.test_context_provider import ContextProviderContract

ORIGIN = "http://localhost:9527"   # .env.example 的 PLATFORM_ALLOWED_ORIGINS
CSRF = "csrf-112"


class _Harness:
    def __init__(self) -> None:
        clock = FakeClock()
        authenticator = FakeAuthenticator(clock)
        self._session = authenticator.open_session(identity(), CSRF)
        self.provider = RequestContexts(authenticator, FakeConfigSnapshotReader([snapshot()]), clock, FakeIdGenerator(),
                                        {ORIGIN})

    def request(self, is_write: bool) -> Request:
        headers = [(b"cookie", f"{SESSION_COOKIE}={self._session}".encode()), (b"origin", ORIGIN.encode())]
        if is_write:
            headers.append((b"x-csrf-token", CSRF.encode()))
        return Request({"type": "http", "method": "POST" if is_write else "GET", "path": "/api/ping", "headers": headers})


class TestRequestContexts(ContextProviderContract):
    @pytest.fixture
    def harness(self) -> _Harness:
        return _Harness()
