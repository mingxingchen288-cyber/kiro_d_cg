"""T-QE-2：个人列配置（QE-07）。表由本模块的迁移脚本在 SQLite 替代事务上建立（d_cg 上的建表由合并后统一升级）。"""

from __future__ import annotations

from datetime import datetime

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

import cost_platform.queries.migrations.qe_0001_pf_personal_config as migration
from cost_platform.contracts.fakes import FakeUnitOfWorkFactory
from cost_platform.contracts.types import ErrorCode, PersonalConfig, PlatformError, dump_wire, parse_wire
from cost_platform.queries.personal import PersonalConfigs, PersonalConfigStore

from .support import PAGE, context

NOW = datetime(2026, 10, 29, 10, 0)
MASTER_GRID = {"columns": [{"field": "DOCID", "width": 120, "pinned": "left", "hide": False},
                           {"field": "GOODSNAME", "width": 200, "pinned": None, "hide": False},
                           {"field": "MEMO", "width": None, "pinned": None, "hide": True}]}
MATERIAL_GRID = {"columns": [{"field": "PRICE", "width": 90, "pinned": None, "hide": False}]}


def migrated() -> FakeUnitOfWorkFactory:
    factory = FakeUnitOfWorkFactory()
    with factory.engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    return factory


def config(body: dict[str, object]) -> PersonalConfig:
    return parse_wire(PersonalConfig, body)


@pytest.fixture
def store() -> PersonalConfigStore:
    return PersonalConfigStore(migrated())


def test_nothing_saved_yet(store: PersonalConfigStore) -> None:
    """没有保存过时各项为空：响应为 {}。"""
    assert dump_wire(PersonalConfig, store.get("112", PAGE)) == {}


def test_save_replaces_only_the_given_parts(store: PersonalConfigStore) -> None:
    """QE-07：保存时只替换请求中给出的部分。"""
    saved = store.save("112", PAGE, config({"grids": {"master": MASTER_GRID}, "detailMode": "tabs"}), NOW)
    assert dump_wire(PersonalConfig, saved) == {"grids": {"master": MASTER_GRID}, "detailMode": "tabs"}

    store.save("112", PAGE, config({"grids": {"COST_MATERIAL": MATERIAL_GRID}}), NOW)
    assert dump_wire(PersonalConfig, store.get("112", PAGE)) == {
        "grids": {"COST_MATERIAL": MATERIAL_GRID, "master": MASTER_GRID}, "detailMode": "tabs"}

    store.save("112", PAGE, config({"detailMode": "stack"}), NOW)
    narrower = {"columns": MASTER_GRID["columns"][:1]}
    after = store.save("112", PAGE, config({"grids": {"master": narrower}}), NOW)
    assert dump_wire(PersonalConfig, after) == {"grids": {"COST_MATERIAL": MATERIAL_GRID, "master": narrower}, "detailMode": "stack"}


def test_columns_keep_their_order(store: PersonalConfigStore) -> None:
    """C09：`columns` 按数组顺序排列（列的顺序就是用户拖动后的顺序）。"""
    reordered = {"columns": list(reversed(MASTER_GRID["columns"]))}
    store.save("112", PAGE, config({"grids": {"master": reordered}}), NOW)
    grids = store.get("112", PAGE).grids
    assert grids is not None and [c.field for c in grids["master"].columns] == ["MEMO", "GOODSNAME", "DOCID"]


def test_each_user_and_page_is_separate(store: PersonalConfigStore) -> None:
    store.save("112", PAGE, config({"grids": {"master": MASTER_GRID}}), NOW)
    assert dump_wire(PersonalConfig, store.get("113", PAGE)) == {}
    assert dump_wire(PersonalConfig, store.get("112", "OTHER_PAGE")) == {}


def test_personal_config_of_the_current_user(store: PersonalConfigStore) -> None:
    """接口按执行上下文中的用户读写；角色不能访问的页面为 403。"""
    personal = PersonalConfigs(store)
    personal.save(context(user_id="120"), PAGE, config({"detailMode": "stack"}))
    assert store.get("120", PAGE).detail_mode == "stack"
    assert personal.get(context(user_id="120"), PAGE).detail_mode == "stack"
    with pytest.raises(PlatformError) as caught:
        personal.get(context(user_id="120"), "OTHER_PAGE")
    assert caught.value.code is ErrorCode.PERMISSION_DENIED
