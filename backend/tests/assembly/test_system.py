"""assembly 的插件 `system` 提供的 `Clock`、`IdGenerator`（C08 第 12 节）：跑 contracts 的契约测试。"""

from __future__ import annotations

import pytest

from cost_platform.assembly.plugins import SystemClock, UuidGenerator

from ..contracts.test_clock import ClockContract
from ..contracts.test_id_generator import IdGeneratorContract


class _Harness:
    def __init__(self) -> None:
        self.clock = SystemClock()
        self.ids = UuidGenerator()


class TestSystemClock(ClockContract):
    @pytest.fixture
    def harness(self) -> _Harness:
        return _Harness()


class TestUuidGenerator(IdGeneratorContract):
    @pytest.fixture
    def harness(self) -> _Harness:
        return _Harness()
