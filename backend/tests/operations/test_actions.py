"""按钮通用动作的展开（OP-01、OP-02、OP-07，C06 第 6 节）。

例子取自任务卡 T-OP-1 和 C06 第 6 节：按钮"同步单价"选中成本单 D（物料 115 单价 80、116 单价 12），把单价同步给
其他含同一物料的成本单。
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from cost_platform.contracts import types as t

from .support import (
    A,
    B,
    D,
    E,
    GOODS,
    MASTER,
    MATERIAL,
    SYNC,
    Bench,
    command,
    cost_doc,
    detail_sql_finder,
    document_sql_finder,
    goods_key_finder,
    material,
    operation,
    ref,
    snapshot,
    writes,
)

dec = Decimal


def update_records(finder: t.TargetFinderConfig, mapping: list[tuple[str, str]]) -> dict:
    return {"action": "updateRecords", "find": t.dump_wire(t.TargetFinder, finder),
            "fieldMapping": [{"from": f, "to": to} for f, to in mapping]}


def preset_detail_rows(bench: Bench, source: str = D) -> None:
    """关联 SQL 按 D 的每一行执行时查出的明细：115 → A.6101、E.7001；116 → A.6102、B.6201、E.7002。"""
    finder = detail_sql_finder()
    bench.related.respond_rows(finder, [{"DOC_ID": dec(A), "DTL_ID": dec(6101)}, {"DOC_ID": dec(E), "DTL_ID": dec(7001)}],
                               binds={"goodsId": dec(115), "docId": dec(source)})
    bench.related.respond_rows(finder, [{"DOC_ID": dec(A), "DTL_ID": dec(6102)}, {"DOC_ID": dec(B), "DTL_ID": dec(6201)},
                                        {"DOC_ID": dec(E), "DTL_ID": dec(7002)}],
                               binds={"goodsId": dec(116), "docId": dec(source)})


def preset_documents(bench: Bench) -> None:
    """按整张单据找：115 → A、E；116 → A、B、E。"""
    finder = document_sql_finder()
    bench.related.respond_rows(finder, [{"DOC_ID": dec(A)}, {"DOC_ID": dec(E)}], binds={"goodsId": dec(115), "docId": dec(D)})
    bench.related.respond_rows(finder, [{"DOC_ID": dec(A)}, {"DOC_ID": dec(B)}, {"DOC_ID": dec(E)}],
                               binds={"goodsId": dec(116), "docId": dec(D)})


SYNC_DETAILS = update_records(detail_sql_finder(), [(f"{MATERIAL}.PRICE", "PRICE")])


# ---------------------------------------------------------------- updateRecords

def test_sync_unit_price_writes_the_value_of_the_row_that_found_each_target() -> None:
    """任务卡：D 中 115 单价 80、116 单价 12，由 116 那一行找到的其他成本单明细写 12，由 115 找到的写 80。"""
    bench = Bench(snapshot({SYNC: operation([SYNC_DETAILS])}))
    preset_detail_rows(bench)
    state = bench.run(command(SYNC, [(MASTER, D)]))
    assert writes(bench.merged) == [
        (A, MATERIAL, "6101", {"PRICE": dec(80)}), (E, MATERIAL, "7001", {"PRICE": dec(80)}),
        (A, MATERIAL, "6102", {"PRICE": dec(12)}), (B, MATERIAL, "6201", {"PRICE": dec(12)}),
        (E, MATERIAL, "7002", {"PRICE": dec(12)})]
    # 找到的明细按所属主单记，不在 involved 中的单据由 write-pipeline 加锁、做冻结检查后再合并（WP-18）
    assert {i.document for i in bench.merged} == {ref(A), ref(B), ref(E)}
    assert state.involved[0] == ref(D)
    bench.close()


def test_update_records_queries_with_the_current_database_data_one_row_at_a_time() -> None:
    """OP-07、OP-08：按 D 在数据库中的当前数据（加锁读到的）查找，绑定明细字段时按行分别调用，每次只传一行。"""
    bench = Bench(snapshot({SYNC: operation([SYNC_DETAILS])}))
    preset_detail_rows(bench)
    bench.run(command(SYNC, [(MASTER, D)]))
    sources = [c.args[2] for c in bench.related.calls_to("find")]
    assert [[r.row_key for r in s.details[MATERIAL]] for s in sources] == [["5001"], ["5002"]]
    database = bench.docs[ref(D)]
    assert all(s.master.values == database.master.values for s in sources)
    assert [s.details[MATERIAL][0].values for s in sources] == [r.values for r in database.details[MATERIAL]]
    bench.close()


def test_field_mapping_takes_the_value_after_the_previous_actions() -> None:
    """OP-02：`from` 取来源计算后的值：前面的动作把 D 中 115 那一行算成 85 时，同步的是 85。"""
    bench = Bench(snapshot({SYNC: operation([SYNC_DETAILS])}))
    preset_detail_rows(bench)
    state = bench.prepare(command(SYNC, [(MASTER, D)]))
    computed = copy.deepcopy(state.current[ref(D)])
    computed.details[MATERIAL][0].values["PRICE"] = dec(85)
    state.candidate[ref(D)] = computed
    ctx = bench.ctx()
    assert bench.stage is not None
    bench.stage.run(bench.uow, state, ctx)
    assert writes(state.intents)[0] == (A, MATERIAL, "6101", {"PRICE": dec(85)})
    bench.close()


def test_two_rows_writing_different_values_to_one_target_row_is_validation_failed() -> None:
    """C06 第 6 节：D 有两行 115、单价 80 和 82，A 中 115 那一行被写入两个值，返回 422 VALIDATION_FAILED。"""
    bench = Bench(snapshot({SYNC: operation([SYNC_DETAILS])}))
    bench.docs[ref(D)] = cost_doc(D, [material("5001", D, 115, "80"), material("5003", D, 115, "82")])
    finder = detail_sql_finder()
    bench.related.respond_rows(finder, [{"DOC_ID": dec(A), "DTL_ID": dec(6101)}], binds={"goodsId": dec(115), "docId": dec(D)})
    with pytest.raises(t.PlatformError) as caught:
        bench.run(command(SYNC, [(MASTER, D)]))
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    detail = caught.value.details[0]
    assert (detail.entity, detail.row_key, detail.field) == (MATERIAL, "6101", "PRICE")
    assert "80 和 82" in (detail.message or "")
    bench.close()


def test_rows_whose_key_is_null_are_skipped_and_the_rest_are_updated() -> None:
    """关联 SQL 查出的行中有一行主键为空（记录已不存在）时，跳过这一行，其余行照常更新，不报错。"""
    bench = Bench(snapshot({SYNC: operation([SYNC_DETAILS])}))
    finder = detail_sql_finder()
    bench.related.respond_rows(finder, [{"DOC_ID": None, "DTL_ID": dec(6999)}, {"DOC_ID": dec(A), "DTL_ID": dec(6101)},
                                        {"DOC_ID": dec(B), "DTL_ID": None}],
                               binds={"goodsId": dec(115), "docId": dec(D)})
    bench.run(command(SYNC, [(MASTER, D)]))
    assert writes(bench.merged) == [(A, MATERIAL, "6101", {"PRICE": dec(80)})]
    bench.close()


def test_update_records_to_the_goods_list_execution_price() -> None:
    """按关联键找物料清单，把成本单明细的单价写到执行价 ZX_PRICE（本地列，ERP 行也可以写）。"""
    sync = update_records(goods_key_finder(), [(f"{MATERIAL}.PRICE", "ZX_PRICE")])
    bench = Bench(snapshot({SYNC: operation([sync], writable={GOODS: ["ZX_PRICE"]}, impact=[GOODS])}))
    for key in ("115", "116"):
        bench.related.add_target(GOODS, "GOODSID", dec(key), t.TargetObject(GOODS, key, (), {}, False))
    bench.run(command(SYNC, [(MASTER, D)]))
    assert writes(bench.merged) == [("115", GOODS, "115", {"ZX_PRICE": dec(80)}),
                                    ("116", GOODS, "116", {"ZX_PRICE": dec(12)})]
    bench.close()


# ---------------------------------------------------------------- updateTargets 和 match

FIND_DOCUMENTS = update_records(document_sql_finder(), [])
PRICE_BY_GOODS = {"action": "updateTargets", "targets": [
    {"entity": MASTER, "detailEntity": MATERIAL, "match": {"GOODSID": f"{MATERIAL}.GOODSID"},
     "fieldMapping": [{"from": f"{MATERIAL}.PRICE", "to": "PRICE"}]}]}


def test_document_found_by_two_rows_writes_each_matched_detail_row_without_conflict() -> None:
    """C06 第 6 节：E 同时含 115 和 116、作为整张单据被 D 的两行都找到，match 按物料编号选明细：
    E 中 115 那一行写 80、116 那一行写 12，不冲突；E 中其他物料的行不动。"""
    bench = Bench(snapshot({SYNC: operation([FIND_DOCUMENTS, PRICE_BY_GOODS])}))
    preset_documents(bench)
    bench.run(command(SYNC, [(MASTER, D)]))
    first, second = bench.merged[:3], bench.merged[3:]
    # 第一个动作只找单据（fieldMapping 为空）：空修改让 write-pipeline 把 A、E、B 加锁读入
    assert writes(first) == [(A, MASTER, A, {}), (E, MASTER, E, {}), (B, MASTER, B, {})]
    # 第二个动作用第一个动作合并后的数据（OP-01）；按目标找到的先后，每个目标内按找到它的来源行的先后
    assert writes(second) == [
        (A, MATERIAL, "6101", {"PRICE": dec(80)}), (A, MATERIAL, "6102", {"PRICE": dec(12)}),
        (E, MATERIAL, "7001", {"PRICE": dec(80)}), (E, MATERIAL, "7002", {"PRICE": dec(12)}),
        (B, MATERIAL, "6201", {"PRICE": dec(12)})]
    bench.close()


def test_matched_detail_row_written_twice_with_different_values_is_validation_failed() -> None:
    """C06 第 6 节：D 有两行 115（80、82）时，E 中 115 那一行被写入两个值，返回 422。"""
    bench = Bench(snapshot({SYNC: operation([FIND_DOCUMENTS, PRICE_BY_GOODS])}))
    bench.docs[ref(D)] = cost_doc(D, [material("5001", D, 115, "80"), material("5003", D, 115, "82")])
    bench.related.respond_rows(document_sql_finder(), [{"DOC_ID": dec(E)}], binds={"goodsId": dec(115), "docId": dec(D)})
    with pytest.raises(t.PlatformError) as caught:
        bench.run(command(SYNC, [(MASTER, D)]))
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    assert [(d.entity, d.row_key, d.field) for d in caught.value.details] == [(MATERIAL, "7001", "PRICE")]
    bench.close()


# ---------------------------------------------------------------- to 的可写检查

def test_mapping_to_a_calculated_field_is_rejected() -> None:
    """映射到计算字段（金额 COST_BATCH）：422 FIELD_NOT_WRITABLE。"""
    to_calc = update_records(detail_sql_finder(), [(f"{MATERIAL}.PRICE", "COST_BATCH")])
    bench = Bench(snapshot({SYNC: operation([to_calc], writable={MATERIAL: ["PRICE", "COST_BATCH"]})}))
    preset_detail_rows(bench)
    with pytest.raises(t.PlatformError) as caught:
        bench.run(command(SYNC, [(MASTER, D)]))
    assert caught.value.code is t.ErrorCode.FIELD_NOT_WRITABLE
    assert {d.field for d in caught.value.details} == {"COST_BATCH"}
    bench.close()


def test_mapping_outside_the_operation_writable_fields_is_rejected() -> None:
    """`to` 必须在操作允许写入的字段内（OP-02）：只允许写 PRICE 时写 MEMO 被拒绝。"""
    to_memo = update_records(detail_sql_finder(), [(f"{MASTER}.MEMO", "MEMO")])
    bench = Bench(snapshot({SYNC: operation([to_memo], writable={MATERIAL: ["PRICE"]})}))
    preset_detail_rows(bench)
    with pytest.raises(t.PlatformError) as caught:
        bench.run(command(SYNC, [(MASTER, D)]))
    assert caught.value.code is t.ErrorCode.FIELD_NOT_WRITABLE
    bench.close()


FIND_GOODS = update_records(goods_key_finder(), [])
PRICE_TO_GOODS = {"action": "updateTargets",
                  "targets": [{"entity": GOODS, "fieldMapping": [{"from": f"{MATERIAL}.PRICE", "to": "PRICE"}]}]}


def _goods_bench(rows: list[t.Row]) -> Bench:
    bench = Bench(snapshot({SYNC: operation([FIND_GOODS, PRICE_TO_GOODS], writable={GOODS: ["PRICE"]}, impact=[GOODS])}))
    bench.docs[ref(D)] = cost_doc(D, rows)
    for key in ("115", "116"):
        bench.related.add_target(GOODS, "GOODSID", dec(key), t.TargetObject(GOODS, key, (), {}, False))
    return bench


def test_mapping_to_an_erp_column_of_an_erp_row_is_rejected() -> None:
    """C06 第 6 节：目标行是 ERP 行（物料 115，ISERP=1）而 `to` 是 ERP 列 PRICE 时，整个命令 422 FIELD_NOT_WRITABLE。"""
    bench = _goods_bench([material("5001", D, 115, "80"), material("5002", D, 116, "12")])
    with pytest.raises(t.PlatformError) as caught:
        bench.run(command(SYNC, [(MASTER, D)]))
    assert caught.value.code is t.ErrorCode.FIELD_NOT_WRITABLE
    assert [(d.entity, d.row_key, d.field) for d in caught.value.details] == [(GOODS, "115", "PRICE")]
    bench.close()


def test_erp_column_of_a_local_row_can_be_written() -> None:
    """本地行（物料 116，ISERP=0）的 ERP 列由平台维护，可以写（C06 第 2 节 erpRow）。"""
    bench = _goods_bench([material("5002", D, 116, "12")])
    bench.run(command(SYNC, [(MASTER, D)]))
    assert writes(bench.merged)[-1] == ("116", GOODS, "116", {"PRICE": dec(12)})
    bench.close()


# ---------------------------------------------------------------- recalculate

def test_recalculate_source_and_targets() -> None:
    """`recalculate`：source 为选中的 D；targets 为前面 updateRecords 找到的 A、E、B。展开为主表行的空修改，
    单据进入候选数据，由 write-pipeline 按各自的计算规则重算。"""
    actions = [{"action": "recalculate", "target": "source"}, FIND_DOCUMENTS, {"action": "recalculate", "target": "targets"}]
    bench = Bench(snapshot({SYNC: operation(actions)}))
    preset_documents(bench)
    bench.run(command(SYNC, [(MASTER, D)]))
    assert writes(bench.merged[:1]) == [(D, MASTER, D, {})]
    assert writes(bench.merged[-3:]) == [(A, MASTER, A, {}), (E, MASTER, E, {}), (B, MASTER, B, {})]
    bench.close()


# ---------------------------------------------------------------- 选中的行已被删除

def test_deleted_selected_rows_are_skipped() -> None:
    """选中的行在点按钮前已被删除，rowNotFound 为 skip：写入 skipped，其余的行照常处理。"""
    bench = Bench(snapshot({SYNC: operation([{"action": "recalculate", "target": "source"}])}))
    state = bench.run(command(SYNC, [(MASTER, D), (MASTER, "2560"), (MATERIAL, "5009")]))
    assert [(s.entity, s.row_key, s.reason) for s in state.skipped] == [(MASTER, "2560", "ROW_NOT_FOUND"),
                                                                        (MATERIAL, "5009", "ROW_NOT_FOUND")]
    assert writes(bench.merged) == [(D, MASTER, D, {})]
    bench.close()


def test_deleted_selected_row_with_reject_is_row_not_found() -> None:
    """rowNotFound 为 reject：返回 409 ROW_NOT_FOUND。"""
    bench = Bench(snapshot({SYNC: operation([{"action": "recalculate", "target": "source"}], row_not_found="reject")}))
    with pytest.raises(t.PlatformError) as caught:
        bench.run(command(SYNC, [(MATERIAL, "5001"), (MATERIAL, "5009")]))
    assert caught.value.code is t.ErrorCode.ROW_NOT_FOUND
    assert [(d.entity, d.row_key) for d in caught.value.details] == [(MATERIAL, "5009")]
    bench.close()
