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

from .support import MASTER, MATERIAL, TMP_1, TMP_2, Pipeline, command, master_none

D = Decimal


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
