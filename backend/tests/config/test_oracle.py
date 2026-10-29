"""真实验证（d_cg）：PF_CONFIG_ITEM、PF_CONFIG_GENERATION 的保存、读取、删除，SQL 片段交给 Oracle 解析，向导，并发保存。

这次不运行（共用规则：合并后统一升级、统一运行）。前提见 real_support.py；C06 7.8、7.10 样例和向导还需要 d_cg 中有
T_COST_GOODS_PRICE_V、T_COST_PINGGU_DTL_LQ、V_COST_PINGGU_MATERIAL_LQ、V_COST_PINGGU_PACKAGE_LQ、T_COST_PINGGU_LQ
（2026-10-29 只读查询时 d_cg 还没有，cmx 有；由 db-core 复制）。
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from sqlalchemy import Engine, text

from cost_platform.config.cache import MemoryConfigCache
from cost_platform.config.entities import PublishedEntities
from cost_platform.config.store import ConfigStore
from cost_platform.contracts.types import ErrorCode, PlatformError, WizardColumnsRequest, WizardGenerateRequest, parse_wire
from tests.contracts.test_config_snapshot_reader import ConfigSnapshotReaderContract
from tests.contracts.test_entity_directory import EntityDirectoryContract

from .real_support import OracleEnv, engine  # noqa: F401 - fixture
from .support import draft, flow_samples, goods_price_items, liquid_items, seed_drafts
from .test_entities import entity_drafts

pytestmark = pytest.mark.oracle

GRID = {"sideBar": True, "cellSelection": True, "groupBy": []}


def _items(prefix: str = "CT_ORA") -> list[Any]:
    fields = [{"name": n, "column": n, "label": n, "type": t, "source": "own", "role": r}
              for n, t, r in (("GOODSID", "number", "system"), ("GOODSNAME", "text", "input"), ("ZX_PRICE", "number", "input"))]
    return [
        draft("entity", f"{prefix}_GOODS", {"table": "T_COST_GOODS", "primaryKey": "GOODSID", "freezable": True, "fields": fields}),
        draft("operation", f"{prefix}_PAGE.save", {"label": "保存", "kind": "save", "writableFields": {f"{prefix}_GOODS": ["ZX_PRICE"]},
                                                  "impact": [f"{prefix}_GOODS"], "propagation": "continue"}),
        draft("page", f"{prefix}_PAGE", {"title": "物料", "layout": "single", "detailMode": "tabs", "audit": False,
                                         "saveOperation": f"{prefix}_PAGE.save", "master": {"entity": f"{prefix}_GOODS", "grid": GRID}}),
        draft("role", f"{prefix}_ROLE", {"name": "测试角色", "admin": False, "pages": {f"{prefix}_PAGE": {"buttons": ["*"]}}}),
    ]


@pytest.fixture
def ora(engine: Engine) -> Any:  # noqa: F811
    env = OracleEnv(engine, MemoryConfigCache())
    env.cleanup()
    yield env
    env.cleanup()


def test_save_read_delete_on_d_cg(ora: OracleEnv) -> None:
    """T-CF-1 真实验证：在 d_cg 上保存、读取、删除配置项；保存时代号只加一，生成的页面视图和规则包一起写入。"""
    generation = ora.generation()
    result = ora.service.save(_items(), "1")
    assert result.generation == generation + 1 == ora.generation()
    with ora.uow.begin() as uow:
        _, records = ConfigStore().read_all(uow)
    assert records["entity/CT_ORA_GOODS"].version == 1
    assert {"pageView/CT_ORA_PAGE|CT_ORA_ROLE", "rulesPack/CT_ORA_GOODS"} <= set(records)
    snapshot = ora.new_reader().read("CT_ORA_ROLE")
    assert snapshot.page_view("CT_ORA_PAGE").title == "物料" and snapshot.entity("CT_ORA_GOODS").table == "T_COST_GOODS"
    assert ora.service.get_item("page", "CT_ORA_PAGE").content["title"] == "物料"
    with pytest.raises(PlatformError) as caught:
        ora.service.delete("entity", "CT_ORA_GOODS", "1")
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    ora.cleanup()
    assert ora.stored_keys("CT_ORA") == []


def test_seed_config_validates_against_d_cg(ora: OracleEnv) -> None:
    """seed 的成本核算配置在 d_cg 的真实表结构上通过 C06 第 10 节的校验。"""
    assert ora.service.validate(seed_drafts()) == []


def test_flow_fragments_are_parsed_by_oracle(ora: OracleEnv) -> None:
    """C06 7.2 包好的 SQL 片段交给 Oracle 解析：表、列不存在时拒绝，原因是中文、不带 ORA- 文本。"""
    def flow(condition: str) -> Any:
        return draft("approvalFlow", "CT_ORA_FLOW", {
            "page": "COST_PINGGU", "order": 1, "operations": {"COST_MATERIAL": ["modify"]},
            "levels": [{"level": 1, "nodes": [{"name": "管理员审批", "conditionType": "sql", "condition": condition,
                                               "approvers": [{"type": "role", "role": "ADMIN"}], "mode": "or"}]}]})
    good = "DECODE(:new_PRICE, (SELECT NVL(ZX_PRICE, PRICE) FROM T_COST_GOODS WHERE GOODSID = :new_GOODSID), 0, 1) = 1"
    assert ora.service.validate([*seed_drafts(), flow(good)]) == []
    errors = ora.service.validate([*seed_drafts(), flow(good.replace("ZX_PRICE", "NO_SUCH_COLUMN"))])
    assert [e.path for e in errors] == ["levels[0].nodes[0].condition"]
    assert "NO_SUCH_COLUMN" in (errors[0].message or "") and "ORA-" not in (errors[0].message or "")


def test_c06_flow_samples_save_on_d_cg(ora: OracleEnv) -> None:
    """T-CF-1：C06 7.8、7.9、7.10 三个样例在 d_cg 上校验通过（SQL 片段按 7.2 包好后交给数据库解析通过）。只校验，不写入。"""
    world = [*seed_drafts(), *goods_price_items(), *liquid_items(), *flow_samples()]
    assert ora.service.validate(world) == []


def test_wizard_on_d_cg(ora: OracleEnv) -> None:
    """T-CF-6 真实验证：用 T_COST_GOODS_PRICE_V 和 T_COST_GOODS 生成物料清单页，字段与视图列一致，视图独有的列只读；
    配置代号只加一；序列不存在的表返回 422 且什么都不写。"""
    created_admin = ora.service.ensure_admin_role()
    menu = draft("menu", "CT_ORA_MENU", {"items": [{"key": "ct_ora", "title": "测试", "kind": "group"}]})
    ora.service.save([menu], "1")
    admin_before = ora.service.get_item("role", "ADMIN").content
    columns = ora.service.wizard_columns(WizardColumnsRequest(read_view="T_COST_GOODS_PRICE_V", table="T_COST_GOODS"))
    generation = ora.generation()
    request = parse_wire(WizardGenerateRequest, {
        "parentMenu": "ct_ora", "pageCode": "CT_ORA_GOODS_PRICE", "title": "物料清单及成本", "layout": "single",
        "detailMode": "tabs", "audit": True, "details": [],
        "master": {"entity": "CT_ORA_GOODS_PRICE", "table": "T_COST_GOODS", "readView": "T_COST_GOODS_PRICE_V",
                   "erpRow": {"column": "ISERP", "value": "1", "localValue": "0"}}})
    try:
        result = ora.service.wizard_generate(request, "1")
        assert result.generation == generation + 1 == ora.generation()
        entity = ora.service.get_item("entity", "CT_ORA_GOODS_PRICE").content
        assert [f["name"] for f in entity["fields"]] == [c.name for c in columns.columns]
        assert {f["name"] for f in entity["fields"] if f["column"] is None} == {c.name for c in columns.columns if not c.in_table}
        bad = parse_wire(WizardGenerateRequest, {**request.model_dump(mode="json", by_alias=True), "pageCode": "CT_ORA_BAD",
                                                 "master": {"entity": "CT_ORA_BAD", "table": "PF_ALEMBIC_VERSION"}})
        generation = ora.generation()
        with pytest.raises(PlatformError) as caught:
            ora.service.wizard_generate(bad, "1")
        assert caught.value.code is ErrorCode.VALIDATION_FAILED and ora.generation() == generation
        assert "序列 PF_ALEMBIC_VERSION_SEQ 不存在" in " ".join(d.message or "" for d in caught.value.details)
    finally:
        if created_admin:  # 测试前没有 ADMIN 角色：删掉，不在 PF_CONFIG_ITEM 中留下正式配置项
            ora.service.delete("role", "ADMIN", "1")
        else:
            admin = ora.service.get_item("role", "ADMIN")
            ora.service.save([draft("role", "ADMIN", admin_before, admin.name)], "1")


def test_concurrent_saves_queue_on_generation_row(ora: OracleEnv) -> None:
    """两次保存并发时在代号行上排队，依次执行，代号各加一（CF-04 第 2 步）。"""
    ora.service.save(_items(), "1")
    generation = ora.generation()
    role = _items()[3]
    results: list[int] = []
    errors: list[BaseException] = []

    def save(name: str) -> None:
        try:
            results.append(ora.service.save([draft("role", "CT_ORA_ROLE", {**role.content, "name": name})], "1").generation)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=save, args=(f"并发{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and sorted(results) == [generation + 1, generation + 2] and ora.generation() == generation + 2


# ---------------------------------------------------------------- ConfigSnapshotReader 的契约测试（d_cg + 内存 Redis）

class OracleReaderHarness:
    """契约测试用的表 T_CT_GOODS 和序列 T_CT_GOODS_SEQ 不存在时在 d_cg 中建立（工程约定第 1 节允许在 d_cg 建表）。"""

    def __init__(self, engine: Engine) -> None:  # noqa: F811
        with engine.begin() as c:
            if c.execute(text("SELECT COUNT(*) FROM user_tables WHERE table_name = 'T_CT_GOODS'")).scalar_one() == 0:
                c.execute(text("CREATE TABLE T_CT_GOODS (GOODSID NUMBER(10) PRIMARY KEY, NAME VARCHAR2(100), PRICE NUMBER(18,2))"))
            if c.execute(text("SELECT COUNT(*) FROM user_sequences WHERE sequence_name = 'T_CT_GOODS_SEQ'")).scalar_one() == 0:
                c.execute(text("CREATE SEQUENCE T_CT_GOODS_SEQ"))
        self.env = OracleEnv(engine, MemoryConfigCache())
        self.env.cleanup()
        self.reader = self.env.reader

    def save(self, items: list[Any]) -> None:
        self.env.service.save(items, "1")

    def delete(self, config_type: str, key: str) -> None:
        self.env.service.delete(config_type, key, "1")

    def make_unavailable(self) -> None:
        """Redis 和 Oracle 都不可用：读取方拿到的事务工厂开不了事务（不能真的停掉 d_cg）。"""
        self.env.cache.unavailable = True
        self.reader._uow = _Unavailable()  # type: ignore[attr-defined]


class _Unavailable:
    def begin(self) -> Any:
        raise PlatformError(ErrorCode.DATABASE_UNAVAILABLE, "数据库暂时不可用")


class TestOracleConfigReader(ConfigSnapshotReaderContract):
    @pytest.fixture
    def harness(self, engine: Engine) -> Any:  # noqa: F811
        harness = OracleReaderHarness(engine)
        yield harness
        harness.env.cache.unavailable = False  # test_unavailable 把 Redis 设成了不可用；清理时恢复
        harness.env.cleanup()


# ---------------------------------------------------------------- EntityDirectory 的契约测试（d_cg + 内存 Redis）

class TestOraclePublishedEntities(EntityDirectoryContract):
    """在 d_cg 上发布契约测试的四个实体（编码由契约测试定，不是 CT_ 开头）。d_cg 中已有的同编码实体（例如启动时导入的 seed）
    不改也不删；只保存缺少的，测试结束时删掉这些，不在 PF_CONFIG_ITEM 中留下正式配置项。"""

    @pytest.fixture
    def directory(self, engine: Engine) -> Any:  # noqa: F811
        env = OracleEnv(engine, MemoryConfigCache())
        with env.uow.begin() as uow:
            _, records = ConfigStore().read_all(uow, ["entity"])
        created = [d for d in entity_drafts() if f"entity/{d.key}" not in records]
        if created:
            env.service.save(created, "1")
        try:
            yield PublishedEntities(env.uow, env.reader)
        finally:
            for item in sorted(created, key=lambda d: not d.content.get("details")):  # 主表先删，明细后删
                env.service.delete("entity", item.key, "1")
