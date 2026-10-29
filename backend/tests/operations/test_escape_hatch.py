"""逃生舱的登记和执行（OP-04，T-OP-2 的模拟验证）。

旧系统的三种执行器各有一个例子（cmx 中真实的按钮，`.reports/modules/operations/02-旧按钮配置.out.txt`）：
- 存储过程（旧 proc）：成本核算"由BOM生成明细"，P_COST_BOM_INSERT(data.id)；
- 语句（旧 sql）：汇率维护"同步ERP汇率"，UPDATE T_COST_FORMONEY SET FMRATE = NULL … WHERE CREATE_BY = 'system'；
- 处理函数（旧 java）：方法引用 `beanName.methodName`。

替代数据库是内存 SQLite，没有存储过程：存储过程由测试里的 `RecordingRunner` 代替，它在命令事务的连接上写一行，
用来检查写入随命令一起提交或回滚。Oracle 上调用真实存储过程见 `test_escape_hatch_oracle.py`（需要 d_cg）。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest
from sqlalchemy import text

from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeRelatedQuery
from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import Value
from cost_platform.operations import (
    ActionStage,
    BoundArg,
    EscapeHatchInvocation,
    EscapeHatchRegistration,
    EscapeHatchRegistry,
    EscapeParam,
    HandlerCall,
    ProcedureCall,
    SqlEscapeHatchRunner,
    StatementCall,
)

from .support import BOM, D, KEY, MASTER, MATERIAL, NOW, SYNC, Bench, button, command, operation, snapshot

LOG_TABLE = "CREATE TABLE PF_TEST_ESCAPE_LOG (DOCID NUMBER, NOTE TEXT)"
BOM_OPERATION = operation([], kind="escapeHatch", procedure="P_COST_BOM_INSERT", label="由BOM生成明细",
                          writes={MASTER: ["TOTAL_COST"], MATERIAL: ["GOODSID", "PRICE"]})
BOM_CALL = ProcedureCall("P_COST_BOM_INSERT", (EscapeParam("P_DOCID", "document.recordKey", "number"),
                                               EscapeParam("P_MESSAGE", mode="OUT", prompt=True)))


class RecordingRunner(SqlEscapeHatchRunner):
    """代替存储过程：记下每次调用，在命令事务的连接上往 PF_TEST_ESCAPE_LOG 写一行；语句照常执行。"""

    def __init__(self, outputs: dict[str, Value] | None = None) -> None:
        self.calls: list[tuple[UnitOfWork, str, list[BoundArg]]] = []
        self.outputs = outputs or {}

    def call_procedure(self, uow: UnitOfWork, call: ProcedureCall, args: Sequence[BoundArg]) -> dict[str, Value]:
        self.calls.append((uow, call.procedure, list(args)))
        docid = next((a.value for a in args if a.name == "P_DOCID"), None)
        uow.connection.execute(text("INSERT INTO PF_TEST_ESCAPE_LOG (DOCID, NOTE) VALUES (:d, :n)"),
                               {"d": str(docid), "n": call.procedure})
        return dict(self.outputs)


def bench_with(registrations: Sequence[EscapeHatchRegistration], operations: dict[str, t.OperationConfig],
               runner: RecordingRunner, setup: Sequence[str] = (LOG_TABLE,),
               buttons: Sequence[t.ViewButton] | None = None) -> Bench:
    related = FakeRelatedQuery()
    stage = ActionStage(related, EscapeHatchRegistry(registrations), runner)
    return Bench(snapshot(operations, buttons), related=related, stage=stage, setup_sql=setup)


def logged(bench: Bench) -> list[tuple[object, ...]]:
    with bench.factory.engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text("SELECT DOCID, NOTE FROM PF_TEST_ESCAPE_LOG"))]


def test_registered_procedure_runs_in_the_command_transaction_and_is_audited() -> None:
    """选中成本单 D 点"由BOM生成明细"：调用登记的 P_COST_BOM_INSERT(D)，用的是命令的事务，自身不提交；
    `state.escape_hatch_calls` 记下逃生舱、参数、执行人、时间和请求键；OUT 参数的提示随命令结果返回。命令提交后写入保留。"""
    runner = RecordingRunner({"P_MESSAGE": "已按 BOM 生成 12 行明细"})
    bench = bench_with([EscapeHatchRegistration(BOM, BOM_CALL)], {BOM: BOM_OPERATION}, runner)
    state = bench.run(command(BOM, [(MASTER, D)]))
    (uow, procedure, args), = runner.calls
    assert uow is bench.uow and procedure == "P_COST_BOM_INSERT"
    assert [(a.name, a.mode, a.value) for a in args] == [("P_DOCID", "IN", Decimal(2550)), ("P_MESSAGE", "OUT", None)]
    assert bench.factory.calls_to("commit") == []
    assert state.prompts == [t.Prompt(rule=BOM, message="已按 BOM 生成 12 行明细")]
    call, = state.escape_hatch_calls  # 写命令记录的 JSON，由 write-pipeline 随命令记录写入
    assert call == {
        "operation": BOM, "kind": "procedure", "target": "P_COST_BOM_INSERT", "params": {"P_DOCID": "2550"},
        "outputs": {"P_MESSAGE": "已按 BOM 生成 12 行明细"}, "writes": {MASTER: ["TOTAL_COST"], MATERIAL: ["GOODSID", "PRICE"]},
        "userId": "112", "userName": "张三", "at": NOW.strftime("%Y-%m-%dT%H:%M:%S"), "requestKey": KEY, "approvalId": None}
    bench.uow.commit()
    bench.close()
    assert logged(bench) == [(Decimal(2550), "P_COST_BOM_INSERT")]


def test_escape_hatch_writes_roll_back_when_a_later_action_fails() -> None:
    """逃生舱之后的动作失败：命令事务回滚，逃生舱的写入一起撤销（T-OP-2 验收标准，模拟）。"""
    later = "COST_PINGGU.bomThenFail"
    actions = [{"action": "escapeHatch", "operation": BOM}, {"action": "escapeHatch", "operation": "COST_PINGGU.notEnabled"}]
    operations = {later: operation(actions), BOM: BOM_OPERATION,
                  "COST_PINGGU.notEnabled": operation([], kind="escapeHatch", procedure="P_OTHER")}
    runner = RecordingRunner()
    bench = bench_with([EscapeHatchRegistration(BOM, BOM_CALL)], operations, runner)
    with pytest.raises(t.PlatformError):
        bench.run(command(later, [(MASTER, D)]))
    assert len(runner.calls) == 1
    bench.close()  # 没有提交就退出：回滚
    assert logged(bench) == []


def test_escape_hatch_not_registered_is_refused() -> None:
    """只在用户点名时启用：配置中有逃生舱操作、但没有登记启用时拒绝执行，什么都不调用。"""
    runner = RecordingRunner()
    bench = bench_with([], {BOM: BOM_OPERATION}, runner)
    with pytest.raises(t.PlatformError) as caught:
        bench.run(command(BOM, [(MASTER, D)]))
    assert caught.value.code is t.ErrorCode.VALIDATION_FAILED
    assert "点名" in caught.value.message and runner.calls == []
    bench.close()


def test_registered_statement_like_old_sql_action() -> None:
    """旧 sql 执行器对应登记的语句："同步ERP汇率"不看选中行，把系统生成的汇率清空；参数用绑定变量。"""
    code = "FORMONEY_MANAGE.syncErpRate"
    setup = ["CREATE TABLE T_COST_FORMONEY (ID NUMBER, FMRATE NUMBER, CREATE_BY TEXT)",
             "INSERT INTO T_COST_FORMONEY VALUES (1, 7.1, 'system')", "INSERT INTO T_COST_FORMONEY VALUES (2, 7.2, '张三')"]
    call = StatementCall("清空系统汇率", "UPDATE T_COST_FORMONEY SET FMRATE = NULL WHERE CREATE_BY = :createBy",
                         (EscapeParam("createBy", "constant", value="system"),))
    runner = RecordingRunner()
    bench = bench_with([EscapeHatchRegistration(code, call)], {code: operation([], kind="escapeHatch", label="同步ERP汇率")},
                       runner, setup=setup, buttons=[button(code, requires=False)])
    state = bench.run(command(code, []))
    rates = bench.uow.connection.execute(text("SELECT ID, FMRATE FROM T_COST_FORMONEY ORDER BY ID")).all()  # 同一事务中读
    assert [(r[0], r[1]) for r in rates] == [(Decimal(1), None), (Decimal(2), Decimal("7.2"))]
    assert [(c["kind"], c["target"], c["params"]) for c in state.escape_hatch_calls] == \
        [("statement", "清空系统汇率", {"createBy": "system"})]
    bench.close()


def test_registered_handler_like_old_java_action_runs_once_per_selected_row() -> None:
    """旧 java 执行器对应登记的处理函数；参数取选中行时，每个选中的行调用一次，按选中的先后。"""
    seen: list[dict[str, Value]] = []

    def handler(invocation: EscapeHatchInvocation) -> dict[str, Value]:
        seen.append(invocation.params)
        return {"P_MESSAGE": f"已处理 {invocation.params['DTLID']}"}

    code = "COST_PINGGU.markRows"
    call = HandlerCall("标记明细", handler, (EscapeParam("DTLID", "row.rowKey", "number"),
                                         EscapeParam("GOODSID", "row.GOODSID", "number"),
                                         EscapeParam("USER_ID", "context.userId"),
                                         EscapeParam("P_MESSAGE", mode="OUT", prompt=True)))
    bench = bench_with([EscapeHatchRegistration(code, call)], {code: operation([], kind="escapeHatch", label="标记")},
                       RecordingRunner())
    state = bench.run(command(code, [(MATERIAL, "5002"), (MATERIAL, "5001")]))
    assert seen == [{"DTLID": Decimal(5002), "GOODSID": Decimal(116), "USER_ID": "112"},
                    {"DTLID": Decimal(5001), "GOODSID": Decimal(115), "USER_ID": "112"}]
    assert [p.message for p in state.prompts] == ["已处理 5002", "已处理 5001"]
    bench.close()


def test_escape_hatch_inside_an_action_operation() -> None:
    """按钮操作的通用动作中引用逃生舱：排到这个动作时执行，前后的动作照常展开。"""
    actions = [{"action": "escapeHatch", "operation": BOM}, {"action": "recalculate", "target": "source"}]
    runner = RecordingRunner()
    bench = bench_with([EscapeHatchRegistration(BOM, BOM_CALL)], {SYNC: operation(actions), BOM: BOM_OPERATION}, runner)
    bench.run(command(SYNC, [(MASTER, D)]))
    assert len(runner.calls) == 1
    assert [(i.document.record_key, i.values) for i in bench.merged] == [(D, {})]
    bench.close()
