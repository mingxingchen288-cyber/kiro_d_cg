"""端到端用例 `frontend/tests/e2e/cost-config.spec.ts` 用：只读查询币种视图 T_COST_FORMONEY_V（成本核算主表币种 Lookup
formoney 的数据源；2026-10-31 起读 d_cg 的外币表，本地汇率为空时取 cmx 经 ERP 数据库链接读的汇率，第 8 批 G1），
按 JSON 输出这个币种的名称和汇率，例如 `{"FMNAME": "欧元", "FMRATE": "7.5404"}`。
用法（backend 目录）：uv run python -m tests.e2e.formoney 欧元
"""

from __future__ import annotations

import json
import sys

from .dcg import one, oracle_engine


def main() -> None:
    engine = oracle_engine()
    try:
        found = one(engine, "SELECT fmname, fmrate FROM t_cost_formoney_v WHERE fmname = :n", n=sys.argv[1])
    finally:
        engine.dispose()
    print(json.dumps({"FMNAME": found["fmname"], "FMRATE": None if found["fmrate"] is None else str(found["fmrate"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
