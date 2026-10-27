"""`DeliveryDispatcher` 的契约测试（C08 第 10 节；状态见 delivery 的 DL-02 和 C09 的投递记录）。

真实实现（delivery）的测试继承 `DeliveryDispatcherContract`，提供 `harness` fixture，实现 `DeliveryDispatcherHarness`。
"""

from __future__ import annotations

from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeDeliveryDispatcher
from cost_platform.contracts.ports import DeliveryDispatcher

OK = "00000000-0000-4000-8000-0000000000d1"
FAILS = "00000000-0000-4000-8000-0000000000d2"


class DeliveryDispatcherHarness(Protocol):
    dispatcher: DeliveryDispatcher

    def register(self, delivery_id: str, *, fails: bool) -> None:
        """登记一条已提交、等待发送的投递记录；`fails` 为 True 时这条记录发送失败。"""
        ...

    def status(self, delivery_id: str) -> str:
        """投递记录的状态：pending、sent、failed、abandoned。"""
        ...


class DeliveryDispatcherContract:
    @pytest.fixture
    def harness(self) -> DeliveryDispatcherHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_sent(self, harness: DeliveryDispatcherHarness) -> None:
        harness.register(OK, fails=False)
        harness.dispatcher.dispatch_now([OK])
        assert harness.status(OK) == "sent"

    def test_failure_is_recorded_not_raised(self, harness: DeliveryDispatcherHarness) -> None:
        """发送失败只记录，不抛出，由后台重试；同一批中其他记录照常发送。失败后记成哪个状态属于 delivery 的 DL-02。"""
        harness.register(FAILS, fails=True)
        harness.register(OK, fails=False)
        harness.dispatcher.dispatch_now([FAILS, OK])
        assert harness.status(FAILS) != "sent"
        assert harness.status(OK) == "sent"

    def test_empty(self, harness: DeliveryDispatcherHarness) -> None:
        harness.dispatcher.dispatch_now([])


class FakeDeliveryDispatcherHarness:
    def __init__(self) -> None:
        self.dispatcher = FakeDeliveryDispatcher()

    def register(self, delivery_id: str, *, fails: bool) -> None:
        self.dispatcher.register(delivery_id, fails=fails)

    def status(self, delivery_id: str) -> str:
        return self.dispatcher.status[delivery_id]


class TestFakeDeliveryDispatcher(DeliveryDispatcherContract):
    @pytest.fixture
    def harness(self) -> FakeDeliveryDispatcherHarness:
        return FakeDeliveryDispatcherHarness()
