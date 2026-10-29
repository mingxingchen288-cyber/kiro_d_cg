"""DB-01：数值列读出为 Decimal，写入用 Decimal，全程不经过浮点（真实验证，d_cg）。

列有两种：业务表中最常见的不带精度的 NUMBER（例如 T_COST_GOODS.PRICE、ZX_PRICE），和带精度的 NUMBER(38,8)。
每次写入都在一个不提交的事务里，退出时回滚。
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal, localcontext

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, text

from cost_platform.db_core.engine import OracleUnitOfWorkFactory

from .support import drop_if_exists, engine, ensure_table  # noqa: F401 - fixture

pytestmark = pytest.mark.oracle

TABLE = "CT_DB_DECIMAL_PROBE"
D = Decimal


@pytest.fixture(scope="module")
def factory(engine: Engine) -> Iterator[OracleUnitOfWorkFactory]:  # noqa: F811
    ensure_table(engine, TABLE, "(ID NUMBER(10) PRIMARY KEY, FREE NUMBER, FIXED NUMBER(38,8))")
    yield OracleUnitOfWorkFactory(engine)
    drop_if_exists(engine, TABLE)


def round_trip(factory: OracleUnitOfWorkFactory, value: Decimal) -> tuple[object, object, object]:
    """写入两列再读出两列和它们的和（SQL 表达式的结果也是不带精度的 NUMBER）。"""
    with factory.begin() as uow:
        uow.connection.execute(text(f"INSERT INTO {TABLE} (ID, FREE, FIXED) VALUES (1, :v, :v)"), {"v": value})
        free, fixed, total = uow.connection.execute(text(f"SELECT FREE, FIXED, FREE + FIXED FROM {TABLE} WHERE ID = 1")).one()
    return free, fixed, total


def doubled(value: Decimal) -> Decimal:
    """精确的两倍（Python 默认只保留 28 位有效数字）。"""
    with localcontext(prec=60):
        return value * 2


@pytest.mark.parametrize("value", [
    D("12345678901234567890.123456"), D("-12345678901234567890.123456"), D("0"),
    D("1.23456789"), D("-1.23456789"),  # E04：存进数据库的值
    D("75"), D("0.064"),  # 物料清单：聚维酮K30 的单价 75，说明书的参考价格 0.064
])
def test_round_trip_keeps_value_as_decimal(factory: OracleUnitOfWorkFactory, value: Decimal) -> None:
    free, fixed, total = round_trip(factory, value)
    assert (free, fixed, total) == (value, value, doubled(value))
    assert all(type(v) is Decimal for v in (free, fixed, total)), (type(free), type(fixed), type(total))


# 整数部分最多 29 位、6 位小数：NUMBER(38,8) 存得下，两倍之后仍在 Oracle NUMBER 的 38 位有效数字之内
LIMIT = D("99999999999999999999999999999.999999")


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.decimals(min_value=-LIMIT, max_value=LIMIT, places=6, allow_nan=False, allow_infinity=False))
def test_generated_values_round_trip(factory: OracleUnitOfWorkFactory, value: Decimal) -> None:
    """整数部分不超过 29 位的任意 6 位小数，写入再读出数值相等，读出的都是 Decimal。"""
    free, fixed, total = round_trip(factory, value)
    assert (free, fixed, total) == (value, value, doubled(value))
    assert all(type(v) is Decimal for v in (free, fixed, total))


def test_business_values_read_as_decimal(engine: Engine) -> None:  # noqa: F811
    """d_cg 中复制来的物料清单：聚维酮K30（25）的主键和单价读出都是 Decimal，不是 int 或 float。"""
    with OracleUnitOfWorkFactory(engine).begin() as uow:
        goodsid, price, zx_price = uow.connection.execute(
            text("SELECT GOODSID, PRICE, ZX_PRICE FROM T_COST_GOODS_PRICE_V WHERE GOODSID = 25")).one()
    assert (goodsid, price, zx_price) == (D(25), D(75), D(75))
    assert all(type(v) is Decimal for v in (goodsid, price, zx_price))
