"""端到端用例 `frontend/tests/e2e/cost-config.spec.ts` 用：只读查询旧系统的币种视图 CMX.T_COST_FORMONEY_V（成本核算主表
币种 Lookup formoney 的数据源，汇率经 ERP 数据库链接取出），按 JSON 输出这个币种的名称和汇率，例如
`{"FMNAME": "欧元", "FMRATE": "7.5404"}`。

用法（backend 目录）：uv run python -m tests.e2e.formoney 欧元
"""

from __future__ import annotations

import json
import sys

from .dcg import one, oracle_engine


def main() -> None:
    engine = oracle_engine()
    try:
        found = one(engine, "SELECT fmname, fmrate FROM cmx.t_cost_formoney_v WHERE fmname = :n AND deleted = 0", n=sys.argv[1])
    finally:
        engine.dispose()
    print(json.dumps({"FMNAME": found["fmname"], "FMRATE": None if found["fmrate"] is None else str(found["fmrate"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
