"""`ConfigImporter` 的契约测试（C08 第 4 节）。

真实实现（config）的测试继承 `ConfigImporterContract`，提供 `harness` fixture，实现 `ConfigImporterHarness`。
C06 第 10 节的各条校验由 config 自己的测试（T-CF-1）验证；这里只用结构不合法的配置项检查导入会校验。
"""

from __future__ import annotations

from typing import Any, Protocol

import pytest

from cost_platform.contracts.fakes import FakeConfigImporter
from cost_platform.contracts.ports import ConfigImporter
from cost_platform.contracts.types import ConfigDraft, ErrorCode, PlatformError

from .support import doc_json

DICT = ConfigDraft(type="dict", key="CT_STATUS", name="状态", content=doc_json("C06", 12))
LOOKUP = ConfigDraft(type="lookup", key="CT_GOODS", name="物料", content=doc_json("C06", 13))
BROKEN = ConfigDraft(type="dict", key="CT_BROKEN", name="缺少 order", content={"items": [{"value": "1", "label": "启用"}]})


class ConfigImporterHarness(Protocol):
    importer: ConfigImporter

    def stored(self, config_type: str, key: str) -> dict[str, Any] | None:
        """读出已保存的配置项内容；没有时为 None。"""
        ...


class ConfigImporterContract:
    @pytest.fixture
    def harness(self) -> ConfigImporterHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_valid_items_are_saved(self, harness: ConfigImporterHarness) -> None:
        report = harness.importer.import_items([DICT, LOOKUP])
        assert report.imported == 2
        assert report.skipped == []
        assert harness.stored("dict", "CT_STATUS") == DICT.content
        assert harness.stored("lookup", "CT_GOODS") == LOOKUP.content

    def test_invalid_item_is_rejected(self, harness: ConfigImporterHarness) -> None:
        """与前端保存使用同一套校验：不合法时抛 422 VALIDATION_FAILED，明细指出配置项，不写入。"""
        with pytest.raises(PlatformError) as caught:
            harness.importer.import_items([BROKEN])
        assert caught.value.code is ErrorCode.VALIDATION_FAILED
        assert any(d.config_type == "dict" and d.config_key == "CT_BROKEN" for d in caught.value.details)
        assert harness.stored("dict", "CT_BROKEN") is None


class FakeConfigImporterHarness:
    def __init__(self) -> None:
        self.importer = FakeConfigImporter()

    def stored(self, config_type: str, key: str) -> dict[str, Any] | None:
        item = self.importer.items.get((config_type, key))
        return None if item is None else item.content


class TestFakeConfigImporter(ConfigImporterContract):
    @pytest.fixture
    def harness(self) -> FakeConfigImporterHarness:
        return FakeConfigImporterHarness()
