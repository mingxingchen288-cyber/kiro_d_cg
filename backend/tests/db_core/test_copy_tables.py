"""DB-03：复制到 d_cg 的业务表和视图符合清单 `db_core/business_tables.json`（真实验证，d_cg）。

这里只核对结构（列、顺序、虚拟列、主键、序列、视图不引用 cmx）和重复执行不改动。行数、逐行内容与 cmx 相同的核对是
复制当时的一次性检查（`.reports/modules/db-core/` 的核对 SQL）：cmx 还在使用、数据在变，平台不做持续同步，
所以不写成每次都跑的测试。
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

from cost_platform.db_core.copy_tables import TableSpec, ViewSpec, copy_business_tables, table_specs
from cost_platform.db_core.schema import OracleSchemaInspector

from .support import engine  # noqa: F401 - fixture

pytestmark = pytest.mark.oracle

SPECS = table_specs()


@pytest.mark.parametrize("name", [n for n, s in SPECS.items() if isinstance(s, TableSpec)])
def test_table_follows_the_list(engine: Engine, name: str) -> None:  # noqa: F811
    spec = SPECS[name]
    assert isinstance(spec, TableSpec)
    inspector = OracleSchemaInspector(engine)
    with engine.connect() as c:
        cmx_order = [r[0] for r in c.execute(text(
            "SELECT column_name FROM all_tab_cols WHERE owner = 'CMX' AND table_name = :t AND hidden_column = 'NO' "
            "ORDER BY column_id"), {"t": name})]
        virtual = c.execute(text("SELECT COUNT(*) FROM user_tab_cols WHERE table_name = :t AND virtual_column = 'YES'"),
                            {"t": name}).scalar_one()
    columns = inspector.columns(name)
    assert inspector.object_type(name) == "table" and columns is not None
    assert list(columns) == [c for c in cmx_order if c in set(spec.columns)] and set(columns) == set(spec.columns)
    assert virtual == 0
    assert inspector.primary_key(name) is not None
    assert inspector.sequence_exists(f"{name}_SEQ")


@pytest.mark.parametrize("name", [n for n, s in SPECS.items() if isinstance(s, ViewSpec)])
def test_view_uses_d_cg_tables(engine: Engine, name: str) -> None:  # noqa: F811
    inspector = OracleSchemaInspector(engine)
    with engine.connect() as c:
        rows = c.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one()  # 查询一次：引用的表重建过时视图在这里重新编译
        body, status = c.execute(text("SELECT v.text_vc, o.status FROM user_views v JOIN user_objects o "
                                      "ON o.object_name = v.view_name AND o.object_type = 'VIEW' WHERE v.view_name = :v"),
                                 {"v": name}).one()
        referenced = {r[0] for r in c.execute(text(
            "SELECT referenced_owner FROM user_dependencies WHERE name = :v AND type = 'VIEW'"), {"v": name})}
    assert inspector.object_type(name) == "view" and status == "VALID" and rows > 0
    spec = SPECS[name]
    assert isinstance(spec, ViewSpec)
    if spec.reads_cmx:  # 直接读 cmx 视图的例外（copy_tables 文件说明）：只引用 cmx 和 d_cg 自己
        assert referenced <= {"CMX", "D_CG"}
    else:
        assert "CMX." not in body.upper() and "CMX" not in referenced


def test_copy_again_changes_nothing(engine: Engine) -> None:  # noqa: F811
    report = copy_business_tables(engine, SPECS)
    assert report == [f"{name}: 已存在，未改动" for name in SPECS]
