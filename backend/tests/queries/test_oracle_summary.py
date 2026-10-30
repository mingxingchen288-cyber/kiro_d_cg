"""汇总行的真实验证（d_cg，标 oracle）：`sum_fields` 取 seed 配置生成的页面视图（C06 第 3 节 `aggregate`，由旧系统
cost-pinggu 列配置的 aggFunc: "sum" 推出），列表的 `aggregates` 对全部满足条件的行求和（QE-04），与直接查询相同。只读。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from cost_platform.config.catalog import Catalog
from cost_platform.config.seed import read_seed
from cost_platform.config.views import build_page_view
from cost_platform.contracts.fakes import FakeConfigSnapshot, FakePermissionChecker
from cost_platform.contracts.types import ListRequest, PackRef, parse_wire
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.queries.catalog import snapshot_catalog
from cost_platform.queries.lists import PageQueries

from .support import context
from .test_oracle import engine, uow  # noqa: F401  （复用同一个 d_cg 连接）

pytestmark = pytest.mark.oracle

SEED = Path(__file__).resolve().parents[2] / "seed" / "config"
PAGE = "COST_PINGGU"
SUMMED = ["TOTAL_FL", "TOTAL_BC", "TOTAL_YL", "TOTAL_COST", "COST_PERBOX", "OUT_PRICE_RMB", "SALEMONEY", "JGF_BATCH", "COST_PERQP",
          "JGF_PERQP", "ML_PERQP", "Y_JG_RE", "Y_ML", "Y_SALE"]
"""cmx 中 cost-pinggu 主表 aggFunc 为 sum 的 14 列（`.reports/batch1-20261029/summary/01-旧汇总配置.out.txt`）。"""


def _snapshot() -> FakeConfigSnapshot:
    """seed 配置下系统管理员（ADMIN）的成本核算页视图，与 config 保存时生成的相同（`build_page_view`）。"""
    catalog = Catalog({}).merged(read_seed(SEED))
    page = catalog.page(PAGE)
    role = catalog.roles()["ADMIN"]
    view = build_page_view(PAGE, page, catalog.entities(), role, 1, PackRef(pack_id=PAGE, version=1),
                           catalog.operation(page.save_operation).writable_fields)
    return FakeConfigSnapshot(version=1, role_code="ADMIN", role=role, page_views={PAGE: view}, entities=catalog.entities())


def test_summary_row_sums_every_matching_cost_document(engine: Engine, uow: OracleUnitOfWorkFactory) -> None:  # noqa: F811
    """成本核算主表筛选"产品名称含 片"、只取第一页 20 行：14 个求和字段的汇总与 d_cg 上直接 SUM 全部满足条件的行相同。"""
    request = parse_wire(ListRequest, {"startRow": 0, "endRow": 20, "filterModel": {
        "GOODSNAME": {"filterType": "text", "type": "contains", "filter": "片"}}})
    result = PageQueries(uow, FakePermissionChecker(), catalog=snapshot_catalog).list(context(_snapshot(), user_id="1"), PAGE, request)
    with engine.connect() as conn:
        expected = conn.execute(text(f"SELECT COUNT(*), {', '.join(f'SUM({f})' for f in SUMMED)} FROM T_COST_PINGGU "
                                     "WHERE GOODSNAME LIKE '%片%'")).one()
    assert len(result.rows) == 20 and result.total == expected[0] > 20
    assert list(result.aggregates) == SUMMED
    assert [Decimal(str(result.aggregates[f])) for f in SUMMED] == [Decimal(str(v)) for v in expected[1:]]
