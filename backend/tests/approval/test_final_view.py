"""已结束的审批显示结束那一刻的修改前、修改后（C06 7.6"已结束的审批"、C09 第 6 节）。

业务场景同 d_cg 的审批 13、14：成本单 2550 的聚维酮K30（明细 206323）单价 75 改成 80，通过；再改回 75，通过。以后数据怎么变，
前一个审批的详情都显示 75.00 → 80.00，后一个显示 80.00 → 75.00。驳回、撤回的审批同样显示结束时的值。
结束时没有保存的（迁移 ap_0002 之前结束的）：已通过的按提交、通过两条命令的记录还原（迁移 ap_0003），撤回的写明没有保存。
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa

from cost_platform.approval.restore import restore_final_views
from cost_platform.approval.tables import pf_approval
from cost_platform.contracts import types as t
from cost_platform.contracts.values import to_wire

from .support import ADMIN, YANGNA, Harness, cost, modify


def cells(row: t.ViewRow) -> list[tuple[object, object]]:
    return [(c.before, c.after) for c in row.cells]


def save_price(h: Harness, price: str) -> str:
    [approval] = h.save(YANGNA, "COST_PINGGU", [cost(2550, modify("COST_MATERIAL", 206323, PRICE=price))]).state.approvals
    return approval.approval_id


def material_and_goods(detail: t.ApprovalDetail) -> tuple[list[tuple[object, object]], list[tuple[object, object]]]:
    [material] = [d for d in detail.view.details if d.key == "material"]
    [goods_block] = detail.view.affected
    return cells(material.rows[0]), cells(goods_block.rows[0])


def test_passed_approvals_keep_values_at_end() -> None:
    h = Harness(["COST_TO_GOODS"])
    first = save_price(h, "80")
    h.pass_(ADMIN, first)
    second = save_price(h, "75")
    h.pass_(ADMIN, second)
    assert h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] == 75  # type: ignore[index]

    detail = h.detail(ADMIN, first)
    assert (detail.status, detail.view_unsaved) == ("approved", None)
    assert material_and_goods(detail) == ([("25", "25"), ("聚维酮K30", "聚维酮K30"), ("75.00", "80.00"), ("750.00", "800.00")],
                                          [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("75.00", "80.00")])
    assert material_and_goods(h.detail(ADMIN, second)) == (
        [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("80.00", "75.00"), ("800.00", "750.00")],
        [("25", "25"), ("聚维酮K30", "聚维酮K30"), ("80.00", "75.00")])
    assert detail.actions == t.ApprovalActions(can_pass=False, can_reject=False, can_withdraw=False)


def test_rejected_and_withdrawn_keep_values_at_end() -> None:
    h = Harness(["COST_TO_GOODS"])
    rejected = save_price(h, "80")
    h.reject(ADMIN, rejected, "价格偏高")
    withdrawn = save_price(h, "81")
    h.withdraw(YANGNA, withdrawn)
    h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] = 70  # type: ignore[index]  # 结束后数据又变了

    assert material_and_goods(h.detail(ADMIN, rejected))[0][2:] == [("75.00", "80.00"), ("750.00", "800.00")]
    assert material_and_goods(h.detail(YANGNA, withdrawn))[0][2:] == [("75.00", "81.00"), ("750.00", "810.00")]
    assert h.detail(ADMIN, withdrawn).status == "withdrawn"


# ---------------------------------------------------------------- 结束时没有保存的（迁移 ap_0003）

_command = sa.Table("pf_command", sa.MetaData(), sa.Column("operation", sa.String), sa.Column("result", sa.Text),
                    sa.Column("audit_diff", sa.Text), sa.Column("created_at", sa.DateTime))
_config_item = sa.Table("pf_config_item", sa.MetaData(), sa.Column("config_type", sa.String), sa.Column("config_key", sa.String),
                        sa.Column("content", sa.Text))


def _row(h: Harness, entity: str, key: str, frozen: str | None) -> dict[str, Any]:
    """命令结果中的一行（C02 的 `rows`）：取 World 中这一行的当前值。"""
    ref = t.DocumentRef("COST_PINGGU", "2550")
    doc = h.world.load(ref)
    assert doc is not None
    row = doc.master if entity == "COST_PINGGU" else next(r for r in doc.details[entity] if r.row_key == key)
    types = {f.name: f.type for f in h.config.entities[entity].fields}
    values = {k: to_wire(types[k], v) for k, v in row.values.items() if k in types}
    return {"entity": entity, "rowKey": key, "values": values, "frozen": {"approvalId": frozen} if frozen else None}


def _command_row(operation: str, outcome: str, approval_id: str, status: str, rows: list[dict[str, Any]],
                 audit: list[dict[str, Any]], at: Any) -> dict[str, Any]:
    result = {"requestKey": "x", "outcome": outcome, "rows": rows, "idMap": {}, "prompts": [], "skipped": [],
              "approvals": [{"approvalId": approval_id, "document": {"entity": "COST_PINGGU", "recordKey": "2550"},
                             "status": status, "level": 1, "flows": ["COST_TO_GOODS"]}]}
    return {"operation": operation, "result": json.dumps(result, ensure_ascii=False), "audit_diff": json.dumps(audit),
            "created_at": at}


def _forget_final_view(h: Harness, approval_id: str) -> t.ApprovalView:
    """模拟 ap_0002 之前结束的审批：清掉结束时存下的修改内容，返回清掉之前的。"""
    saved = h.record(approval_id).final_view
    assert saved is not None
    with h.uow.begin() as uow:
        uow.connection.execute(sa.update(pf_approval).where(pf_approval.c.approval_id == int(approval_id)).values(final_view=None))
        uow.commit()
    return saved  # type: ignore[no-any-return]


def test_restore_passed_approval_from_commands_and_unsaved_withdrawn() -> None:
    """已通过的：修改前取提交命令返回的行（带本审批的冻结标记），修改后取通过命令返回的行，物料清单的修改后取通过命令的审计；
    还原出的修改内容与结束时存下的相同，之后数据再变也不影响。撤回的结束时没有算修改后，还原不了，详情写明没有保存。"""
    h = Harness(["COST_TO_GOODS"])
    _command.create(h.uow.engine)
    _config_item.create(h.uow.engine)
    passed = save_price(h, "80")
    submitted = [_row(h, "COST_MATERIAL", "206323", passed), _row(h, "COST_PINGGU", "2550", passed)]
    h.pass_(ADMIN, passed)
    written = [_row(h, "COST_MATERIAL", "206323", None), _row(h, "COST_PINGGU", "2550", None)]
    withdrawn = save_price(h, "81")
    h.withdraw(YANGNA, withdrawn)
    expected = _forget_final_view(h, passed)
    _forget_final_view(h, withdrawn)
    h.world.row("T_COST_PINGGU_DTL", 206323)["PRICE"] = 70  # type: ignore[index]

    record = h.record(passed)
    audit = [{"entity": "T_COST_GOODS", "rowKey": "25", "op": "modify", "fields": {"ZX_PRICE": {"old": None, "new": "80"}}}]
    with h.uow.begin() as uow:
        conn = uow.connection
        conn.execute(sa.insert(_command), [
            _command_row("COST_PINGGU.save", "approvalSubmitted", passed, "pending", submitted, [], record.submitted_at),
            _command_row("approval.pass", "approvalProcessed", passed, "approved", written, audit, record.finished_at)])
        conn.execute(sa.insert(_config_item), [{"config_type": "entity", "config_key": code,
                                                 "content": json.dumps(t.dump_wire(t.EntityConfig, e), ensure_ascii=False)}
                                                for code, e in h.config.entities.items()])
        assert restore_final_views(conn) == [(passed, True), (withdrawn, False)]
        uow.commit()

    detail = h.detail(ADMIN, passed)
    assert detail.view == expected and detail.view_unsaved is None
    assert material_and_goods(detail)[0][2:] == [("75.00", "80.00"), ("750.00", "800.00")]
    unsaved = h.detail(ADMIN, withdrawn)
    assert unsaved.view_unsaved is True
    assert (unsaved.view.master.rows, unsaved.view.details, unsaved.view.affected) == ([], [], [])
