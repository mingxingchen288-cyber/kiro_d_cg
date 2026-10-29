"""按钮操作的"确定涉及的单据"（OP-05、OP-08，C02 第 1 节）。"""

from __future__ import annotations

import pytest

from cost_platform.contracts import types as t

from .support import BOM, D, MASTER, MATERIAL, SYNC, Bench, button, command, operation, ref, snapshot

RECALC = [{"action": "recalculate", "target": "source"}]


def test_selected_master_row_is_the_document_and_actions_come_from_the_operation() -> None:
    """选中成本单 D 的主表行点按钮：D 是涉及的单据，动作为操作配置的通用动作。"""
    bench = Bench(snapshot({SYNC: operation(RECALC)}))
    state = bench.prepare(command(SYNC, [(MASTER, D)]))
    assert state.involved == [ref(D)]
    assert state.actions == operation(RECALC).actions
    assert ref(D) in state.current  # 加锁读到的是数据库中的当前数据
    bench.close()


def test_selected_detail_rows_belong_to_their_document() -> None:
    """选中 D 的两行原辅料明细：经 RelatedQuery 按明细主键找到所属的成本单 D，只算一张单据。"""
    bench = Bench(snapshot({SYNC: operation(RECALC)}))
    state = bench.prepare(command(SYNC, [(MATERIAL, "5002"), (MATERIAL, "5001")]))
    assert state.involved == [ref(D)]
    finder = bench.related.calls_to("find")[0].args[1]
    assert isinstance(finder, t.RelationKeyFinder) and finder.entity == MATERIAL and finder.target_key == "DTLID"
    bench.close()


def test_documents_in_a_button_command_is_invalid_request() -> None:
    """OP-08：按钮命令带了 documents 时返回 400 INVALID_REQUEST。"""
    bench = Bench(snapshot({SYNC: operation(RECALC)}))
    patch = {"entity": MASTER, "master": {"op": "modify", "rowKey": D, "changes": {"MEMO": "x"}}, "details": []}
    with pytest.raises(t.PlatformError) as caught:
        bench.prepare(command(SYNC, [(MASTER, D)], documents=[patch]))
    assert caught.value.code is t.ErrorCode.INVALID_REQUEST
    bench.close()


def test_requires_selection_without_selected_rows_is_validation_failed() -> None:
    """OP-05：按钮的 requiresSelection 为 true 而 selectedRows 为空时返回 422 VALIDATION_FAILED。"""
    bench = Bench(snapshot({SYNC: operation(RECALC)}, buttons=[button(SYNC, requires=True)]))
    with pytest.raises(t.PlatformError) as caught:
        bench.prepare(command(SYNC, []))
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    bench.close()


def test_button_without_requires_selection_runs_without_rows() -> None:
    """requiresSelection 为 false 的按钮（例如旧系统不看选中行的"同步采购价"）不选行也照常执行。"""
    bench = Bench(snapshot({SYNC: operation(RECALC)}, buttons=[button(SYNC, requires=False)]))
    state = bench.prepare(command(SYNC, []))
    assert state.involved == [] and state.actions == operation(RECALC).actions
    bench.close()


def test_escape_hatch_operation_on_a_button_becomes_one_escape_hatch_action() -> None:
    """按钮直接引用逃生舱操作（kind 为 escapeHatch）：动作为调用它的一个 escapeHatch。"""
    bom = operation([], kind="escapeHatch", procedure="P_COST_BOM_INSERT", writes={MATERIAL: ["GOODSID", "PRICE"]},
                    label="由BOM生成明细")
    bench = Bench(snapshot({BOM: bom}))
    state = bench.prepare(command(BOM, [(MASTER, D)]))
    assert state.involved == [ref(D)]
    assert state.actions == [t.EscapeHatch(action="escapeHatch", operation=BOM)]
    bench.close()
