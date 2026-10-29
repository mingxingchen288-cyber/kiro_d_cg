"""`ContextProvider` 的契约测试（C08 第 15 节，C04）。真实实现（assembly 的 `http` 插件）的测试继承
`ContextProviderContract`，提供 `harness` fixture：`provider`，`request(is_write)` 给出已登录、已选角色的用户 112
（成本会计）在允许的来源发来的请求，写请求带正确的 CSRF 令牌。"""

from __future__ import annotations

from typing import Any, Protocol

import pytest

from cost_platform.contracts.fakes import FakeContextProvider
from cost_platform.contracts.ports import ContextProvider

from .support import context


class ContextProviderHarness(Protocol):
    provider: ContextProvider

    def request(self, is_write: bool) -> Any: ...


class ContextProviderContract:
    @pytest.fixture
    def harness(self) -> ContextProviderHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    @pytest.mark.parametrize("is_write", [False, True])
    def test_context_of_logged_in_user(self, harness: ContextProviderHarness, is_write: bool) -> None:
        """执行上下文：身份为会话的用户和选定的角色，配置快照属于这个角色，版本号取快照的版本，来源为用户本人。"""
        ctx = harness.provider.context(harness.request(is_write), is_write)
        assert (ctx.identity.user_id, ctx.identity.role_code) == ("112", "COST_ACCOUNTANT")
        assert ctx.config.role_code == "COST_ACCOUNTANT"
        assert ctx.config_version == ctx.config.version
        assert (ctx.origin.kind, ctx.origin.approval_id) == ("user", None)


class FakeContextProviderHarness:
    def __init__(self) -> None:
        self.provider = FakeContextProvider(context())

    def request(self, is_write: bool) -> Any:
        return object()


class TestFakeContextProvider(ContextProviderContract):
    @pytest.fixture
    def harness(self) -> FakeContextProviderHarness:
        return FakeContextProviderHarness()
