"""queries-export 模拟验证的共用数据：contracts 的 SQLite 替代事务上的成本单、原辅料明细、物料和历史价格，
以及对应的实体、页面视图、执行上下文（其他模块用 contracts 的替代实现）。

数据（说明用）：成本单 1001–1005；原辅料明细中 1001 有物料 115（价格 3.80），1002 有 115（价格 2）和 116（价格 5），
1003 有 115（价格 3.5）和 116（价格 1），1004 有 117（价格 9）。历史价格 115 为 3.50，117 为 0。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from cost_platform.contracts.fakes import FakeConfigSnapshot, FakeUnitOfWorkFactory
from cost_platform.contracts.types import (
    DetailLink,
    EntityConfig,
    EntityField,
    ExecutionContext,
    GridOptions,
    Identity,
    Origin,
    PackRef,
    PageView,
    QueryCompare,
    RoleConfig,
    RolePage,
    ViewDetail,
    ViewField,
    ViewMaster,
)

# 与 sqlite3 已弃用的默认适配器写法相同，只是显式注册，免得每次绑定日期时间都报弃用警告
sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))
sqlite3.register_adapter(date, lambda value: value.isoformat())

PAGE = "COST_PINGGU"
MASTER = "COST_PINGGU"
MATERIAL = "COST_MATERIAL"
GOODS = "COST_GOODS_PRICE"

_TABLES = [
    "CREATE TABLE T_COST_PINGGU (DOCID NUMBER(19) PRIMARY KEY, GOODSID NUMBER(19), GOODSNAME VARCHAR2(200), "
    "TOTAL_COST NUMBER, MEMO VARCHAR2(200), CREATE_BY VARCHAR2(64))",
    "CREATE TABLE T_COST_PINGGU_DTL (DTLID NUMBER(19) PRIMARY KEY, DOCID NUMBER(19), GOODSID NUMBER(19), PRICE NUMBER, "
    "LAST_PRICE NUMBER, MEMO VARCHAR2(200))",
    "CREATE TABLE T_COST_GOODS (GOODSID NUMBER(19) PRIMARY KEY, GOODSNAME VARCHAR2(200), GOODSTYPE VARCHAR2(64), PRICE NUMBER)",
    "CREATE TABLE T_COST_GOODS_HIS (GOODSID NUMBER(19), PRICE NUMBER)",
    "CREATE VIEW V_COST_PINGGU_MATERIAL AS SELECT D.DTLID, D.DOCID, D.GOODSID, G.GOODSNAME, D.PRICE, D.LAST_PRICE, D.MEMO "
    "FROM T_COST_PINGGU_DTL D LEFT JOIN T_COST_GOODS G ON G.GOODSID = D.GOODSID",
]

DOCS = [
    (1001, 900, "胶囊A", "10.5", "甲", "zhang"),
    (1002, 901, "片剂B", "20.25", "乙", "li"),
    (1003, 902, "胶囊C", "10.5", "丙", "zhang"),
    (1004, 903, "Granule d", "5", "丁", "zhang"),
    (1005, 904, "胶囊E", None, "戊", "li"),
]
DETAILS = [
    (5001, 1001, 115, "3.80", "3.50"),
    (5002, 1002, 115, "2", "2"),
    (5003, 1002, 116, "5", "4"),
    (5004, 1003, 115, "3.5", "3.5"),
    (5005, 1003, 116, "1", "1"),
    (5006, 1004, 117, "9", "0"),
]
GOODS_ROWS = [
    (115, "硬脂酸镁", "袋", "3.5"),
    (116, "胶囊壳", "瓶", "1.2"),
    (117, "玉米淀粉", "袋", "9"),
    (118, "空心胶囊", "瓶", "2"),
    (119, "胶体二氧化硅", "桶", "6"),
]
HISTORY = [(115, "3.50"), (117, "0")]


def _num(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def threaded_factory() -> FakeUnitOfWorkFactory:
    """可以在其他线程中使用的 SQLite 替代事务：路由在线程池中访问数据库。"""
    factory = FakeUnitOfWorkFactory()
    factory.engine = create_engine("sqlite://", poolclass=StaticPool,
                                   connect_args={"detect_types": sqlite3.PARSE_DECLTYPES, "check_same_thread": False})
    return factory


def database(factory: FakeUnitOfWorkFactory | None = None) -> FakeUnitOfWorkFactory:
    """建表并写入上面的数据。"""
    factory = factory or FakeUnitOfWorkFactory()
    with factory.engine.begin() as conn:
        for ddl in _TABLES:
            conn.execute(text(ddl))
        for doc, goods, name, total, memo, by in DOCS:
            conn.execute(text("INSERT INTO T_COST_PINGGU VALUES (:a, :b, :c, :d, :e, :f)"),
                         {"a": doc, "b": goods, "c": name, "d": _num(total), "e": memo, "f": by})
        for dtl, doc, goods, price, last in DETAILS:
            conn.execute(text("INSERT INTO T_COST_PINGGU_DTL VALUES (:a, :b, :c, :d, :e, NULL)"),
                         {"a": dtl, "b": doc, "c": goods, "d": _num(price), "e": _num(last)})
        for goods, name, kind, price in GOODS_ROWS:
            conn.execute(text("INSERT INTO T_COST_GOODS VALUES (:a, :b, :c, :d)"), {"a": goods, "b": name, "c": kind, "d": _num(price)})
        for goods, price in HISTORY:
            conn.execute(text("INSERT INTO T_COST_GOODS_HIS VALUES (:a, :b)"), {"a": goods, "b": _num(price)})
    return factory


def field(name: str, label: str, kind: str = "number", column: str | None = "", **extra: Any) -> EntityField:
    return EntityField(name=name, column=name if column == "" else column, label=label, type=kind, source="own", role="input", **extra)


def master_entity() -> EntityConfig:
    return EntityConfig(table="T_COST_PINGGU", primary_key="DOCID", freezable=True, fields=[
        field("DOCID", "单据号"), field("GOODSID", "产品"), field("GOODSNAME", "产品名称", "text"),
        field("TOTAL_COST", "总成本"), field("MEMO", "备注", "text"), field("CREATE_BY", "创建人", "text"),
    ], details=[DetailLink(entity=MATERIAL, parent_key="DOCID")])


PRICE_COMPARE = QueryCompare(mode="query", source="T_COST_GOODS_HIS", keys=[{"current": "GOODSID", "compare": "GOODSID"}],
                             field="PRICE", format="both")


def material_entity(compare: bool = False) -> EntityConfig:
    """原辅料明细经视图 V_COST_PINGGU_MATERIAL 读取（QE-03）；物料名称只在视图中。"""
    return EntityConfig(table="T_COST_PINGGU_DTL", primary_key="DTLID", freezable=True, read_view="V_COST_PINGGU_MATERIAL",
                        fields=[field("DTLID", "明细"), field("DOCID", "单据号"), field("GOODSID", "物料"),
                                field("GOODSNAME", "物料名称", "text", column=None),
                                field("PRICE", "单价", compare=PRICE_COMPARE if compare else None),
                                field("LAST_PRICE", "上次单价"), field("MEMO", "备注", "text")])


def goods_entity() -> EntityConfig:
    return EntityConfig(table="T_COST_GOODS", primary_key="GOODSID", freezable=True,
                        fields=[field("GOODSID", "物料"), field("GOODSNAME", "名称", "text"), field("GOODSTYPE", "类型", "text"),
                                field("PRICE", "价格")])


def entities(compare: bool = False) -> dict[str, EntityConfig]:
    return {MASTER: master_entity(), MATERIAL: material_entity(compare), GOODS: goods_entity()}


_GRID = GridOptions(side_bar=True, cell_selection=True, group_by=[])


def view_fields(entity: EntityConfig, hidden: Iterable[str] = ()) -> list[ViewField]:
    hide = set(hidden)
    return [ViewField(name=f.name, label=f.label, type=f.type, scale=f.scale, source=f.source, calculated=False,
                      visible=f.name not in hide, editable=False, required=False, width=None, pinned=None, dict_type=None,
                      lookup=None) for f in entity.fields]


def page_view(configs: Mapping[str, EntityConfig], hidden: Iterable[str] = ("CREATE_BY",)) -> PageView:
    """成本核算页：主表的创建人对当前角色不可见。"""
    master = configs[MASTER]
    return PageView(
        page_code=PAGE, title="成本核算", version=13, layout="masterDetail", detail_mode="tabs", audit=True,
        save_operation="COST_PINGGU.save", rules_pack=PackRef(pack_id=PAGE, version=1),
        master=ViewMaster(entity=MASTER, primary_key="DOCID", fields=view_fields(master, hidden), buttons=[], grid=_GRID,
                          form_layout=[]),
        details=[ViewDetail(entity=MATERIAL, title="原辅料", primary_key="DTLID", parent_key="DOCID",
                            fields=view_fields(configs[MATERIAL]), buttons=[], grid=_GRID, form_layout=[])],
        system_buttons=["save"])


def snapshot(compare: bool = False, hidden: Iterable[str] = ("CREATE_BY",),
             configs: Mapping[str, EntityConfig] | None = None) -> FakeConfigSnapshot:
    configs = dict(configs) if configs is not None else entities(compare)
    role = RoleConfig(name="成本会计", admin=False, pages={PAGE: RolePage(buttons=["*"])})
    return FakeConfigSnapshot(version=13, role_code="COST_ACCOUNTANT", role=role, page_views={PAGE: page_view(configs, hidden)},
                              pages=[PAGE, "OTHER_PAGE"], entities=configs)


def context(config: Any = None, user_id: str = "112") -> ExecutionContext:
    snap = config if config is not None else snapshot()
    who = Identity(user_id=user_id, username=f"user{user_id}", display_name=f"用户{user_id}", department_id="10",
                   role_code=snap.role_code, session_id=f"s-{user_id}")
    return ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=who, config=snap,
                            config_version=snap.version, origin=Origin(kind="user", approval_id=None), now=datetime(2026, 10, 29, 10, 0))


def keys(rows: Sequence[Any]) -> list[str]:
    return [r.row_key for r in rows]
