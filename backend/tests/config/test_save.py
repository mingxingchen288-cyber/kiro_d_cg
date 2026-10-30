"""保存、删除、读取配置项（CF-01、CF-02、CF-04、CF-07～CF-10，T-CF-1、T-CF-3 的模拟验证）。"""

from __future__ import annotations

import pytest

from cost_platform.config.records import item_id
from cost_platform.contracts.types import ErrorCode, PlatformError

from .support import Env, base_world, draft, flow_samples, seed_drafts


@pytest.fixture
def env() -> Env:
    return Env()


def test_seed_and_c06_flow_samples_can_be_saved(env: Env) -> None:
    """T-CF-1：C06 7.8、7.9、7.10 三个样例能保存（所属页面、实体在同一套配置中）。"""
    first = env.save(base_world())
    result = env.save(flow_samples())
    assert result.generation == first.generation + 1 == env.generation()
    in_seed = {d.key for d in seed_drafts() if d.type == "approvalFlow"}  # seed 已有 7.9、7.10 两个（部门、液体两块按 d_cg 改过）
    assert in_seed == {"TECH_CUSTOMER_MATERIAL", "GOODS_TO_COST"}
    for item in flow_samples():
        assert env.stored("approvalFlow", item.key) == item.content
        assert result.versions[("approvalFlow", item.key)] == (2 if item.key in in_seed else 1)


def test_save_writes_new_version_views_and_packs_in_one_generation(env: Env) -> None:
    """CF-02：一个事务写入新内容、版本号加一，重新生成受影响的页面视图（每个页面、每个角色一份）和规则包（每个业务对象一份）。"""
    env.save(seed_drafts())
    records = env.records()
    assert {r.id for r in records.values() if r.type in ("pageView", "rulesPack")} == {
        "pageView/COST_PINGGU|ADMIN", "pageView/COST_PINGGU|技术中心", "pageView/GOODS_PRICE_MANAGE|ADMIN",
        "pageView/GOODS_PRICE_MANAGE|技术中心", "rulesPack/COST_PINGGU", "rulesPack/COST_GOODS_PRICE"}
    page = next(d for d in seed_drafts() if d.type == "page")
    changed = page.content | {"title": "成本核算（改）"}
    result = env.save([draft("page", "COST_PINGGU", changed, "成本核算")])
    after = env.records()
    assert after[item_id("page", "COST_PINGGU")].version == 2
    assert after[item_id("page", "COST_PINGGU")].generation == result.generation
    view = after[item_id("pageView", "COST_PINGGU|ADMIN")]
    assert view.content()["title"] == "成本核算（改）" and view.content()["version"] == result.generation
    # 规则包内容没变：不重写，版本不变
    assert after[item_id("rulesPack", "COST_PINGGU")] == records[item_id("rulesPack", "COST_PINGGU")]
    assert sorted(result.changed) == ["page/COST_PINGGU", "pageView/COST_PINGGU|ADMIN", "pageView/COST_PINGGU|技术中心"]


def test_failed_validation_writes_nothing(env: Env) -> None:
    """CF-01：校验不通过返回 422 VALIDATION_FAILED，什么都不写，代号不变。"""
    env.save(seed_drafts())
    before, generation = env.records(), env.generation()
    page = next(d for d in seed_drafts() if d.type == "page")
    broken = page.content | {"saveOperation": "NO_SUCH.save"}
    with pytest.raises(PlatformError) as caught:
        env.save([draft("page", "COST_PINGGU", broken, "成本核算")])
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    detail = caught.value.details[0]
    assert (detail.config_type, detail.config_key, detail.path) == ("page", "COST_PINGGU", "saveOperation")
    assert env.records() == before and env.generation() == generation
    assert env.cache.pending == {}


def test_last_save_wins(env: Env) -> None:
    """CF-08：两个管理员先后保存同一配置项，后保存的覆盖先保存的。"""
    env.save(seed_drafts())
    role = next(d for d in seed_drafts() if d.type == "role")
    env.save([draft("role", "ADMIN", role.content | {"name": "管理员甲"})], user="11")
    env.save([draft("role", "ADMIN", role.content | {"name": "管理员乙"})], user="12")
    record = env.records()[item_id("role", "ADMIN")]
    assert record.content()["name"] == "管理员乙" and record.updated_by == "12" and record.version == 3


def test_referenced_item_cannot_be_deleted(env: Env) -> None:
    """CF-09：仍被其他配置引用的配置项不能删除；不被引用的可以删除，删除后生成的视图跟着删除。"""
    env.save([*seed_drafts(), draft("role", "VIEWER", {"name": "只读", "admin": False, "pages": {"COST_PINGGU": {}}})])
    with pytest.raises(PlatformError) as caught:
        env.service.delete("entity", "COST_MATERIAL", "1")
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert "仍被" in (caught.value.details[0].message or "")
    assert item_id("entity", "COST_MATERIAL") in env.records()
    env.service.delete("role", "VIEWER", "1")
    records = env.records()
    assert item_id("role", "VIEWER") not in records and item_id("pageView", "COST_PINGGU|VIEWER") not in records


def test_flow_order_is_taken_from_config(env: Env) -> None:
    """CF-07：审批流的先后由配置中的 order 决定，config 不另外分配。"""
    env.save(base_world())
    env.save(flow_samples())
    snapshot = env.reader.read("ADMIN")
    assert [f.order for f in snapshot.approval_flows("COST_PINGGU")] == [1, 2]


def test_ensure_admin_role(env: Env) -> None:
    """CF-10：没有 ADMIN 角色配置时启动创建它（admin 为 true），已存在时不改。"""
    items = [d for d in seed_drafts() if d.type != "role"]
    menu = next(d for d in items if d.type == "menu")
    env.save([d for d in items if d.type != "menu"])
    assert env.service.ensure_admin_role() is True
    admin = env.stored("role", "ADMIN")
    assert admin == {"name": "系统管理员", "admin": True,
                     "pages": {"COST_PINGGU": {"buttons": ["*"]}, "GOODS_PRICE_MANAGE": {"buttons": ["*"]}}}
    env.save([menu])
    generation = env.generation()
    assert env.service.ensure_admin_role() is False
    assert env.generation() == generation and env.stored("role", "ADMIN") == admin


def test_list_and_get_items(env: Env) -> None:
    env.save(seed_drafts())
    pages = env.service.list_items("page")
    assert [(i.type, i.key, i.version, i.updated_by) for i in pages] == [("page", "COST_PINGGU", 1, "1"),
                                                                         ("page", "GOODS_PRICE_MANAGE", 1, "1")]
    assert {i.type for i in env.service.list_items()} == {"approvalFlow", "dict", "entity", "export", "lookup", "menu", "operation",
                                                           "page", "role", "rule"}
    item = env.service.get_item("entity", "COST_PINGGU")
    assert item.content == next(d for d in seed_drafts() if d.key == "COST_PINGGU" and d.type == "entity").content
    with pytest.raises(PlatformError) as caught:
        env.service.get_item("pageView", "COST_PINGGU|ADMIN")
    assert caught.value.code is ErrorCode.NOT_FOUND
