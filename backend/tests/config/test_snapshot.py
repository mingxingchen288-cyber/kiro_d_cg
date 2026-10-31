"""配置快照读取（CF-06、CF-12，C08 第 4 节，T-CF-4 的模拟验证）。"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

import pytest

from cost_platform.contracts.types import ErrorCode, PlatformError
from tests.contracts.test_config_snapshot_reader import ConfigSnapshotReaderContract

from .support import Env, draft, seed_drafts


class ConfigReaderHarness:
    """契约测试的 harness：真实的保存流程（SQLite 上的 PF_ 表）、内存 Redis、`ConfigReader`。"""

    def __init__(self) -> None:
        self.env = Env()
        self.reader = self.env.reader

    def save(self, items: list) -> None:
        self.env.save(items)

    def delete(self, config_type: str, key: str) -> None:
        self.env.service.delete(config_type, key, "1")

    def make_unavailable(self) -> None:
        self.env.cache.unavailable = True
        self.env.uow.fail("begin", PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "数据库暂时不可用"), times=None)


class TestConfigReader(ConfigSnapshotReaderContract):
    @pytest.fixture
    def harness(self) -> ConfigReaderHarness:
        return ConfigReaderHarness()


def _saved() -> Env:
    env = Env()
    env.save(seed_drafts())
    return env


def test_read_is_one_redis_call_without_oracle() -> None:
    """没有待生效登记时，一次读取只访问 Redis 一次，不访问 Oracle（CF-06）。"""
    env = _saved()
    env.reader.read("ADMIN")
    env.cache.calls.clear()
    begins = len(env.uow.calls_to("begin"))
    for _ in range(3):
        snapshot = env.reader.read("ADMIN")
    assert env.cache.calls == ["read", "read", "read"]
    assert len(env.uow.calls_to("begin")) == begins and env.reader.oracle_reads == 0
    assert snapshot.version == env.generation()


def test_new_process_reads_everything_in_one_call() -> None:
    """新进程第一次读取：同一次 Redis 读取带出角色用到的全部配置项内容，不访问 Oracle。"""
    env = _saved()
    reader = env.new_reader()
    env.cache.calls.clear()
    snapshot = reader.read("ADMIN")
    assert env.cache.calls == ["read"] and reader.oracle_reads == 0
    assert snapshot.page_view("COST_PINGGU").page_code == "COST_PINGGU"


def test_pending_registration_of_other_role_does_not_touch_oracle() -> None:
    """待生效登记与本次要用的配置项没有交集时，不查 Oracle。"""
    env = _saved()
    env.reader.read("ADMIN")
    from cost_platform.config.cache import PendingEntry

    env.cache.register_pending(PendingEntry(env.generation() + 1, ("role/OTHER", "pageView/COST_PINGGU|OTHER"),
                                            env.clock.now()))
    env.reader.read("ADMIN")
    assert env.reader.oracle_reads == 0


def test_redis_flushed_falls_back_to_oracle_and_rewrites() -> None:
    """Redis 被清空（缺项）时回查 Oracle，并把全部配置补写回 Redis。"""
    env = _saved()
    generation = env.generation()
    env.cache.generation, env.cache.index, env.cache.items = 0, {}, {}
    snapshot = env.new_reader().read("ADMIN")
    assert snapshot.version == generation
    assert env.cache.generation == generation and "pageView/COST_PINGGU|ADMIN" in env.cache.index


def test_redis_unavailable_reads_oracle() -> None:
    """Redis 不可用时，读取配置快照直接查 Oracle（CF-05）。"""
    env = _saved()
    env.cache.unavailable = True
    snapshot = env.new_reader().read("ADMIN")
    assert snapshot.version == env.generation() and snapshot.role().admin is True


def test_menus_only_accessible_pages() -> None:
    """CF-12：menus() 只含该角色可以访问的页面；没有可访问页面的分组去掉。"""
    env = Env()
    menu = draft("menu", "main", {"items": [
        {"key": "cost", "title": "成本", "kind": "group", "children": [
            {"key": "COST_PINGGU", "title": "成本核算", "kind": "page", "pageCode": "COST_PINGGU"}]},
        {"key": "goods", "title": "物料", "kind": "group", "children": [
            {"key": "GOODS_PRICE_MANAGE", "title": "物料清单", "kind": "page", "pageCode": "GOODS_PRICE_MANAGE"}]},
        {"key": "config", "title": "配置", "kind": "config"}]})
    from .support import goods_price_items

    viewer = draft("role", "VIEWER", {"name": "只看成本", "admin": False, "pages": {"COST_PINGGU": {}}})
    env.save([*[d for d in seed_drafts() if d.type != "menu"], *goods_price_items(), menu, viewer])
    menus = env.reader.read("VIEWER").menus()
    assert [(m.key, [c.key for c in m.children]) for m in menus] == [("cost", ["COST_PINGGU"])]
    admin = env.reader.read("ADMIN").menus()
    assert [m.key for m in admin] == ["cost", "goods", "config"]  # seed 的 ADMIN 能访问物料清单页


@settings(max_examples=25, deadline=None)
@given(steps=st.lists(st.sampled_from(["role", "page", "read", "read2"]), min_size=1, max_size=12))
def test_interleaved_saves_and_reads_never_mix_versions(steps: list[str]) -> None:
    """基于属性的测试：保存和读取交替进行时，每次读到的快照都属于同一版本组合（角色名称、页面标题、页面视图都是快照代号
    那一刻的值），同一快照的内容之后不变。两个进程交替读取。"""
    env = _saved()
    other = env.new_reader()
    role = next(d for d in seed_drafts() if (d.type, d.key) == ("role", "ADMIN")).content
    page = next(d for d in seed_drafts() if d.type == "page" and d.key == "COST_PINGGU").content
    names = {env.generation(): (role["name"], page["title"])}
    current = dict(zip(("role", "title"), names[env.generation()], strict=True))
    taken = []
    for i, step in enumerate(steps):
        if step == "role":
            current["role"] = f"角色{i}"
            env.save([draft("role", "ADMIN", {**role, "name": current["role"]})])
        elif step == "page":
            current["title"] = f"页面{i}"
            env.save([draft("page", "COST_PINGGU", {**page, "title": current["title"]})])
        else:
            snapshot = (env.reader if step == "read" else other).read("ADMIN")
            taken.append(snapshot)
        names[env.generation()] = (current["role"], current["title"])
    for snapshot in taken:
        expected_role, expected_title = names[snapshot.version]
        assert snapshot.role().name == expected_role
        assert snapshot.page_view("COST_PINGGU").title == expected_title
        assert snapshot.page_view("COST_PINGGU").version <= snapshot.version


# ---------------------------------------------------------------- 2026-10-29 补的快照方法和 current_version

def test_lookup_dict_exports_and_flow_entries() -> None:
    """快照的 Lookup、字典、导出配置，以及带编码和名称的审批流（C08 第 4 节，使用方 queries-export、approval）。"""
    from cost_platform.contracts.types import parse_config_content

    from .support import base_world, doc_json, flow_samples

    env = Env()
    env.save(base_world())
    lookup = draft("lookup", "GOODS", {"table": "T_COST_GOODS", "columns": ["GOODSID", "GOODSNAME"],
                                       "keywordColumns": ["GOODSID", "GOODSNAME"], "orderBy": "GOODSID"})
    status = draft("dict", "USESTATUS", {"items": [{"value": "评估中", "label": "评估中", "order": 1}]})
    export = draft("export", "cost-pinggu-export", doc_json("C06", 13), "成本核算导出")
    env.save([lookup, status, export, *flow_samples()])
    snapshot = env.reader.read("ADMIN")
    assert snapshot.lookup("GOODS") == parse_config_content("lookup", lookup.content)
    assert snapshot.lookup("NO_SUCH_LOOKUP") is None
    assert snapshot.dict_config("USESTATUS") == parse_config_content("dict", status.content)
    page = export.content["page"]
    assert snapshot.exports(page) == {"cost-pinggu-export": parse_config_content("export", export.content)}
    for flow_page in {f.content["page"] for f in flow_samples()}:
        drafts = sorted((f for f in flow_samples() if f.content["page"] == flow_page and f.content.get("enabled", True)),
                        key=lambda f: (f.content["order"], f.key))
        entries = snapshot.approval_flow_entries(flow_page)
        assert [(e.code, e.name) for e in entries] == [(f.key, f.name) for f in drafts]
        assert [e.flow for e in entries] == snapshot.approval_flows(flow_page)


def test_current_version() -> None:
    """当前配置代号：从 Redis 读；Redis 不可用时读 Oracle 的代号行（X-Config-Version、还没选角色时的 `/api/me`）。"""
    env = _saved()
    assert env.reader.current_version() == env.generation()
    env.cache.unavailable = True
    assert env.reader.current_version() == env.generation()
