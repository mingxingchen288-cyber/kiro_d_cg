"""`IdGenerator` 的契约测试（C08 第 12 节）。真实实现（assembly）的测试继承 `IdGeneratorContract`，提供 `harness` fixture。"""

from __future__ import annotations

import re
from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakeIdGenerator
from cost_platform.contracts.ports import IdGenerator

# C01 第 5 节：请求键、事件编号、投递编号都是小写 UUID
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class IdGeneratorHarness(Protocol):
    ids: IdGenerator


class IdGeneratorContract:
    @pytest.fixture
    def harness(self) -> IdGeneratorHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_lowercase_uuid(self, harness: IdGeneratorHarness) -> None:
        for _ in range(50):
            value = harness.ids.uuid()
            assert _UUID.fullmatch(value), value

    def test_distinct(self, harness: IdGeneratorHarness) -> None:
        values = [harness.ids.uuid() for _ in range(500)]
        assert len(set(values)) == len(values)


class FakeIdGeneratorHarness:
    def __init__(self) -> None:
        self.ids = FakeIdGenerator()


class TestFakeIdGenerator(IdGeneratorContract):
    @pytest.fixture
    def harness(self) -> FakeIdGeneratorHarness:
        return FakeIdGeneratorHarness()


def test_fake_ids_are_predictable() -> None:
    ids = FakeIdGenerator()
    assert [ids.uuid(), ids.uuid()] == ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"]
