"""`CommandMonitor` 的契约测试（C08 第 5a 节，WP-17）。真实实现（write-pipeline 的命令审查）的测试继承
`CommandMonitorContract`，提供 `harness` fixture：`monitor`、`enable()` 打开审查、`results()` 按结束的先后给出
（请求键、结果），结果为 saved（成功）、rejected（业务拒绝，4xx）或 failed（5xx 和其他异常）。"""

from __future__ import annotations

from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeCommandMonitor
from cost_platform.contracts.ports import CommandMonitor
from cost_platform.contracts.types import ErrorCode, PlatformError

from .support import context, sample_command


class CommandMonitorHarness(Protocol):
    monitor: CommandMonitor

    def enable(self) -> None: ...

    def results(self) -> list[tuple[str, str]]: ...


class CommandMonitorContract:
    @pytest.fixture
    def harness(self) -> CommandMonitorHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_saved_command_recorded(self, harness: CommandMonitorHarness) -> None:
        harness.enable()
        command = sample_command()
        with harness.monitor.watch(command, context()):
            pass
        assert harness.results() == [(command.request_key, "saved")]

    def test_rejected_command_recorded_and_error_kept(self, harness: CommandMonitorHarness) -> None:
        """成本单被审批冻结时保存被拒绝：错误照常抛出，记为 rejected。"""
        harness.enable()
        command = sample_command()
        with pytest.raises(PlatformError) as caught:
            with harness.monitor.watch(command, context()):
                raise PlatformError(ErrorCode.FROZEN_BY_APPROVAL, "单据已被审批冻结")
        assert caught.value.code is ErrorCode.FROZEN_BY_APPROVAL
        assert harness.results() == [(command.request_key, "rejected")]

    def test_failed_command_recorded(self, harness: CommandMonitorHarness) -> None:
        harness.enable()
        command = sample_command()
        with pytest.raises(RuntimeError):
            with harness.monitor.watch(command, context()):
                raise RuntimeError("连接断开")
        assert harness.results() == [(command.request_key, "failed")]


class FakeCommandMonitorHarness:
    def __init__(self) -> None:
        self.monitor = FakeCommandMonitor()

    def enable(self) -> None:
        pass

    def results(self) -> list[tuple[str, str]]:
        def outcome(code: ErrorCode | None) -> str:
            if code is None:
                return "saved"
            return "failed" if PlatformError(code, "").http_status >= 500 else "rejected"
        return [(key, outcome(code)) for key, code in self.monitor.watched]


class TestFakeCommandMonitor(CommandMonitorContract):
    @pytest.fixture
    def harness(self) -> FakeCommandMonitorHarness:
        return FakeCommandMonitorHarness()
