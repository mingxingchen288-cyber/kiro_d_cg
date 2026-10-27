"""`CommandExecutor` 的契约测试（C08 第 5 节；判重和失败见 C02 第 3 节）。

真实实现（write-pipeline）的测试继承 `CommandExecutorContract`，提供 `harness` fixture，实现 `CommandExecutorHarness`。
"""

from __future__ import annotations

from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeCommandExecutor
from cost_platform.contracts.ports import CommandExecutor
from cost_platform.contracts.types import Command, CommandResult, ErrorCode, ExecutionContext, PlatformError

from .support import context, sample_command

KEY_A = "00000000-0000-4000-8000-00000000c001"
KEY_B = "00000000-0000-4000-8000-00000000c002"


class CommandExecutorHarness(Protocol):
    executor: CommandExecutor

    def context(self, user_id: str) -> ExecutionContext:
        """这个用户的执行上下文。"""
        ...

    def command(self, request_key: str, *, variant: int = 0) -> Command:
        """一个能执行成功的命令；`variant` 不同时内容不同（内容摘要不同）。"""
        ...

    def fail_next(self, error: PlatformError) -> None:
        """让下一次执行在中途失败并抛出 `error`。"""
        ...

    def executions(self) -> int:
        """到目前为止真正执行（没有被判重直接返回）的命令数。"""
        ...


class CommandExecutorContract:
    @pytest.fixture
    def harness(self) -> CommandExecutorHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_result_echoes_request_key(self, harness: CommandExecutorHarness) -> None:
        result = harness.executor.execute(harness.command(KEY_A), harness.context("112"))
        assert isinstance(result, CommandResult)
        assert result.request_key == KEY_A

    def test_same_key_and_content_returns_original_result(self, harness: CommandExecutorHarness) -> None:
        ctx = harness.context("112")
        first = harness.executor.execute(harness.command(KEY_A), ctx)
        again = harness.executor.execute(harness.command(KEY_A), ctx)
        assert again == first
        assert harness.executions() == 1

    def test_same_key_different_content_is_rejected(self, harness: CommandExecutorHarness) -> None:
        ctx = harness.context("112")
        harness.executor.execute(harness.command(KEY_A), ctx)
        with pytest.raises(PlatformError) as caught:
            harness.executor.execute(harness.command(KEY_A, variant=1), ctx)
        assert caught.value.code is ErrorCode.IDEMPOTENCY_KEY_REUSED

    def test_keys_are_per_user(self, harness: CommandExecutorHarness) -> None:
        harness.executor.execute(harness.command(KEY_A), harness.context("112"))
        harness.executor.execute(harness.command(KEY_A, variant=1), harness.context("113"))
        assert harness.executions() == 2

    def test_failed_command_can_be_resubmitted(self, harness: CommandExecutorHarness) -> None:
        """失败的命令整笔回滚、不留下命令记录，同一请求键可以重新提交（C02 第 3 节）。"""
        ctx = harness.context("112")
        harness.fail_next(PlatformError(ErrorCode.RULE_REJECTED, "规则拒绝"))
        with pytest.raises(PlatformError) as caught:
            harness.executor.execute(harness.command(KEY_B), ctx)
        assert caught.value.code is ErrorCode.RULE_REJECTED
        result = harness.executor.execute(harness.command(KEY_B, variant=1), ctx)
        assert result.request_key == KEY_B


class FakeCommandExecutorHarness:
    def __init__(self) -> None:
        self.executor = FakeCommandExecutor()

    def context(self, user_id: str) -> ExecutionContext:
        return context(user_id)

    def command(self, request_key: str, *, variant: int = 0) -> Command:
        return sample_command(requestKey=request_key, params={"variant": variant})

    def fail_next(self, error: PlatformError) -> None:
        self.executor.fail("execute", error)

    def executions(self) -> int:
        return len(self.executor.executed)


class TestFakeCommandExecutor(CommandExecutorContract):
    @pytest.fixture
    def harness(self) -> FakeCommandExecutorHarness:
        return FakeCommandExecutorHarness()


def test_fake_respond_and_responder_errors() -> None:
    """替代实现：结果由 respond 给出；respond 抛出的错误不留下结果。"""
    calls = []

    def respond(command: Command, ctx: ExecutionContext) -> CommandResult:
        calls.append(command.request_key)
        if len(calls) == 1:
            raise PlatformError(ErrorCode.DOCUMENT_BUSY, "等锁超时")
        return CommandResult(request_key=command.request_key, outcome="saved", rows=[], id_map={}, prompts=[], skipped=[],
                             approvals=[])

    executor = FakeCommandExecutor(respond)
    with pytest.raises(PlatformError):
        executor.execute(sample_command(requestKey=KEY_A), context())
    assert executor.execute(sample_command(requestKey=KEY_A), context()).outcome == "saved"
    assert calls == [KEY_A, KEY_A]
