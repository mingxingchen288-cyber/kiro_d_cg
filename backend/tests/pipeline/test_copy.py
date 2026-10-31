"""复制出的行写入复制的全部字段（C02 `copyOf`，WP-21）的模拟验证。

旧系统复制源行的全部字段（`copy-row-fields.ts` 第 23–29 行），新增行提交全部字段（`useWorkingSetStore.ts` 第 834–876 行），
后端插入只跳过虚拟列（`DynamicDataService.java` 第 274–327 行）。新平台的命令写明复制自哪一行，后端另读源行，
本行不可写的复制字段取源行的值。support 的成本单 1001：产品名称 GOODSNAME 不可编辑（不在可写字段中），
CREATE_BY 不可编辑、默认值为当前用户名。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeStage

from .support import MASTER, MATERIAL, TMP_1, TMP_2, Pipeline, Setup, command, master_none

D = Decimal
TMP_3 = "tmp-8c3a4e5f-2d6a-4b7c-8e9f-1a2b3c4d5e6f"


def copy_master(values: dict[str, str | None], copy_of: str | None = "1001") -> t.Command:
    master: dict[str, object] = {"op": "add", "clientRowId": TMP_1, "values": values}
    if copy_of is not None:
        master["copyOf"] = copy_of
    return command([{"entity": MASTER, "master": master, "details": []}])


def test_copied_master_takes_not_writable_fields_from_source() -> None:
    """复制成本单 1001：可写的备注、批量取命令中的值；不可写的产品名称、创建人取源行的值（命令中给的"伪造的名称"不用）；
    计算字段 TOTAL_COST 不写，由计算规则算；没复制的状态 USESTATUS 不补默认值，为空。源行只读一次。"""
    pipeline = Pipeline()
    cmd = copy_master({"GOODSNAME": "伪造的名称", "CREATE_BY": "李四", "MEMO": "复制", "APEX_PL": "100000", "TOTAL_COST": "1"})
    result = pipeline.execute(cmd, pipeline.setup.context())
    row = pipeline.store.rows[MASTER][result.id_map[TMP_1]]
    assert (row["GOODSNAME"], row["CREATE_BY"], row["MEMO"], row["APEX_PL"]) == ("250mg乙酰唑胺片", "王五", "复制", D(100000))
    assert row["TOTAL_COST"] is None and row["USESTATUS"] is None
    assert pipeline.store.copy_reads == 1  # type: ignore[attr-defined]


def test_not_copied_fields_are_left_empty() -> None:
    """WP-24（C05 v11 `copy: false`）：成本核算页把创建人 CREATE_BY（不可写）、批量 APEX_PL（可写）配成不复制。复制 1001：
    前端不复制这两列，批量写 null；这个页面是在改配置之前打开的，对话框里还勾着创建人，命令中带了源行的"王五"。
    新单据的创建人、批量都为空：创建人不取源行的值、不报错，批量不补默认值；产品名称照旧取源行的值，备注取命令中的值。"""
    pipeline = Pipeline(setup=Setup(not_copied={MASTER: ["CREATE_BY", "APEX_PL"]}))
    cmd = copy_master({"GOODSNAME": "250mg乙酰唑胺片", "CREATE_BY": "王五", "MEMO": "复制", "APEX_PL": None})
    result = pipeline.execute(cmd, pipeline.setup.context())
    row = pipeline.store.rows[MASTER][result.id_map[TMP_1]]
    assert (row["GOODSNAME"], row["MEMO"]) == ("250mg乙酰唑胺片", "复制")
    assert (row["CREATE_BY"], row["APEX_PL"]) == (None, None)
    [inserted] = [r for w in pipeline.store.writes if w.op == "insert" for r in w.rows]
    assert "CREATE_BY" not in inserted


def test_new_row_without_copy_of_still_rejects_not_writable_field() -> None:
    """不是复制出的行（没有 copyOf）：不可写的产品名称照旧 422 FIELD_NOT_WRITABLE，不读源行。"""
    pipeline = Pipeline()
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(copy_master({"GOODSNAME": "伪造的名称"}, copy_of=None), pipeline.setup.context())
    assert caught.value.code is t.ErrorCode.FIELD_NOT_WRITABLE
    assert not hasattr(pipeline.store, "copy_reads")


def test_source_outside_row_permission_is_not_found() -> None:
    """源行超出行权限（读不到）：409 ROW_NOT_FOUND，不写库。"""
    pipeline = Pipeline()
    pipeline.store.denied.add((MASTER, "1001"))
    with pytest.raises(t.PlatformError) as caught:
        pipeline.execute(copy_master({"GOODSNAME": "250mg乙酰唑胺片"}), pipeline.setup.context())
    assert caught.value.code is t.ErrorCode.ROW_NOT_FOUND
    assert pipeline.store.writes == []


def test_copied_detail_rows() -> None:
    """明细区复制 5001 到同一张单据：物料、用量、单价取命令中的值；只在视图中的物料名称、计算字段每批成本不写。"""
    pipeline = Pipeline()
    cmd = command([master_none("1001", [
        {"entity": MATERIAL, "op": "add", "clientRowId": TMP_2, "copyOf": "5001",
         "values": {"GOODSID": "115", "GOODSNAME": "硬脂酸镁", "USAGE": "2", "PRICE": "3.50", "COST_BATCH": "7", "MEMO": None}}])])
    result = pipeline.execute(cmd, pipeline.setup.context())
    [inserted] = [r for w in pipeline.store.writes if w.op == "insert" for r in w.rows]
    assert set(inserted) == {"DOCID", "GOODSID", "USAGE", "PRICE", "MEMO"}
    assert pipeline.store.rows[MATERIAL][result.id_map[TMP_2]]["PRICE"] == D("3.50")


def test_approved_copied_rows_are_written_as_resolved_without_defaults() -> None:
    """审批通过时写入复制出的行（approval AP-10）：复制 1001 成新单据 1003（送审时取得主键），明细复制 5001，另新增一行物料 116。
    approval 展开的意图中复制出的行带 `copy_of`，值是提交审批时按源行解出的：照写，不再读源行，没复制的状态、创建时间、
    批量、用量不补默认值，写入的列与直接保存时相同；不是复制的新增明细照常补默认值（用量、每批成本为 0，WP-16）。"""
    source = t.DocumentRef(MASTER, "1003")

    def process(uow, state: t.CommandState, ctx: t.ExecutionContext) -> None:  # type: ignore[no-untyped-def]
        state.approvals.append(t.ApprovalRef(approval_id="206", document=t.RecordRef(entity=MASTER, record_key="1003"),
                                             status="approved", level=1, flows=["COST_TO_GOODS"]))
        state.intents += [
            t.RowIntent(document=source, entity=MASTER, op="add", row_key="1003", client_row_id=TMP_1, copy_of="1001",
                        values={"GOODSNAME": "250mg乙酰唑胺片", "CREATE_BY": "王五", "MEMO": "复制"}),
            t.RowIntent(document=source, entity=MATERIAL, op="add", row_key="300001", client_row_id=TMP_2, copy_of="5001",
                        values={"GOODSID": D(115), "PRICE": D("3.50"), "DOCID": D(1003)}),
            t.RowIntent(document=source, entity=MATERIAL, op="add", row_key="300002", client_row_id=TMP_3,
                        values={"GOODSID": D(116), "PRICE": D("12"), "DOCID": D(1003)})]

    pipeline = Pipeline(extra=[FakeStage("审批处理", effect=process)])
    cmd = command([], page=None, operation="approval.pass", params={"approvalId": "206"})
    result = pipeline.execute(cmd, pipeline.setup.context(origin=t.Origin(kind="approval", approval_id="206")))
    assert result.outcome == "approvalProcessed"
    master, *details = [r for w in pipeline.store.writes if w.op == "insert" for r in w.rows]
    assert master == {"GOODSNAME": "250mg乙酰唑胺片", "CREATE_BY": "王五", "MEMO": "复制"}
    assert [set(r) for r in details] == [{"DOCID", "GOODSID", "PRICE"}, {"DOCID", "GOODSID", "PRICE", "USAGE", "COST_BATCH"}]
    row = pipeline.store.rows[MASTER]["1003"]
    assert (row["USESTATUS"], row["CREATE_TIME"], row["APEX_PL"]) == (None, None, None)
    assert (pipeline.store.rows[MATERIAL]["300002"]["USAGE"], pipeline.store.rows[MATERIAL]["300002"]["COST_BATCH"]) == (D(0), D(0))
    assert not hasattr(pipeline.store, "copy_reads")  # 不再读源行
