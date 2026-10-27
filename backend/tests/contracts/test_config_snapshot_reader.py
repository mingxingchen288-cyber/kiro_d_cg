"""`ConfigSnapshotReader` 和 `ConfigSnapshot` 的契约测试（C08 第 4 节，C04）。

真实实现（config）的测试继承 `ConfigSnapshotReaderContract`，提供 `harness` fixture，实现 `ConfigSnapshotReaderHarness`。
页面视图的生成（CF-03）、菜单的过滤（CF-12）、规则包的编译和 Redis 往返次数（CF-06）由 config 自己的测试验证。
"""

from __future__ import annotations

import copy
from typing import Any, Protocol

import pytest

from cost_platform.contracts.fakes import FakeConfigSnapshot, FakeConfigSnapshotReader
from cost_platform.contracts.ports import ConfigSnapshotReader
from cost_platform.contracts.types import ConfigDraft, ErrorCode, PlatformError, parse_config_content

from .support import doc_json

ROLE_CODE = "CT_ACCOUNTANT"


def _flow(seq: int, key: str, operation: str) -> ConfigDraft:
    item = doc_json("C06", 6)  # 7.4 样例一
    content = copy.deepcopy(item["content"])
    content.pop("display")
    content.update(createdSeq=seq, sourceOperation=operation)
    return ConfigDraft(type="approvalFlow", key=key, name=key, content=content)


def _items(role_name: str = "成本会计") -> list[ConfigDraft]:
    return [
        ConfigDraft(type="role", key=ROLE_CODE, name=role_name, content={**doc_json("C06", 10), "name": role_name}),
        ConfigDraft(type="entity", key="COST_PINGGU", name="成本核算", content=doc_json("C06", 1)),
        ConfigDraft(type="operation", key="COST_PINGGU.save", name="保存", content=doc_json("C06", 3)),
        _flow(7, "CT_FLOW_LATE", "COST_PINGGU.save"),
        _flow(3, "CT_FLOW_EARLY", "COST_PINGGU.save"),
        _flow(5, "CT_FLOW_OTHER", "COST_GOODS_PRICE.save"),
    ]


def _parsed(items: list[ConfigDraft], key: str) -> Any:
    item = next(i for i in items if i.key == key)
    return parse_config_content(item.type, item.content)


class ConfigSnapshotReaderHarness(Protocol):
    reader: ConfigSnapshotReader

    def save(self, items: list[ConfigDraft]) -> None:
        """保存这些配置项，保存后生效（配置代号加一）。"""
        ...

    def make_unavailable(self) -> None:
        """让配置读不到：Redis 和 Oracle 都不可用。"""
        ...


class ConfigSnapshotReaderContract:
    @pytest.fixture
    def harness(self) -> ConfigSnapshotReaderHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    def test_snapshot_belongs_to_role(self, harness: ConfigSnapshotReaderHarness) -> None:
        items = _items()
        harness.save(items)
        snapshot = harness.reader.read(ROLE_CODE)
        assert snapshot.role_code == ROLE_CODE
        assert isinstance(snapshot.version, int)
        assert snapshot.role() == _parsed(items, ROLE_CODE)

    def test_items_by_code(self, harness: ConfigSnapshotReaderHarness) -> None:
        items = _items()
        harness.save(items)
        snapshot = harness.reader.read(ROLE_CODE)
        assert snapshot.entity("COST_PINGGU") == _parsed(items, "COST_PINGGU")
        assert snapshot.operation("COST_PINGGU.save") == _parsed(items, "COST_PINGGU.save")
        assert snapshot.approval_flow("CT_FLOW_OTHER") == _parsed(items, "CT_FLOW_OTHER")

    def test_approval_flows_by_operation_in_created_order(self, harness: ConfigSnapshotReaderHarness) -> None:
        harness.save(_items())
        flows = harness.reader.read(ROLE_CODE).approval_flows("COST_PINGGU.save")
        assert [(f.created_seq, f.source_operation) for f in flows] == [(3, "COST_PINGGU.save"), (7, "COST_PINGGU.save")]

    def test_snapshot_does_not_change_after_save(self, harness: ConfigSnapshotReaderHarness) -> None:
        """C04：已经取得的快照在之后的保存中不变；保存后读到的是更新的版本。"""
        harness.save(_items())
        before = harness.reader.read(ROLE_CODE)
        role_before = before.role()
        harness.save(_items(role_name="成本会计（改）"))
        after = harness.reader.read(ROLE_CODE)
        assert before.role() == role_before
        assert after.role().name == "成本会计（改）"
        assert after.version > before.version

    def test_unavailable(self, harness: ConfigSnapshotReaderHarness) -> None:
        harness.save(_items())
        harness.make_unavailable()
        with pytest.raises(PlatformError) as caught:
            harness.reader.read(ROLE_CODE)
        assert caught.value.code is ErrorCode.CONFIG_UNAVAILABLE


class FakeConfigSnapshotReaderHarness:
    def __init__(self) -> None:
        self.reader = FakeConfigSnapshotReader()
        self._version = 0

    def save(self, items: list[ConfigDraft]) -> None:
        self._version += 1
        self.reader.put(FakeConfigSnapshot.from_items(version=self._version, role_code=ROLE_CODE, items=items))

    def make_unavailable(self) -> None:
        self.reader.fail("read", PlatformError(ErrorCode.CONFIG_UNAVAILABLE, "读不到配置"), times=None)


class TestFakeConfigSnapshotReader(ConfigSnapshotReaderContract):
    @pytest.fixture
    def harness(self) -> FakeConfigSnapshotReaderHarness:
        return FakeConfigSnapshotReaderHarness()


def test_fake_snapshot_returns_given_views_menus_and_packs() -> None:
    """替代实现：页面视图、菜单和规则包句柄按给出的内容返回。"""
    from cost_platform.contracts.types import MenuItem, PageView, parse_wire

    view = parse_wire(PageView, doc_json("C05", 0))
    handle = object()
    menu = [MenuItem(key="COST_PINGGU", title="成本核算", kind="page", page_code="COST_PINGGU")]
    snapshot = FakeConfigSnapshot.from_items(version=1, role_code=ROLE_CODE, items=_items(), page_views={"COST_PINGGU": view},
                                             packs={"COST_PINGGU": handle})
    assert snapshot.page_view("COST_PINGGU") is view
    assert snapshot.rules_pack("COST_PINGGU") is handle
    assert FakeConfigSnapshot(version=1, role_code=ROLE_CODE, role=snapshot.role(), menus=menu).menus() == menu
