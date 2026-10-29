"""write-pipeline 真实验证（d_cg）共用的表、配置和数据。

测试自己建表、建序列和视图（T_WP_DOC、T_WP_DTL、V_WP_MATERIAL、V_WP_PACKAGE、T_WP_GOODS），结束时删除，不碰业务表；
命令记录写在 PF_COMMAND（迁移 wp_0001，前提：已执行 `platform db upgrade`），用户编号为 990001、990002，结束时删除
这两个用户的命令记录。表的形状仿成本核算：主表、两个明细实体同在一张明细表（经两个视图读取）、物料表带 ISERP。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeConfigSnapshot, FakePermissionChecker, FakeRulesEngine, FakeSchemaInspector

from . import support
from .support import fld, view_fields

DOC, MATERIAL, PACKAGE, GOODS = "WP_DOC", "WP_MATERIAL", "WP_PACKAGE", "WP_GOODS"


def master_none(record_key: str, details: list[dict[str, Any]], entity: str = DOC) -> dict[str, Any]:
    """同 support.master_none，主表实体默认为测试表的 WP_DOC。"""
    return support.master_none(record_key, details, entity)


def master_modify(record_key: str, changes: dict[str, Any], entity: str = DOC,
                  details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """同 support.master_modify，主表实体默认为测试表的 WP_DOC。"""
    return support.master_modify(record_key, changes, entity, details)
PAGE, SAVE = "WP_PAGE", "WP_PAGE.save"
GOODS_PAGE, GOODS_SAVE = "WP_GOODS_PAGE", "WP_GOODS_PAGE.save"
USERS = ("990001", "990002")
NOW = datetime(2026, 10, 29, 10, 0, 0)

DDL = [
    "CREATE TABLE T_WP_DOC (DOCID NUMBER(12) PRIMARY KEY, MEMO VARCHAR2(200), APEX_PL NUMBER, TOTAL_COST NUMBER, "
    "CREATE_BY VARCHAR2(64), USESTATUS VARCHAR2(20), OWNER VARCHAR2(64))",
    "CREATE SEQUENCE T_WP_DOC_SEQ START WITH 900001",
    "CREATE TABLE T_WP_DTL (DTLID NUMBER(12) PRIMARY KEY, DOCID NUMBER(12) NOT NULL, KIND VARCHAR2(10) NOT NULL, "
    "GOODSID NUMBER(12), USAGE NUMBER, PRICE NUMBER(18,2), COST_BATCH NUMBER, MEMO VARCHAR2(200))",
    "CREATE SEQUENCE T_WP_DTL_SEQ START WITH 900001",
    "CREATE VIEW V_WP_MATERIAL AS SELECT DTLID, DOCID, KIND, GOODSID, USAGE, PRICE, COST_BATCH, MEMO FROM T_WP_DTL WHERE KIND = 'M'",
    "CREATE VIEW V_WP_PACKAGE AS SELECT DTLID, DOCID, KIND, GOODSID, USAGE, PRICE, COST_BATCH, MEMO FROM T_WP_DTL WHERE KIND = 'P'",
    "CREATE TABLE T_WP_GOODS (GOODSID NUMBER(12) PRIMARY KEY, NAME VARCHAR2(100), ISERP NUMBER(1), PRICE NUMBER, "
    "ZX_PRICE NUMBER(18,4))",
    "CREATE SEQUENCE T_WP_GOODS_SEQ START WITH 900001",
]
DROP = ["DROP VIEW V_WP_MATERIAL", "DROP VIEW V_WP_PACKAGE", "DROP TABLE T_WP_DTL PURGE", "DROP TABLE T_WP_DOC PURGE",
        "DROP TABLE T_WP_GOODS PURGE", "DROP SEQUENCE T_WP_DOC_SEQ", "DROP SEQUENCE T_WP_DTL_SEQ", "DROP SEQUENCE T_WP_GOODS_SEQ"]
ROWS = [
    "INSERT INTO T_WP_DOC VALUES (1001, NULL, 100000, 54, '王五', '草稿', 'user990001')",
    "INSERT INTO T_WP_DOC VALUES (1002, '旧备注', 50000, 12, '王五', '草稿', 'other')",
    "INSERT INTO T_WP_DTL VALUES (5001, 1001, 'M', 115, 2, 3.50, 7, NULL)",
    "INSERT INTO T_WP_DTL VALUES (5002, 1001, 'M', 116, 1, 47, 47, NULL)",
    "INSERT INTO T_WP_DTL VALUES (6001, 1001, 'P', 300, 1, 0.5, 0.5, NULL)",
    "INSERT INTO T_WP_DTL VALUES (5101, 1002, 'M', 115, 4, 3, 12, NULL)",
    "INSERT INTO T_WP_GOODS VALUES (115, '硬脂酸镁', 1, 3.5, 3.5)",
    "INSERT INTO T_WP_GOODS VALUES (116, '聚维酮K30', 0, 47, 47)",
]


def _detail_entity(view: str, kind: str) -> t.EntityConfig:
    return t.EntityConfig(
        table="T_WP_DTL", primary_key="DTLID", freezable=True, read_view=view,
        fields=[fld("DTLID", "number", role="system"), fld("DOCID", "number", role="system"),
                fld("KIND", role="system", default={"type": "static", "value": kind}), fld("GOODSID", "number"),
                fld("USAGE", "number"), fld("PRICE", "number"), fld("COST_BATCH", "number", role="calculated"), fld("MEMO")])


ENTITIES = {
    DOC: t.EntityConfig(
        table="T_WP_DOC", primary_key="DOCID", freezable=True,
        fields=[fld("DOCID", "number", role="system"), fld("MEMO"), fld("APEX_PL", "number"),
                fld("TOTAL_COST", "number", role="calculated"),
                fld("CREATE_BY", default={"type": "builtin", "value": "currentUserName"}),
                fld("USESTATUS", default={"type": "options", "value": ["草稿", "已提交"]}), fld("OWNER")],
        details=[t.DetailLink(entity=MATERIAL, parent_key="DOCID"), t.DetailLink(entity=PACKAGE, parent_key="DOCID")],
        field_defaults={"CREATE_BY": t.FieldFlags(editable=False), "OWNER": t.FieldFlags(editable=False)}),
    MATERIAL: _detail_entity("V_WP_MATERIAL", "M"),
    PACKAGE: _detail_entity("V_WP_PACKAGE", "P"),
    GOODS: t.EntityConfig(
        table="T_WP_GOODS", primary_key="GOODSID", freezable=True, erp_row=t.ErpRow(column="ISERP", value="1", local_value="0"),
        fields=[fld("GOODSID", "number", role="system"), fld("NAME", source="erp"), fld("ISERP", "number", role="system"),
                fld("PRICE", "number", source="erp"), fld("ZX_PRICE", "number")]),
}
WRITABLE = {(PAGE, DOC): ("MEMO", "APEX_PL", "USESTATUS"), (PAGE, MATERIAL): ("GOODSID", "USAGE", "PRICE", "MEMO"),
            (PAGE, PACKAGE): ("GOODSID", "USAGE", "PRICE", "MEMO"), (GOODS_PAGE, GOODS): ("NAME", "PRICE", "ZX_PRICE")}
_GRID = t.GridOptions(side_bar=True, cell_selection=True, group_by=[])
PACK = json.dumps({"packId": PAGE, "version": 1, "coreVersion": "0.1.0", "fields": {}, "rules": [], "jdm": {}}).encode()


def _detail_view(code: str) -> t.ViewDetail:
    return t.ViewDetail(entity=code, title=code, primary_key="DTLID", parent_key="DOCID",
                        fields=view_fields(ENTITIES[code], WRITABLE[(PAGE, code)]), buttons=[], grid=_GRID, form_layout=[])


def page_views(audit: bool = True) -> dict[str, t.PageView]:
    return {
        PAGE: t.PageView(page_code=PAGE, title="成本核算（测试）", version=1, layout="masterDetail", detail_mode="tabs", audit=audit,
                         save_operation=SAVE, rules_pack=t.PackRef(pack_id=PAGE, version=1),
                         master=t.ViewMaster(entity=DOC, primary_key="DOCID", fields=view_fields(ENTITIES[DOC], WRITABLE[(PAGE, DOC)]),
                                             buttons=[], grid=_GRID, form_layout=[]),
                         details=[_detail_view(MATERIAL), _detail_view(PACKAGE)], system_buttons=["save"]),
        GOODS_PAGE: t.PageView(page_code=GOODS_PAGE, title="物料清单（测试）", version=1, layout="single", detail_mode="tabs",
                               audit=audit, save_operation=GOODS_SAVE, rules_pack=t.PackRef(pack_id=GOODS_PAGE, version=1),
                               master=t.ViewMaster(entity=GOODS, primary_key="GOODSID",
                                                   fields=view_fields(ENTITIES[GOODS], WRITABLE[(GOODS_PAGE, GOODS)]),
                                                   buttons=[], grid=_GRID, form_layout=[], erp_row=ENTITIES[GOODS].erp_row),
                               details=[], system_buttons=["save"]),
    }


@dataclass
class WpSetup:
    """与 `support.Setup` 相同的用法，配置换成测试表。"""

    engine: FakeRulesEngine = field(default_factory=FakeRulesEngine)
    permission: FakePermissionChecker = field(default_factory=FakePermissionChecker)
    audit: bool = True

    def __post_init__(self) -> None:
        for (page, entity), names in WRITABLE.items():
            self.permission.set_writable(page, entity, names)
        self.pack = self.engine.load_pack(PACK)

    def context(self, user_id: str = USERS[0], display_name: str = "张三") -> t.ExecutionContext:
        operation = t.OperationConfig(label="保存", kind="save", propagation="continue")
        snapshot = FakeConfigSnapshot(version=1, role_code="WP_TEST", role=t.RoleConfig(name="测试", admin=False, pages={}),
                                      page_views=page_views(self.audit), entities=ENTITIES,
                                      operations={SAVE: operation, GOODS_SAVE: operation},
                                      packs={PAGE: self.pack, GOODS_PAGE: self.pack, DOC: self.pack, GOODS: self.pack})
        identity = t.Identity(user_id=user_id, username=f"user{user_id}", display_name=display_name, department_id="10",
                              role_code="WP_TEST", session_id=f"s-{user_id}")
        return t.ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=identity, config=snapshot,
                                  config_version=1, origin=t.Origin(kind="user", approval_id=None), now=NOW)


def inspector() -> FakeSchemaInspector:
    """与 DDL 一致的列小数位：T_WP_DTL.PRICE 为 NUMBER(18,2)，T_WP_GOODS.ZX_PRICE 为 NUMBER(18,4)，其余数值列没有定义小数位。"""
    found = FakeSchemaInspector()
    scales = {("T_WP_DTL", "PRICE"): 2, ("T_WP_GOODS", "ZX_PRICE"): 4}
    for table, pk in (("T_WP_DOC", "DOCID"), ("T_WP_DTL", "DTLID"), ("T_WP_GOODS", "GOODSID")):
        entity = next(e for e in ENTITIES.values() if e.table == table)
        found.add_table(table, [t.ColumnInfo(name=f.column, data_type="NUMBER" if f.type == "number" else "VARCHAR2",
                                             nullable=True, length=None, precision=None, scale=scales.get((table, f.column)))
                                for f in entity.fields if f.column], primary_key=pk)
    return found


def _run(engine: Engine, statements: list[str], ignore_errors: bool = False) -> None:
    with engine.connect() as connection:
        for sql in statements:
            try:
                connection.execute(text(sql))
            except DBAPIError:
                if not ignore_errors:
                    raise
        connection.commit()


def reset_rows(engine: Engine) -> None:
    """每个测试开始前恢复测试数据。"""
    _run(engine, ["DELETE FROM T_WP_DTL", "DELETE FROM T_WP_DOC", "DELETE FROM T_WP_GOODS", *ROWS,
                  f"DELETE FROM pf_command WHERE user_id IN ('{USERS[0]}', '{USERS[1]}')"])


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    from cost_platform.assembly.settings import Settings
    from cost_platform.db_core.engine import create_oracle_engine

    settings = Settings.load()
    found = create_oracle_engine(settings.db_user, settings.db_password, settings.db_dsn)
    _run(found, DROP, ignore_errors=True)  # 上次中断时留下的
    _run(found, DDL)
    yield found
    _run(found, [f"DELETE FROM pf_command WHERE user_id IN ('{USERS[0]}', '{USERS[1]}')"])
    _run(found, DROP, ignore_errors=True)
    found.dispose()


@pytest.fixture
def rows(engine: Engine) -> Engine:
    reset_rows(engine)
    return engine


def fetch(engine: Engine, sql: str, **binds: Any) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(r) for r in connection.execute(text(sql), binds).mappings()]
