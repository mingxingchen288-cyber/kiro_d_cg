"""C08 第 2 节端口的契约测试，用 db-core 的真实实现在 d_cg 上运行（C08 第 14 节、T-DB-1）。

另有 `OracleSchemaInspector` 在 d_cg 现有对象上的只读检查（序列是否存在，C08 没有，见 `.reports/modules/db-core/contract-gaps.md`；
列注释、按关键字列出表和视图，C08 v21）和只读事务的检查。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest
from sqlalchemy import Engine, exc, text

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import ColumnInfo, DbObject
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.db_core.legacy import OracleLegacyConnectionFactory
from cost_platform.db_core.schema import OracleSchemaInspector

from ..contracts.test_connection_factory import ConnectionFactoryContract
from ..contracts.test_schema_inspector import SchemaInspectorContract
from ..contracts.test_unit_of_work import UnitOfWorkContract
from .support import drop_if_exists, engine, ensure_table  # noqa: F401 - fixture

pytestmark = pytest.mark.oracle


# ---------------------------------------------------------------- SchemaInspector

def _ddl_type(column: ColumnInfo) -> str:
    if column.data_type == "NUMBER" and column.precision is not None:
        return f"NUMBER({column.precision},{column.scale or 0})"
    if column.data_type in ("VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR") and column.length is not None:
        return f"{column.data_type}({column.length})"
    return column.data_type


class OracleSchemaHarness:
    """在 d_cg 中建契约测试用的表和视图，结束时删除。"""

    def __init__(self, engine: Engine) -> None:  # noqa: F811
        self.engine = engine
        self.inspector = OracleSchemaInspector(engine)
        self._made: list[tuple[str, str]] = []

    def create_table(self, table: str, columns: Sequence[ColumnInfo], primary_key: str | None = None) -> None:
        drop_if_exists(self.engine, table)
        parts = [f"{c.name} {_ddl_type(c)}{'' if c.nullable else ' NOT NULL'}" for c in columns]
        if primary_key is not None:
            parts.append(f"CONSTRAINT PK_{table} PRIMARY KEY ({primary_key})")
        with self.engine.connect() as c:
            c.exec_driver_sql(f"CREATE TABLE {table} ({', '.join(parts)})")
        self._made.append(("TABLE", table))

    def create_view(self, view: str, table: str) -> None:
        with self.engine.connect() as c:
            c.exec_driver_sql(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM {table}")
        self._made.append(("VIEW", view))

    def missing_table(self) -> str:
        return "CT_SCHEMA_NO_SUCH_TABLE"

    def close(self) -> None:
        for kind, name in sorted(self._made, key=lambda item: item[0] != "VIEW"):  # 先删视图
            drop_if_exists(self.engine, name, kind)


class TestOracleSchemaInspector(SchemaInspectorContract):
    @pytest.fixture
    def harness(self, engine: Engine) -> Iterator[OracleSchemaHarness]:  # noqa: F811
        harness = OracleSchemaHarness(engine)
        yield harness
        harness.close()


def test_business_tables_and_views(engine: Engine) -> None:  # noqa: F811
    """复制来的物料表和物料清单视图：表有主键 GOODSID，视图没有；ZX_PRICE 是不带精度的 NUMBER（精度、小数位为空）。"""
    inspector = OracleSchemaInspector(engine)
    assert (inspector.object_type("T_COST_GOODS"), inspector.object_type("T_COST_GOODS_PRICE_V")) == ("table", "view")
    assert inspector.primary_key("T_COST_GOODS") == "GOODSID"
    assert inspector.primary_key("T_COST_GOODS_PRICE_V") is None
    goods = inspector.columns("T_COST_GOODS")
    assert goods is not None
    assert goods["ZX_PRICE"] == ColumnInfo("ZX_PRICE", "NUMBER", True, None, None, None)
    assert goods["GOODSID"] == ColumnInfo("GOODSID", "NUMBER", False, None, 19, 0)
    assert goods["GOODSNAME"] == ColumnInfo("GOODSNAME", "VARCHAR2", True, 1000, None, None)
    view = inspector.columns("T_COST_GOODS_PRICE_V")
    assert view is not None and {"GOODSID", "ZX_PRICE", "ROW_CLASS_FLAG"} <= set(view)


def test_sequence_exists(engine: Engine) -> None:  # noqa: F811
    """向导和实体校验要求 `<表名>_SEQ` 已存在（C06 第 10 节、C09 wizard/columns 的 sequence.exists）。"""
    inspector = OracleSchemaInspector(engine)
    assert inspector.sequence_exists("T_COST_GOODS_SEQ")
    assert inspector.sequence_exists("T_COST_PINGGU_LQ_SEQ")
    assert not inspector.sequence_exists("PF_ALEMBIC_VERSION_SEQ")


def test_column_comments(engine: Engine) -> None:  # noqa: F811
    """旧向导的列标题取列注释（MetaConfigService.listViewColumns）；液体成本主表复制时带上了 cmx 的注释。"""
    inspector = OracleSchemaInspector(engine)
    comments = inspector.column_comments("T_COST_PINGGU_LQ")
    assert comments is not None
    assert (comments["COST_PERBOX"], comments["M_PERPACK"], comments["DOCID"]) == ("每盒成本", "每中盒小盒数", None)
    assert inspector.column_comments("CT_SCHEMA_NO_SUCH_TABLE") is None


def test_objects_on_d_cg(engine: Engine) -> None:  # noqa: F811
    """DB-07（只读，只查数据字典）：向导输入"T_COST_GOODS"，列出物料表和物料清单视图，先表后视图；
    关键字为空时最多 100 个（同旧系统 listDbObjects）。"""
    inspector = OracleSchemaInspector(engine)
    found = inspector.objects("t_cost_goods")
    assert {DbObject("T_COST_GOODS", "table"), DbObject("T_COST_GOODS_PRICE_V", "view")} <= set(found)
    assert all("T_COST_GOODS" in o.name for o in found)
    kinds = [o.type for o in found]
    assert kinds == sorted(kinds)
    assert 0 < len(inspector.objects("")) <= 100


def test_view_sources_on_d_cg(engine: Engine) -> None:  # noqa: F811
    """DB-08（只读，只查数据字典）：物料清单的读取视图只读 T_COST_GOODS（加锁读取一条语句）；产品信息维护的读取视图
    关联客户、分销商表，外币管理的关联 cmx 经 ERP 链接读的视图（先锁表、再读视图，WP-03）。"""
    inspector = OracleSchemaInspector(engine)
    assert inspector.view_sources("T_COST_GOODS_PRICE_V") == ["T_COST_GOODS"]
    assert inspector.view_sources("T_COST_GOODS_V") == ["T_COST_CUSTOMER", "T_COST_GOODS", "T_COST_TRANPOSER"]
    assert inspector.view_sources("T_COST_FORMONEY_V") == ["CMX.ERP_FORMONEY_V", "T_COST_FORMONEY"]
    assert inspector.view_sources("T_COST_GOODS") is None


# ---------------------------------------------------------------- UnitOfWorkFactory、UnitOfWork

UOW_TABLE = "CT_DB_UOW_PROBE"


class OracleUnitOfWorkHarness:
    def __init__(self, engine: Engine) -> None:  # noqa: F811
        ensure_table(engine, UOW_TABLE, "(V VARCHAR2(20))")
        self.engine = engine
        self.factory = OracleUnitOfWorkFactory(engine)

    def write(self, uow: UnitOfWork, value: str) -> None:
        uow.connection.execute(text(f"INSERT INTO {UOW_TABLE} (V) VALUES (:v)"), {"v": value})

    def committed(self) -> list[str]:
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(text(f"SELECT V FROM {UOW_TABLE} ORDER BY V"))]


class TestOracleUnitOfWork(UnitOfWorkContract):
    @pytest.fixture
    def harness(self, engine: Engine) -> Iterator[OracleUnitOfWorkHarness]:  # noqa: F811
        yield OracleUnitOfWorkHarness(engine)
        drop_if_exists(engine, UOW_TABLE)


# ---------------------------------------------------------------- ConnectionFactory

class OracleConnectionFactoryHarness:
    def __init__(self, engine: Engine) -> None:  # noqa: F811
        self.engine = engine
        self.factory = OracleLegacyConnectionFactory(engine)

    def legacy_table(self) -> tuple[str, int]:
        """cmx 的液体成本核算主表和它现在的行数（含已删除的行）。"""
        with self.engine.connect() as c:
            return "T_COST_PINGGU_LQ", int(c.execute(text("SELECT COUNT(*) FROM CMX.T_COST_PINGGU_LQ")).scalar_one())


class TestOracleConnectionFactory(ConnectionFactoryContract):
    @pytest.fixture
    def harness(self, engine: Engine) -> OracleConnectionFactoryHarness:  # noqa: F811
        return OracleConnectionFactoryHarness(engine)


def test_legacy_connection_is_read_only_transaction(engine: Engine) -> None:  # noqa: F811
    """d_cg 账号能写自己的表，但在读 cmx 的连接里也写不进去：事务是只读的（ORA-01456）。"""
    ensure_table(engine, UOW_TABLE, "(V VARCHAR2(20))")
    try:
        factory = OracleLegacyConnectionFactory(engine)
        with factory.legacy_readonly() as connection, pytest.raises(exc.DBAPIError, match="ORA-01456"):
            connection.execute(text(f"INSERT INTO {UOW_TABLE} (V) VALUES ('x')"))
        with engine.connect() as c:
            assert c.execute(text(f"SELECT COUNT(*) FROM {UOW_TABLE}")).scalar_one() == 0
    finally:
        drop_if_exists(engine, UOW_TABLE)
