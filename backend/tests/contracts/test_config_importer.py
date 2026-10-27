"""`ConfigImporter` 的契约测试（C08 第 4 节；报告见 C08 第 1 节的 ImportReport）。

真实实现（config）的测试继承 `ConfigImporterContract`，提供 `harness` fixture，实现 `ConfigImporterHarness`。
测试用的配置是 support 中自洽的最小配置，加上一个字典和一个 Lookup。C06 第 10 节的逐条校验由 config 自己的测试
（T-CF-1）验证；这里检查整批校验、引用可以指向已有配置和本批其他项、已有的项不覆盖。
"""

from __future__ import annotations

from typing import Any, Protocol

import pytest

from cost_platform.contracts.fakes import FakeConfigImporter
from cost_platform.contracts.ports import ConfigImporter
from cost_platform.contracts.types import ConfigDraft, ErrorCode, PlatformError

from .support import CT_PAGE_A, CT_SAVE_A, CT_TABLE, ct_entity, ct_page, ct_save_operation, doc_json

DICT = ConfigDraft(type="dict", key="CT_STATUS", name="状态", content=doc_json("C06", 12))
DICT_CHANGED = ConfigDraft(type="dict", key="CT_STATUS", name="状态（改）",
                           content={"items": [{"value": "9", "label": "改过", "order": 1}]})
LOOKUP = ConfigDraft(type="lookup", key="CT_GOODS_LOOKUP", name="物料",
                     content={"table": CT_TABLE, "columns": ["GOODSID", "NAME"], "keywordColumns": ["NAME"], "orderBy": "GOODSID"})
BROKEN = ConfigDraft(type="dict", key="CT_BROKEN", name="缺少 order", content={"items": [{"value": "1", "label": "启用"}]})
BROKEN_2 = ConfigDraft(type="dict", key="CT_BROKEN_2", name="缺少 label", content={"items": [{"value": "1", "order": 1}]})
ENTITY = ct_entity()
OPERATION = ct_save_operation(CT_SAVE_A)
PAGE = ct_page(CT_PAGE_A, CT_SAVE_A)


class ConfigImporterHarness(Protocol):
    importer: ConfigImporter

    def prepare_schema(self, items: list[ConfigDraft]) -> None:
        """在数据库中准备这些配置项用到的表、列和序列（真实实现在 d_cg 上建 T_CT_ 开头的测试表）。"""
        ...

    def stored(self, config_type: str, key: str) -> dict[str, Any] | None:
        """读出已保存的配置项内容；没有时为 None。"""
        ...


def _import(harness: ConfigImporterHarness, items: list[ConfigDraft]) -> Any:
    harness.prepare_schema(items)
    return harness.importer.import_items(items)


def _at(path: str, index: int) -> bool:
    """`path` 以本批中的位置 `items[<index>]` 开头，后面可以接内容中的位置（C08 第 4 节）。"""
    prefix = f"items[{index}]"
    return path == prefix or path.startswith((prefix + ".", prefix + "["))


def _rejected(harness: ConfigImporterHarness, items: list[ConfigDraft]) -> PlatformError:
    harness.prepare_schema(items)
    with pytest.raises(PlatformError) as caught:
        harness.importer.import_items(items)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    return caught.value


class ConfigImporterContract:
    @pytest.fixture
    def harness(self) -> ConfigImporterHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_valid_items_are_saved(self, harness: ConfigImporterHarness) -> None:
        report = _import(harness, [DICT, LOOKUP])
        assert report.imported == 2
        assert report.skipped == []
        assert harness.stored("dict", "CT_STATUS") == DICT.content
        assert harness.stored("lookup", "CT_GOODS_LOOKUP") == LOOKUP.content

    def test_invalid_item_is_rejected(self, harness: ConfigImporterHarness) -> None:
        """与前端保存使用同一套校验：不合法时抛 422 VALIDATION_FAILED，明细指出配置项，不写入。"""
        error = _rejected(harness, [BROKEN])
        assert {(d.config_type, d.config_key) for d in error.details} == {("dict", "CT_BROKEN")}
        assert harness.stored("dict", "CT_BROKEN") is None

    def test_every_invalid_item_is_listed(self, harness: ConfigImporterHarness) -> None:
        error = _rejected(harness, [BROKEN, DICT, BROKEN_2])
        assert {d.config_key for d in error.details} == {"CT_BROKEN", "CT_BROKEN_2"}

    def test_batch_is_all_or_nothing(self, harness: ConfigImporterHarness) -> None:
        """整批校验：有一项不通过时，本批合法的项也不写入。"""
        error = _rejected(harness, [LOOKUP, BROKEN])
        assert {d.config_key for d in error.details} == {"CT_BROKEN"}
        assert harness.stored("lookup", "CT_GOODS_LOOKUP") is None

    def test_references_within_batch(self, harness: ConfigImporterHarness) -> None:
        """引用可以指向本批的其他项，与它们在批中的先后无关。"""
        report = _import(harness, [PAGE, OPERATION, ENTITY])
        assert report.imported == 3
        assert harness.stored("page", CT_PAGE_A) == PAGE.content

    def test_references_to_existing_items(self, harness: ConfigImporterHarness) -> None:
        _import(harness, [ENTITY])
        report = _import(harness, [PAGE, OPERATION])
        assert report.imported == 2
        assert harness.stored("operation", CT_SAVE_A) == OPERATION.content

    def test_missing_reference_is_rejected(self, harness: ConfigImporterHarness) -> None:
        """引用的实体既不在已有配置中，也不在本批中：整批不写。"""
        error = _rejected(harness, [PAGE, OPERATION])
        assert ("page", CT_PAGE_A) in {(d.config_type, d.config_key) for d in error.details}
        assert harness.stored("page", CT_PAGE_A) is None
        assert harness.stored("operation", CT_SAVE_A) is None

    def test_existing_items_are_skipped(self, harness: ConfigImporterHarness) -> None:
        """已有同类型、同编码的配置项不覆盖，列入 skipped；imported 只数实际导入的项。"""
        _import(harness, [DICT])
        report = _import(harness, [DICT_CHANGED, LOOKUP])
        assert report.imported == 1
        assert [ident for ident, _ in report.skipped] == ["config:dict/CT_STATUS"]
        assert all(reason for _, reason in report.skipped)
        assert harness.stored("dict", "CT_STATUS") == DICT.content
        assert harness.stored("lookup", "CT_GOODS_LOOKUP") == LOOKUP.content

    def test_existing_items_are_not_validated(self, harness: ConfigImporterHarness) -> None:
        """与已有项同编码的项不参与校验：即使它的内容不合法，本批其余的项照常导入。"""
        _import(harness, [DICT])
        invalid_twin = ConfigDraft(type="dict", key="CT_STATUS", name="状态", content=BROKEN.content)
        report = _import(harness, [invalid_twin, LOOKUP])
        assert report.imported == 1
        assert [ident for ident, _ in report.skipped] == ["config:dict/CT_STATUS"]
        assert harness.stored("dict", "CT_STATUS") == DICT.content

    def test_reimport_writes_nothing(self, harness: ConfigImporterHarness) -> None:
        _import(harness, [DICT, LOOKUP])
        report = _import(harness, [DICT, LOOKUP])
        assert report.imported == 0
        assert sorted(ident for ident, _ in report.skipped) == ["config:dict/CT_STATUS", "config:lookup/CT_GOODS_LOOKUP"]

    @pytest.mark.parametrize("twin", [DICT_CHANGED, DICT], ids=["content-differs", "content-identical"])
    def test_duplicates_in_batch_are_rejected(self, harness: ConfigImporterHarness, twin: ConfigDraft) -> None:
        """同一批中两项类型和编码相同：内容不同或完全相同都整批不写，明细列出这两项，`path` 带它们在批中的位置。"""
        error = _rejected(harness, [LOOKUP, DICT, twin])
        found = sorted((d.config_type, d.config_key, d.path or "") for d in error.details)
        assert [(t, k) for t, k, _ in found] == [("dict", "CT_STATUS"), ("dict", "CT_STATUS")]
        assert _at(found[0][2], 1) and _at(found[1][2], 2)
        assert all(d.message for d in error.details)
        assert harness.stored("dict", "CT_STATUS") is None
        assert harness.stored("lookup", "CT_GOODS_LOOKUP") is None

    def test_duplicates_of_existing_item_are_rejected(self, harness: ConfigImporterHarness) -> None:
        """重复的项与已有配置项相同时也拒绝，不当作已有的项跳过；已有的项不变。"""
        _import(harness, [DICT])
        error = _rejected(harness, [DICT_CHANGED, DICT, LOOKUP])
        paths = sorted(d.path or "" for d in error.details)
        assert len(paths) == 2 and _at(paths[0], 0) and _at(paths[1], 1)
        assert harness.stored("dict", "CT_STATUS") == DICT.content
        assert harness.stored("lookup", "CT_GOODS_LOOKUP") is None

    def test_duplicates_listed_with_other_invalid_items(self, harness: ConfigImporterHarness) -> None:
        """有重复项时，其余不通过的项也照常列出，调用方一次就能改完。"""
        error = _rejected(harness, [DICT, BROKEN, DICT_CHANGED])
        assert sorted(d.config_key for d in error.details if d.config_key == "CT_STATUS") == ["CT_STATUS", "CT_STATUS"]
        assert "CT_BROKEN" in {d.config_key for d in error.details}

    def test_detail_path_starts_with_batch_position(self, harness: ConfigImporterHarness) -> None:
        """每条明细的 `path` 以 `items[<序号>]` 开头，序号是这一项在本批中的位置（从 0 起）；
        内容不符合 C06 结构的项，后面接内容中的位置（C08 第 4 节）。"""
        error = _rejected(harness, [DICT, BROKEN, LOOKUP, PAGE, OPERATION])
        paths: dict[str, list[str]] = {}
        for d in error.details:
            paths.setdefault(d.config_key or "", []).append(d.path or "")
        assert set(paths) >= {"CT_BROKEN", CT_PAGE_A}
        assert all(p.startswith(("items[1].", "items[1][")) for p in paths["CT_BROKEN"])
        assert all(_at(p, 3) for p in paths[CT_PAGE_A])


class FakeConfigImporterHarness:
    def __init__(self) -> None:
        self.importer = FakeConfigImporter()

    def prepare_schema(self, items: list[ConfigDraft]) -> None:
        """替代实现不检查表结构，不需要准备。"""

    def stored(self, config_type: str, key: str) -> dict[str, Any] | None:
        item = self.importer.items.get((config_type, key))
        return None if item is None else item.content


class TestFakeConfigImporter(ConfigImporterContract):
    @pytest.fixture
    def harness(self) -> FakeConfigImporterHarness:
        return FakeConfigImporterHarness()
