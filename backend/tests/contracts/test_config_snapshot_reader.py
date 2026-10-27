"""`ConfigSnapshotReader` 和 `ConfigSnapshot` 的契约测试（C08 第 4 节，C04）。

真实实现（config）的测试继承 `ConfigSnapshotReaderContract`，提供 `harness` fixture，实现 `ConfigSnapshotReaderHarness`。
测试用的配置是 support 中自洽的最小配置，能经 config 的真实保存流程保存。页面视图的生成（CF-03）、菜单的过滤（CF-12）、
规则包的编译、Redis 往返次数和缺项时回查 Oracle（CF-06）由 config 自己的测试验证；这里检查回查后仍取不到时的错误。
"""

from __future__ import annotations

from typing import Any, Protocol

import pytest

from cost_platform.contracts.fakes import FakeConfigSnapshot, FakeConfigSnapshotReader
from cost_platform.contracts.ports import ConfigSnapshot, ConfigSnapshotReader
from cost_platform.contracts.types import ConfigDraft, ErrorCode, PageView, PlatformError, parse_config_content, parse_wire

from .support import (
    CT_ENTITY,
    CT_PAGE_A,
    CT_PAGE_B,
    CT_ROLE_A,
    CT_ROLE_B,
    CT_SAVE_A,
    CT_SAVE_B,
    ct_base_items,
    ct_flow,
    ct_role,
    doc_json,
    without_created_seq,
)

# 同一个操作的三条审批流按 FIRST、SECOND、THIRD 的先后创建；编码正序为 THIRD、FIRST、SECOND，倒序为 SECOND、FIRST、THIRD，
# 都与创建先后不同，按编码排列的实现不能通过；test_created_order_survives_resave 再保存一次 FIRST，
# 按最后一次保存的先后排列（例如 ORDER BY 更新时间）的实现也不能通过
FIRST = ct_flow("CT_FLOW_M", CT_SAVE_A, "第一个建的审批流")
SECOND = ct_flow("CT_FLOW_Z", CT_SAVE_A, "第二个建的审批流")
THIRD = ct_flow("CT_FLOW_A", CT_SAVE_A, "第三个建的审批流")
OTHER = ct_flow("CT_FLOW_OTHER", CT_SAVE_B, "另一个操作的审批流")


def _parsed(item: ConfigDraft) -> Any:
    return without_created_seq(parse_config_content(item.type, item.content))


def _code(call: Any, *args: Any) -> ErrorCode:
    with pytest.raises(PlatformError) as caught:
        call(*args)
    return caught.value.code


class ConfigSnapshotReaderHarness(Protocol):
    reader: ConfigSnapshotReader

    def save(self, items: list[ConfigDraft]) -> None:
        """经保存流程保存这些配置项（其他已保存的配置项不变），保存后生效。配置引用的表和序列由 harness 自己准备。"""
        ...

    def delete(self, config_type: str, key: str) -> None:
        """删除一个配置项（没有被其他配置引用），删除后生效。"""
        ...

    def make_unavailable(self) -> None:
        """让配置读不到：Redis 和 Oracle 都不可用。"""
        ...


def save_all(harness: ConfigSnapshotReaderHarness) -> None:
    """依次保存基础配置和四条审批流，审批流的创建先后为 FIRST、SECOND、OTHER、THIRD。"""
    harness.save(ct_base_items())
    for flow in (FIRST, SECOND, OTHER, THIRD):
        harness.save([flow])


class ConfigSnapshotReaderContract:
    @pytest.fixture
    def harness(self) -> ConfigSnapshotReaderHarness:
        raise NotImplementedError("由具体实现的测试类提供")

    @pytest.fixture
    def snapshot(self, harness: ConfigSnapshotReaderHarness) -> ConfigSnapshot:
        save_all(harness)
        return harness.reader.read(CT_ROLE_A)

    def test_snapshot_belongs_to_role(self, snapshot: ConfigSnapshot) -> None:
        assert snapshot.role_code == CT_ROLE_A
        assert isinstance(snapshot.version, int)
        assert snapshot.role() == _parsed(ct_role(CT_ROLE_A, CT_PAGE_A, "契约测试角色甲"))

    def test_snapshots_are_per_role(self, harness: ConfigSnapshotReaderHarness) -> None:
        save_all(harness)
        a, b = harness.reader.read(CT_ROLE_A), harness.reader.read(CT_ROLE_B)
        assert (a.role_code, b.role_code) == (CT_ROLE_A, CT_ROLE_B)
        assert b.role() == _parsed(ct_role(CT_ROLE_B, CT_PAGE_B, "契约测试角色乙"))
        assert b.page_view(CT_PAGE_B).page_code == CT_PAGE_B
        assert _code(b.page_view, CT_PAGE_A) is ErrorCode.PERMISSION_DENIED

    def test_items_by_code(self, snapshot: ConfigSnapshot) -> None:
        base = {(i.type, i.key): i for i in ct_base_items()}
        assert snapshot.entity(CT_ENTITY) == _parsed(base[("entity", CT_ENTITY)])
        assert snapshot.operation(CT_SAVE_A) == _parsed(base[("operation", CT_SAVE_A)])
        assert without_created_seq(snapshot.approval_flow("CT_FLOW_OTHER")) == _parsed(OTHER)

    def test_approval_flows_by_operation_in_created_order(self, snapshot: ConfigSnapshot) -> None:
        flows = snapshot.approval_flows(CT_SAVE_A)
        assert [f.levels[0].entries[0].name for f in flows] == ["第一个建的审批流", "第二个建的审批流", "第三个建的审批流"]
        assert {f.source_operation for f in flows} == {CT_SAVE_A}
        assert flows[0].created_seq < flows[1].created_seq < flows[2].created_seq

    def test_created_order_survives_resave(self, harness: ConfigSnapshotReaderHarness) -> None:
        """重新保存先建的审批流后，先后仍按创建：`createdSeq` 第一次保存时分配，之后不变（C06 7.1）。"""
        save_all(harness)
        changed = ct_flow("CT_FLOW_M", CT_SAVE_A, "第一个建的审批流（改）")
        # 提交的内容里带一个很大的 createdSeq：config 不采用提交的值，先后照旧
        changed = changed.model_copy(update={"content": {**changed.content, "createdSeq": 999999}})
        harness.save([changed])
        flows = harness.reader.read(CT_ROLE_A).approval_flows(CT_SAVE_A)
        assert [f.levels[0].entries[0].name for f in flows] == ["第一个建的审批流（改）", "第二个建的审批流", "第三个建的审批流"]

    def test_page_view(self, snapshot: ConfigSnapshot) -> None:
        view = snapshot.page_view(CT_PAGE_A)
        assert isinstance(view, PageView)
        assert view.page_code == CT_PAGE_A

    def test_page_view_errors(self, snapshot: ConfigSnapshot) -> None:
        """页面不存在为 NOT_FOUND，该角色不能访问为 PERMISSION_DENIED（C08 第 4 节，与 C09 的页面视图接口一致）。"""
        assert _code(snapshot.page_view, "CT_NO_SUCH_PAGE") is ErrorCode.NOT_FOUND
        assert _code(snapshot.page_view, CT_PAGE_B) is ErrorCode.PERMISSION_DENIED

    @pytest.mark.parametrize("method", ["entity", "operation", "approval_flow", "rules_pack"])
    def test_broken_reference_is_internal_error(self, snapshot: ConfigSnapshot, method: str) -> None:
        """已发布的配置中取不到被引用的项，说明内部引用断了。"""
        assert _code(getattr(snapshot, method), "CT_NO_SUCH_ITEM") is ErrorCode.INTERNAL_ERROR

    def test_snapshot_does_not_change_after_save(self, harness: ConfigSnapshotReaderHarness) -> None:
        """C04：已经取得的快照在之后的保存中不变；保存后读到的是更新的版本。"""
        save_all(harness)
        before = harness.reader.read(CT_ROLE_A)
        role_before = before.role()
        harness.save([ct_role(CT_ROLE_A, CT_PAGE_A, "契约测试角色甲（改）")])
        after = harness.reader.read(CT_ROLE_A)
        assert before.role() == role_before
        assert after.role().name == "契约测试角色甲（改）"
        assert after.version > before.version

    def test_deleted_role(self, harness: ConfigSnapshotReaderHarness) -> None:
        """角色被删除后，新的读取为 SESSION_ROLE_REVOKED；已经取得的快照照常可用；其他角色不受影响。"""
        save_all(harness)
        before = harness.reader.read(CT_ROLE_A)
        harness.delete("role", CT_ROLE_A)
        assert _code(harness.reader.read, CT_ROLE_A) is ErrorCode.SESSION_ROLE_REVOKED
        assert before.role() == _parsed(ct_role(CT_ROLE_A, CT_PAGE_A, "契约测试角色甲"))
        assert before.entity(CT_ENTITY).table == "T_CT_GOODS"
        assert harness.reader.read(CT_ROLE_B).role_code == CT_ROLE_B

    def test_unavailable(self, harness: ConfigSnapshotReaderHarness) -> None:
        save_all(harness)
        harness.make_unavailable()
        assert _code(harness.reader.read, CT_ROLE_A) is ErrorCode.CONFIG_UNAVAILABLE


class FakeConfigSnapshotReaderHarness:
    """模拟 config 的保存：按 CF-07 给第一次保存的审批流分配递增的 createdSeq，每次保存或删除后为每个角色重建快照；
    角色配置中有的页面给出 C05 样例形状的页面视图。"""

    def __init__(self) -> None:
        self.reader = FakeConfigSnapshotReader()
        self._items: dict[tuple[str, str], ConfigDraft] = {}
        self._seq = 0
        self._version = 0

    def _publish(self) -> None:
        self._version += 1
        # 按编码倒序交给快照：审批流的先后只能来自 createdSeq，不能来自保存的先后
        items = sorted(self._items.values(), key=lambda i: (i.type, i.key), reverse=True)
        roles = {i.key: parse_config_content("role", i.content) for i in items if i.type == "role"}
        for code in [c for c in ("CT_ROLE_A", "CT_ROLE_B") if c not in roles]:
            self.reader.remove(code)
        for code, role in roles.items():
            views = {i.key: parse_wire(PageView, {**doc_json("C05", 0), "pageCode": i.key})
                     for i in items if i.type == "page" and i.key in role.pages}
            self.reader.put(FakeConfigSnapshot.from_items(version=self._version, role_code=code, items=items, page_views=views))

    def save(self, items: list[ConfigDraft]) -> None:
        for item in items:
            old = self._items.get((item.type, item.key))
            if item.type == "approvalFlow":
                if old is None:
                    self._seq += 1
                    seq = self._seq
                else:
                    seq = old.content["createdSeq"]
                item = item.model_copy(update={"content": {**item.content, "createdSeq": seq}})
            self._items[(item.type, item.key)] = item
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


# ---------------------------------------------------------------- 只针对替代实现

def test_fake_snapshot_returns_given_views_menus_and_packs() -> None:
    """替代实现：页面视图、菜单和规则包句柄按给出的内容返回。"""
    from cost_platform.contracts.types import MenuItem

    view = parse_wire(PageView, {**doc_json("C05", 0), "pageCode": CT_PAGE_A})
    handle = object()
    menu = [MenuItem(key=CT_PAGE_A, title="页面 A", kind="page", page_code=CT_PAGE_A)]
    snapshot = FakeConfigSnapshot.from_items(version=1, role_code=CT_ROLE_A, items=ct_base_items(), page_views={CT_PAGE_A: view},
                                             packs={"CT_GOODS": handle})
    assert snapshot.page_view(CT_PAGE_A) is view
    assert snapshot.rules_pack("CT_GOODS") is handle
    assert FakeConfigSnapshot(version=1, role_code=CT_ROLE_A, role=snapshot.role(), menus=menu).menus() == menu


def test_fake_from_items_filters_menus_and_requires_views() -> None:
    """from_items 按角色去掉菜单中不能访问的页面（CF-12）；角色可以访问却没有给出页面视图时，是准备数据的错误。"""
    menu = ConfigDraft(type="menu", key="CT_MENU", name="菜单", content={"items": [
        {"key": "ct", "title": "契约测试", "kind": "group", "children": [
            {"key": CT_PAGE_A, "title": "页面 A", "kind": "page", "pageCode": CT_PAGE_A},
            {"key": CT_PAGE_B, "title": "页面 B", "kind": "page", "pageCode": CT_PAGE_B}]}]})
    snapshot = FakeConfigSnapshot.from_items(version=1, role_code=CT_ROLE_A, items=[*ct_base_items(), menu])
    assert [c.page_code for c in snapshot.menus()[0].children] == [CT_PAGE_A]
    with pytest.raises(ValueError):
        snapshot.page_view(CT_PAGE_A)
    assert _code(snapshot.page_view, CT_PAGE_B) is ErrorCode.PERMISSION_DENIED
