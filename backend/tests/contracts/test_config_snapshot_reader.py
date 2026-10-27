"""`ConfigSnapshotReader` 和 `ConfigSnapshot` 的契约测试（C08 第 4 节，C04）。

真实实现（config）的测试继承 `ConfigSnapshotReaderContract`，提供 `harness` fixture，实现 `ConfigSnapshotReaderHarness`。
页面视图的生成（CF-03）、菜单的过滤（CF-12）、规则包的编译和 Redis 往返次数、缺项时回查 Oracle（CF-06）
由 config 自己的测试验证；这里检查回查后仍取不到时的错误。
"""

from __future__ import annotations

import copy
from typing import Any, Protocol

import pytest

from cost_platform.contracts.fakes import FakeConfigSnapshot, FakeConfigSnapshotReader
from cost_platform.contracts.ports import ConfigSnapshot, ConfigSnapshotReader
from cost_platform.contracts.types import ConfigDraft, ErrorCode, PageView, PlatformError, parse_config_content, parse_wire

from .support import doc_json

ROLE_CODE = "CT_ACCOUNTANT"
VISIBLE_PAGE = "COST_PINGGU"      # 角色配置（C06 第 8 节样例）中有这个页面
HIDDEN_PAGE = "CT_HIDDEN_PAGE"    # 配置中有这个页面，角色配置中没有


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
        ConfigDraft(type="page", key=VISIBLE_PAGE, name="成本核算", content=doc_json("C06", 2)),
        ConfigDraft(type="page", key=HIDDEN_PAGE, name="不给这个角色的页面", content=doc_json("C06", 2)),
        ConfigDraft(type="operation", key="COST_PINGGU.save", name="保存", content=doc_json("C06", 3)),
        _flow(7, "CT_FLOW_LATE", "COST_PINGGU.save"),
        _flow(3, "CT_FLOW_EARLY", "COST_PINGGU.save"),
        _flow(5, "CT_FLOW_OTHER", "COST_GOODS_PRICE.save"),
    ]


def _parsed(items: list[ConfigDraft], key: str) -> Any:
    item = next(i for i in items if i.key == key)
    return parse_config_content(item.type, item.content)


def _code(call: Any, *args: Any) -> ErrorCode:
    with pytest.raises(PlatformError) as caught:
        call(*args)
    return caught.value.code


class ConfigSnapshotReaderHarness(Protocol):
    reader: ConfigSnapshotReader

    def save(self, items: list[ConfigDraft]) -> None:
        """保存这些配置项（其他已保存的配置项不变），保存后生效（配置代号加一）。"""
        ...

    def delete(self, config_type: str, key: str) -> None:
        """删除一个配置项，删除后生效。"""
        ...

    def make_unavailable(self) -> None:
        """让配置读不到：Redis 和 Oracle 都不可用。"""
        ...


class ConfigSnapshotReaderContract:
    @pytest.fixture
    def harness(self) -> ConfigSnapshotReaderHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    @pytest.fixture
    def snapshot(self, harness: ConfigSnapshotReaderHarness) -> ConfigSnapshot:
        harness.save(_items())
        return harness.reader.read(ROLE_CODE)

    def test_snapshot_belongs_to_role(self, snapshot: ConfigSnapshot) -> None:
        assert snapshot.role_code == ROLE_CODE
        assert isinstance(snapshot.version, int)
        assert snapshot.role() == _parsed(_items(), ROLE_CODE)

    def test_items_by_code(self, snapshot: ConfigSnapshot) -> None:
        items = _items()
        assert snapshot.entity("COST_PINGGU") == _parsed(items, "COST_PINGGU")
        assert snapshot.operation("COST_PINGGU.save") == _parsed(items, "COST_PINGGU.save")
        assert snapshot.approval_flow("CT_FLOW_OTHER") == _parsed(items, "CT_FLOW_OTHER")

    def test_approval_flows_by_operation_in_created_order(self, snapshot: ConfigSnapshot) -> None:
        flows = snapshot.approval_flows("COST_PINGGU.save")
        assert [(f.created_seq, f.source_operation) for f in flows] == [(3, "COST_PINGGU.save"), (7, "COST_PINGGU.save")]

    def test_page_view(self, snapshot: ConfigSnapshot) -> None:
        view = snapshot.page_view(VISIBLE_PAGE)
        assert isinstance(view, PageView)
        assert view.page_code == VISIBLE_PAGE

    def test_page_view_errors(self, snapshot: ConfigSnapshot) -> None:
        """页面不存在为 NOT_FOUND，该角色不能访问为 PERMISSION_DENIED（C08 第 4 节，与 C09 的页面视图接口一致）。"""
        assert _code(snapshot.page_view, "CT_NO_SUCH_PAGE") is ErrorCode.NOT_FOUND
        assert _code(snapshot.page_view, HIDDEN_PAGE) is ErrorCode.PERMISSION_DENIED

    @pytest.mark.parametrize("method", ["entity", "operation", "approval_flow", "rules_pack"])
    def test_broken_reference_is_internal_error(self, snapshot: ConfigSnapshot, method: str) -> None:
        """已发布的配置中取不到被引用的项，说明内部引用断了。"""
        assert _code(getattr(snapshot, method), "CT_NO_SUCH_ITEM") is ErrorCode.INTERNAL_ERROR

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

    def test_deleted_role(self, harness: ConfigSnapshotReaderHarness) -> None:
        """角色被删除后，新的读取为 SESSION_ROLE_REVOKED；已经取得的快照照常可用。"""
        harness.save(_items())
        before = harness.reader.read(ROLE_CODE)
        harness.delete("role", ROLE_CODE)
        assert _code(harness.reader.read, ROLE_CODE) is ErrorCode.SESSION_ROLE_REVOKED
        assert before.role() == _parsed(_items(), ROLE_CODE)
        assert before.entity("COST_PINGGU") == _parsed(_items(), "COST_PINGGU")

    def test_unavailable(self, harness: ConfigSnapshotReaderHarness) -> None:
        harness.save(_items())
        harness.make_unavailable()
        assert _code(harness.reader.read, ROLE_CODE) is ErrorCode.CONFIG_UNAVAILABLE


class FakeConfigSnapshotReaderHarness:
    """把配置项合在一起，每次保存或删除后重建快照；角色配置中有的页面给出 C05 样例形状的页面视图。"""

    def __init__(self) -> None:
        self.reader = FakeConfigSnapshotReader()
        self._items: dict[tuple[str, str], ConfigDraft] = {}
        self._version = 0

    def _publish(self) -> None:
        self._version += 1
        items = list(self._items.values())
        if ("role", ROLE_CODE) not in self._items:
            self.reader.remove(ROLE_CODE)
            return
        role = parse_config_content("role", self._items[("role", ROLE_CODE)].content)
        views = {i.key: parse_wire(PageView, {**doc_json("C05", 0), "pageCode": i.key})
                 for i in items if i.type == "page" and i.key in role.pages}
        self.reader.put(FakeConfigSnapshot.from_items(version=self._version, role_code=ROLE_CODE, items=items, page_views=views))

    def save(self, items: list[ConfigDraft]) -> None:
        self._items.update({(i.type, i.key): i for i in items})
        self._publish()

    def delete(self, config_type: str, key: str) -> None:
        self._items.pop((config_type, key), None)
        self._publish()

    def make_unavailable(self) -> None:
        self.reader.fail("read", PlatformError(ErrorCode.CONFIG_UNAVAILABLE, "读不到配置"), times=None)


class TestFakeConfigSnapshotReader(ConfigSnapshotReaderContract):
    @pytest.fixture
    def harness(self) -> FakeConfigSnapshotReaderHarness:
        return FakeConfigSnapshotReaderHarness()


def test_fake_snapshot_returns_given_views_menus_and_packs() -> None:
    """替代实现：页面视图、菜单和规则包句柄按给出的内容返回。"""
    from cost_platform.contracts.types import MenuItem

    view = parse_wire(PageView, doc_json("C05", 0))
    handle = object()
    menu = [MenuItem(key="COST_PINGGU", title="成本核算", kind="page", page_code="COST_PINGGU")]
    snapshot = FakeConfigSnapshot.from_items(version=1, role_code=ROLE_CODE, items=_items(), page_views={"COST_PINGGU": view},
                                             packs={"COST_PINGGU": handle})
    assert snapshot.page_view("COST_PINGGU") is view
    assert snapshot.rules_pack("COST_PINGGU") is handle
    assert FakeConfigSnapshot(version=1, role_code=ROLE_CODE, role=snapshot.role(), menus=menu).menus() == menu
