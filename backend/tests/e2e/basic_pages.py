"""端到端用例 `frontend/tests/e2e/basic-pages-1031.spec.ts`（第 8 批 G1：产品信息维护、客户信息、外币管理）用的测试数据：
自己建、自己删，不改 d_cg 已有的行。

- 外币：页面上外币的各列都不能填（同旧系统 formoney-manage 的列配置，EDITABLE 全为 0），测试外币直接写 T_COST_FORMONEY，
  主键取 T_COST_FORMONEY_SEQ（写法同 sample_two.py 的 CreatedData）。`CREATE_BY` 为 'system' 的是"同步ERP汇率"要清空本地汇率的，
  其余不动（旧按钮 SQL：UPDATE T_COST_FORMONEY SET FMRATE = NULL … WHERE CREATE_BY = 'system'）。
- ERP 汇率：只读 cmx 的 ERP_FORMONEY_V（经 ERP 数据库链接读 ERP 的外币，d_cg 的 T_COST_FORMONEY_V 也从它取 ERP 汇率）。
- 删除：用例结束时按主键直接删测试外币，以及经页面建的产品、客户（连同分销商）中还在的。

用法（backend 目录）：
  uv run python -m tests.e2e.basic_pages currency --name "PF_TEST 外币甲" --by system --rate 9.99
  uv run python -m tests.e2e.basic_pages erp-rates
  uv run python -m tests.e2e.basic_pages drop --currencies <外币,…> --goods <产品,…> --customers <客户,…>
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal

from sqlalchemy import Engine, text

from .dcg import oracle_engine, rows


def add_currency(engine: Engine, name: str, by: str, rate: str) -> str:
    with engine.begin() as conn:
        fmid = str(conn.execute(text("SELECT t_cost_formoney_seq.NEXTVAL FROM dual")).scalar_one())
        conn.execute(text("INSERT INTO t_cost_formoney (fmid, fmname, fmrate, usestatus, create_by) VALUES (:k, :n, :r, 1, :b)"),
                     {"k": int(fmid), "n": name, "r": Decimal(rate), "b": by})
    return fmid


def erp_rates(engine: Engine) -> dict[str, str | None]:
    """d_cg 外币表中本地汇率为空的外币在 ERP 的汇率（FMID → 汇率文本）。"""
    local = [r["fmid"] for r in rows(engine, "SELECT fmid FROM t_cost_formoney WHERE fmrate IS NULL")]
    if not local:
        return {}
    found = rows(engine, "SELECT fmid, fmrate FROM cmx.erp_formoney_v WHERE fmid IN ("
                         + ", ".join(str(int(k)) for k in local) + ")")
    return {str(r["fmid"]): None if r["fmrate"] is None else format(Decimal(str(r["fmrate"])).normalize(), "f") for r in found}


def drop(engine: Engine, currencies: list[str], goods: list[str], customers: list[str]) -> None:
    with engine.begin() as conn:
        for key in currencies:
            conn.execute(text("DELETE FROM t_cost_formoney WHERE fmid = :k"), {"k": int(key)})
        for key in goods:
            conn.execute(text("DELETE FROM t_cost_goods WHERE goodsid = :k"), {"k": int(key)})
        for key in customers:
            conn.execute(text("DELETE FROM t_cost_tranposer WHERE customid = :k"), {"k": int(key)})
            conn.execute(text("DELETE FROM t_cost_customer WHERE customid = :k"), {"k": int(key)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["currency", "erp-rates", "drop"])
    parser.add_argument("--name", default="")
    parser.add_argument("--by", default="system")
    parser.add_argument("--rate", default="1")
    parser.add_argument("--currencies", default="")
    parser.add_argument("--goods", default="")
    parser.add_argument("--customers", default="")
    args = parser.parse_args()
    engine = oracle_engine()
    try:
        if args.action == "currency":
            print(json.dumps({"fmid": add_currency(engine, args.name, args.by, args.rate)}))
        elif args.action == "erp-rates":
            print(json.dumps(erp_rates(engine)))
        else:
            split = [[k for k in v.split(",") if k] for v in (args.currencies, args.goods, args.customers)]
            drop(engine, *split)
            print(json.dumps({"dropped": {"currencies": split[0], "goods": split[1], "customers": split[2]}}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
