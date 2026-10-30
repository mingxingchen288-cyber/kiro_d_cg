"""按 SQL 的两种按钮动作的展开（OP-09、OP-10，C06 第 6 节 v18）：`replaceDetails`、`updateRows`。

例子取自成本核算的两个按钮：
- "由BOM生成明细"（旧 P_COST_BOM_INSERT）：选中成本单 D（产品 900，原辅料 5001、5002），删掉原辅料的全部行，按 BOM
  查出的物料逐行新增；
- "同步采购价"（旧 P_PINGGU_COMPUTE_ALL）：不选行，按 SQL 找到单价和物料清单参考价不同的明细，改成参考价。

SQL 在 contracts 的内存 SQLite 中执行，表由 `Bench.setup_sql` 建立（模拟验证）；写入管道的合并、计算和写入在
`test_sql_actions_oracle.py` 中用 d_cg 真实验证。
"""

from __future__ import annotations

from decimal import Decimal

from cost_platform.contracts import types as t

from .support import A, D, E, MASTER, MATERIAL, Bench, button, command, operation, ref, snapshot, writes

dec = Decimal
BOM = "COST_PINGGU.generateFromBom"
SYNC_PRICE = "COST_PINGGU.syncPrice"

TABLES = (
    "CREATE TABLE T_TEST_BOM (PRODUCT NUMBER, SEQ NUMBER, GOODSID NUMBER, PRICE NUMBER)",
    "INSERT INTO T_TEST_BOM VALUES (900, 1, 115, 75), (900, 2, 120, 0.48), (901, 1, 116, 10)",
    "CREATE TABLE T_TEST_DTL (DOCID NUMBER, DTLID NUMBER, PRICE NUMBER)",
    "INSERT INTO T_TEST_DTL VALUES (2551, 6101, 75), (2553, 7001, 75), (2553, 7002, 10)",
)

REPLACE = {"action": "replaceDetails", "entity": MATERIAL,
           "sql": "SELECT B.GOODSID AS GOODSID, B.PRICE AS PRICE FROM T_TEST_BOM B WHERE B.PRODUCT = :product ORDER BY B.SEQ",
           "binds": {"product": f"{MASTER}.GOODSID"}}
UPDATE = {"action": "updateRows", "entity": MATERIAL,
          "sql": "SELECT D.DOCID AS DOC_ID, D.DTLID AS DTL_ID, D.PRICE AS PRICE FROM T_TEST_DTL D ORDER BY D.DOCID, D.DTLID",
          "recordKeyColumn": "DOC_ID", "rowKeyColumns": ["DTL_ID"]}


def test_replace_details_deletes_the_rows_then_adds_one_row_per_sql_row() -> None:
    """选中 D 点"由BOM生成明细"：先删掉 D 的原辅料 5001、5002，再按 D 的产品 900 查出的两行新增，值取 SQL 的同名列；
    新增行的 clientRowId 为 `tmp-` 加 UUID，同一请求重放时相同。"""
    config = snapshot({BOM: operation([REPLACE], writable={MATERIAL: ["GOODSID", "PRICE"]}, label="由BOM生成明细")})
    bench = Bench(config, setup_sql=TABLES)
    bench.run(command(BOM, [(MASTER, D)]))
    deletes = [(i.document.record_key, i.entity, i.row_key) for i in bench.merged if i.op == "delete"]
    adds = [(i.document.record_key, i.entity, i.values) for i in bench.merged if i.op == "add"]
    assert deletes == [(D, MATERIAL, "5001"), (D, MATERIAL, "5002")]
    assert adds == [(D, MATERIAL, {"GOODSID": dec(115), "PRICE": dec(75)}),
                    (D, MATERIAL, {"GOODSID": dec(120), "PRICE": dec("0.48")})]
    # 新增的行不补默认值（旧 P_COST_BOM_INSERT 只写查出的列，WP-16 的例外）
    assert [i.fill_defaults for i in bench.merged if i.op == "add"] == [False, False]
    ids = [i.client_row_id for i in bench.merged if i.op == "add"]
    assert all(t.parse_wire(t.DetailAdd, {"entity": MATERIAL, "op": "add", "clientRowId": c, "values": {}}) for c in ids)
    bench.close()

    again = Bench(config, setup_sql=TABLES)
    again.run(command(BOM, [(MASTER, D)]))
    assert [i.client_row_id for i in again.merged if i.op == "add"] == ids
    again.close()


def test_update_rows_needs_no_selection_and_the_documents_come_from_the_sql() -> None:
    """不选行点"同步采购价"：SQL 执行一次，查出 A 的 6101、E 的 7001 和 7002，按查出的值改单价；涉及的单据 A、E
    由 SQL 结果决定，不在 involved 中，由 write-pipeline 加锁、做冻结检查后再合并（WP-18）。"""
    config = snapshot({SYNC_PRICE: operation([UPDATE], label="同步采购价")}, buttons=[button(SYNC_PRICE, requires=False)])
    bench = Bench(config, setup_sql=TABLES)
    state = bench.run(command(SYNC_PRICE))
    assert writes(bench.merged) == [(A, MATERIAL, "6101", {"PRICE": dec(75)}), (E, MATERIAL, "7001", {"PRICE": dec(75)}),
                                    (E, MATERIAL, "7002", {"PRICE": dec(10)})]
    assert {i.document for i in bench.merged} == {ref(A), ref(E)}
    assert state.involved == [ref(A), ref(E)]
    bench.close()
