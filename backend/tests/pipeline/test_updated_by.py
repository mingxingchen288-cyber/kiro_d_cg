"""写入修改人（WP-20，C06 第 2 节 `updatedByColumn`）的模拟验证。

旧系统 DynamicDataService.java 的 insert、update 每次写 UPDATE_BY = 当前用户名（SecurityUtils.getCurrentUsername，
登录名）；物料清单视图 T_COST_GOODS_PRICE_V 按它判断 ERP 行"已被修改"（黄底）。这里给物料实体（support 的 COST_GOODS）
配上 `updatedByColumn: UPDATE_BY`：
- 改本地物料 116 的执行价：同一条 UPDATE 另写修改人为当前用户的登录名（user112），命令结果中没有它；
- 新增物料：INSERT 同样带修改人；
- 没配的实体（成本单主表）不写修改人；
- 来源为审批的写入（审批通过）写执行它的审批人的登录名。
"""

from __future__ import annotations

import json

import pytest

from cost_platform.contracts import types as t
from cost_platform.pipeline.writer import UPDATED_BY

from . import support
from .support import GOODS, GOODS_PAGE, GOODS_SAVE, TMP_1, MemoryStore, Pipeline, command, master_modify


class TableStore(MemoryStore):
    """写入时实体换成了带修改人字段的副本，按表找实体编码。"""

    def _code(self, entity: t.EntityConfig) -> str:
        return next(code for code, e in support.ENTITIES.items() if e.table == entity.table)


@pytest.fixture(autouse=True)
def goods_with_updated_by(monkeypatch: pytest.MonkeyPatch) -> None:
    entity = support.GOODS_ENTITY.model_copy(update={"updated_by_column": "UPDATE_BY"})
    monkeypatch.setitem(support.ENTITIES, GOODS, entity)


def _writes(pipeline: Pipeline, op: str, entity: str) -> list[dict[str, object]]:
    return [r for w in pipeline.store.writes if w.op == op and w.entity == entity for r in w.rows]


def test_modify_writes_updated_by_in_same_statement() -> None:
    pipeline = Pipeline(store=TableStore())
    result = pipeline.execute(command([master_modify("116", {"ZX_PRICE": "48"}, entity=GOODS)], page=GOODS_PAGE,
                                      operation=GOODS_SAVE), pipeline.setup.context())
    assert result.outcome == "saved"
    [write] = [w for w in pipeline.store.writes if w.op == "update"]
    assert write.rows == [{"rowKey": "116", "ZX_PRICE": 48, UPDATED_BY: "user112"}]
    [row] = [r for r in result.rows if isinstance(r, t.ResultRow)]
    assert UPDATED_BY not in row.values and "UPDATE_BY" not in row.values
    assert UPDATED_BY not in json.dumps(support.command_rows(pipeline.factory)[0]["result"], ensure_ascii=False)


def test_insert_writes_updated_by() -> None:
    pipeline = Pipeline(store=TableStore())
    cmd = command([{"entity": GOODS, "master": {"op": "add", "clientRowId": TMP_1, "values": {"NAME": "新物料", "ZX_PRICE": "3"}},
                    "details": []}], page=GOODS_PAGE, operation=GOODS_SAVE)
    result = pipeline.execute(cmd, pipeline.setup.context())
    [inserted] = _writes(pipeline, "insert", GOODS)
    assert inserted[UPDATED_BY] == "user112"
    assert pipeline.store.rows[GOODS][result.id_map[TMP_1]][UPDATED_BY] == "user112"


def test_entity_without_updated_by_column_is_unchanged() -> None:
    pipeline = Pipeline(store=TableStore())
    pipeline.execute(command([master_modify("1002", {"MEMO": "新备注"})]), pipeline.setup.context())
    assert _writes(pipeline, "update", support.MASTER) == [{"rowKey": "1002", "MEMO": "新备注"}]


def test_approval_write_uses_approver_username() -> None:
    """审批通过时的写入（来源为审批，意图由 approval 展开）：修改人为执行它的审批人（旧系统审批通过在审批人的请求中
    调 DynamicDataService.saveInternal，UPDATE_BY 为审批人的用户名）。"""
    ref = t.DocumentRef(GOODS, "115")

    def approve(state: t.CommandState, ctx: t.ExecutionContext) -> None:
        state.involved.append(ref)
        state.intents.append(t.RowIntent(document=ref, entity=GOODS, op="modify", row_key="115", client_row_id=None,
                                         values={"ZX_PRICE": "80"}))

    pipeline = Pipeline(store=TableStore(), actions=[approve])
    ctx = pipeline.setup.context("1", "管理员", origin=t.Origin(kind="approval", approval_id="203"))
    result = pipeline.execute(command([], page=None, operation="approval.pass", params={"approvalId": "203"}), ctx)
    assert result.outcome == "saved"
    assert _writes(pipeline, "update", GOODS) == [{"rowKey": "115", "ZX_PRICE": 80, UPDATED_BY: "user1"}]
