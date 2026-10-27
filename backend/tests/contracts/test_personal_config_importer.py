"""`PersonalConfigImporter` 的契约测试（C08 第 9 节）。

真实实现（queries-export）的测试继承 `PersonalConfigImporterContract`，提供 `harness` fixture，实现
`PersonalConfigImporterHarness`。
"""

from __future__ import annotations

from typing import Protocol

import pytest

from cost_platform.contracts.fakes import FakePersonalConfigImporter
from cost_platform.contracts.ports import PersonalConfigImporter
from cost_platform.contracts.types import PersonalConfig, PersonalConfigBatch, PersonalConfigEntry, parse_wire

from .support import doc_json

CONFIG = parse_wire(PersonalConfig, doc_json("C09", 1))
ENTRIES = [
    PersonalConfigEntry(user_id="9201", page_code="COST_PINGGU", config=CONFIG),
    PersonalConfigEntry(user_id="9202", page_code="COST_PINGGU", config=PersonalConfig(detail_mode="stack")),
]


class PersonalConfigImporterHarness(Protocol):
    importer: PersonalConfigImporter

    def stored(self, user_id: str, page_code: str) -> PersonalConfig | None:
        """读出这个用户在这个页面的个人配置；没有时为 None。"""
        ...


class PersonalConfigImporterContract:
    @pytest.fixture
    def harness(self) -> PersonalConfigImporterHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_imports_new_entries(self, harness: PersonalConfigImporterHarness) -> None:
        report = harness.importer.import_batch(PersonalConfigBatch(entries=ENTRIES))
        assert report.imported == len(ENTRIES)
        assert report.skipped == []
        for entry in ENTRIES:
            assert harness.stored(entry.user_id, entry.page_code) == entry.config


class FakePersonalConfigImporterHarness:
    def __init__(self) -> None:
        self.importer = FakePersonalConfigImporter()

    def stored(self, user_id: str, page_code: str) -> PersonalConfig | None:
        return self.importer.configs.get((user_id, page_code))


class TestFakePersonalConfigImporter(PersonalConfigImporterContract):
    @pytest.fixture
    def harness(self) -> FakePersonalConfigImporterHarness:
        return FakePersonalConfigImporterHarness()
