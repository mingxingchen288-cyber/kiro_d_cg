"""`ConfigImporter` 的契约测试（C08 第 4 节；报告见 C08 第 1 节的 ImportReport）。

真实实现（config）的测试继承 `ConfigImporterContract`，提供 `harness` fixture，实现 `ConfigImporterHarness`。
C06 第 10 节的各条校验，以及引用指向已有配置和本批其他项，由 config 自己的测试（T-CF-1）验证；
这里用结构不合法的配置项检查导入会整批校验。
"""

from __future__ import annotations

from typing import Any, Protocol

import pytest

from cost_platform.contracts.fakes import FakeConfigImporter
from cost_platform.contracts.ports import ConfigImporter
from cost_platform.contracts.types import ConfigDraft, ErrorCode, PlatformError

from .support import doc_json

DICT = ConfigDraft(type="dict", key="CT_STATUS", name="状态", content=doc_json("C06", 12))
DICT_CHANGED = ConfigDraft(type="dict", key="CT_STATUS", name="状态（改）",
                           content={"items": [{"value": "9", "label": "改过", "order": 1}]})
LOOKUP = ConfigDraft(type="lookup", key="CT_GOODS", name="物料", content=doc_json("C06", 13))
BROKEN = ConfigDraft(type="dict", key="CT_BROKEN", name="缺少 order", content={"items": [{"value": "1", "label": "启用"}]})


class ConfigImporterHarness(Protocol):
    importer: ConfigImporter

    def stored(self, config_type: str, key: str) -> dict[str, Any] | None:
        """读出已保存的配置项内容；没有时为 None。"""
        ...


def _rejected(harness: ConfigImporterHarness, items: list[ConfigDraft]) -> PlatformError:
    with pytest.raises(PlatformError) as caught:
        harness.importer.import_items(items)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    return caught.value


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
        error = _rejected(harness, [BROKEN])
        assert [(d.config_type, d.config_key) for d in error.details] == [("dict", "CT_BROKEN")]
        assert harness.stored("dict", "CT_BROKEN") is None

    def test_batch_is_all_or_nothing(self, harness: ConfigImporterHarness) -> None:
        """整批校验：有一项不通过时，本批合法的项也不写入。"""
        error = _rejected(harness, [LOOKUP, BROKEN])
        assert {d.config_key for d in error.details} == {"CT_BROKEN"}
        assert harness.stored("lookup", "CT_GOODS") is None

    def test_existing_items_are_skipped(self, harness: ConfigImporterHarness) -> None:
        """已有同类型、同编码的配置项不覆盖，列入 skipped；imported 只数实际导入的项。"""
        harness.importer.import_items([DICT])
        report = harness.importer.import_items([DICT_CHANGED, LOOKUP])
        assert report.imported == 1
        assert [ident for ident, _ in report.skipped] == ["config:dict/CT_STATUS"]
        assert all(reason for _, reason in report.skipped)
        assert harness.stored("dict", "CT_STATUS") == DICT.content
        assert harness.stored("lookup", "CT_GOODS") == LOOKUP.content

    def test_reimport_writes_nothing(self, harness: ConfigImporterHarness) -> None:
        harness.importer.import_items([DICT, LOOKUP])
        report = harness.importer.import_items([DICT, LOOKUP])
        assert report.imported == 0
        assert sorted(ident for ident, _ in report.skipped) == ["config:dict/CT_STATUS", "config:lookup/CT_GOODS"]


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
