"""浏览器用例 `frontend/tests/e2e/liquid-cost.spec.ts` 用：按旧 P_COST_BOM_INSERT_LQ 的查询算出一张液体成本单"由BOM生成明细"
应该新增的行（只读 d_cg 和 cmx 的 BOM 树），输出 JSON。

旧过程（`my-project/sql20260523/03_program_units.sql` 第 772–790 行）按产品查 BOM 树 CMX.T_COST_BOM_GOODS_TREE_V，
插入物料、BOM 用量（batch_qty）和 PUB_GOODS_V 的单价；随后 P_PINGGU_DTL_COMPUTE_LQ 第一步按 BOM 用量反推原辅料的每片含量
（per_hl = batch_qty / apex_pl * 1000000）。原辅料、包材按物料清单的分类归到两个明细（同两个读取视图）。

用法（backend 目录）：uv run python -m tests.e2e.liquid bom --doc <液体成本单>
"""

from __future__ import annotations

import argparse
import json

from .dcg import oracle_engine, rows

BOM_SQL = """SELECT V.GOODSID AS GOODSID, G.USEFLAG AS USEFLAG, V.USEQTY AS USEQTY, F.PRICE AS PRICE,
       CASE WHEN G.USEFLAG IN ('原料', '辅料') THEN NVL(V.USEQTY, 0) / NULLIF(M.APEX_PL, 0) * 1000000 END AS PER_HL
  FROM T_COST_PINGGU_LQ M
  JOIN CMX.T_COST_BOM_GOODS_TREE_V V ON V.TREEID LIKE '-' || M.GOODSID || '-%'
  JOIN T_COST_GOODS G ON G.GOODSID = V.GOODSID
  LEFT JOIN CMX.PUB_GOODS_V F ON F.GOODSID = V.GOODSID
 WHERE M.DOCID = :docid AND V.PID <> '-1' AND V.USEFLAG NOT IN (0, 1)
   AND G.USEFLAG IN ('原料', '辅料', '非印字包材', '印字包材')
 ORDER BY V.TREEID"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["bom"])
    parser.add_argument("--doc", required=True)
    args = parser.parse_args()
    found = rows(oracle_engine(), BOM_SQL, docid=int(args.doc))
    out = [{"entity": "COST_MATERIAL_LQ" if r["useflag"] in ("原料", "辅料") else "COST_PACKAGE_LQ", "goodsid": str(r["goodsid"]),
            "useqty": None if r["useqty"] is None else format(r["useqty"].normalize(), "f"),
            "price": None if r["price"] is None else format(r["price"].normalize(), "f"),
            "perHl": None if r["per_hl"] is None else format(r["per_hl"], "f")} for r in found]
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
