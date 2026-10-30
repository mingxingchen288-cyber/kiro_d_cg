"""审批的加锁顺序（用户 2026-10-30 同意"固定加锁层级"，规则 1–6，模拟验证）。

`FakeBusinessLocker` 按与 write-pipeline 真实实现相同的规则检查：一个事务中后加的锁必须排在已持有的锁之后，否则 500。
`LockLog` 另外记下每个命令（事务）新加的锁、加锁时所在的阶段，以及登记冻结时本事务已锁住的对象。只要每个命令都按同一个
全序加锁，就不可能互相等成环（不会死锁）；三方交叉的全部交错由 `.reports/concurrency-c04-20261030/model_check_v3.py`
穷举，在 d_cg 上的并发重放见 write-pipeline 的 `test_oracle_lock_order.py`。

数据（support.py）：成本单 2550、2556 含聚维酮K30（物料 25）；2551、2552 是三方交叉用的假设数据。审批流配置只在内存中：
COST_TO_GOODS（成本单改价冻结物料清单，往后找）、GOODS_TO_COST（物料清单改价冻结含这个物料的成本单，往前找）和假设的
X_COST_CROSS（成本单改了某个物料，冻结含这个物料的其他成本单，同层找）。
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from cost_platform.contracts import types as t

from .support import ADMIN, BUYER, MAKER, YANGNA, Harness, _dtl, cost, goods, modify
from .test_freeze import e37_save

D = Decimal
LockLine = tuple[str, str, str]

CROSS = t.ConfigDraft(type="approvalFlow", key="X_COST_CROSS", name="（假设）同物料成本单互相冻结", content={
    "page": "COST_PINGGU", "order": 9, "enabled": True, "operations": {"COST_MATERIAL": ["modify"]},
    "levels": [{"level": 1, "nodes": [{"name": "管理员审批", "conditionType": "always", "department": None,
                                        "approvers": [{"type": "role", "role": "ADMIN"}], "mode": "or", "enabled": True}]}],
    "freeze": [{"table": "T_COST_PINGGU_DTL", "condition": "GOODSID = :new_GOODSID", "enabled": True}],
    "display": [], "propagation": "end", "notify": []})


class LockLog:
    """记下每个命令新加的锁（按事务）和当时所在的阶段；登记冻结时记下本事务已锁住的对象。"""

    def __init__(self, h: Harness) -> None:
        self.events: list[tuple[int, str, list[t.LockTarget]]] = []
        self.freezes: list[tuple[set[tuple[str, str]], set[tuple[str, str]]]] = []
        self.phase = "加锁读取"
        locks, store = h.locks, h.store
        lock, freeze = locks.lock, store.freeze

        def logged_lock(uow: Any, ctx: t.ExecutionContext, targets: list[t.LockTarget],
                        expected: dict[t.DocumentRef, t.DocumentData] | None = None) -> None:
            new = sorted(set(targets) - locks.held(uow), key=t.LockTarget.order)
            lock(uow, ctx, targets, expected)
            if new:
                self.events.append((id(uow), self.phase, new))

        def logged_freeze(uow: Any, entries: list[t.FreezeEntry]) -> None:
            self.freezes.append(({(e.table.upper(), e.record_key) for e in entries},
                                 {(x.table, x.key) for x in locks.held(uow)}))
            freeze(uow, entries)

        locks.lock = logged_lock  # type: ignore[method-assign]
        store.freeze = logged_freeze  # type: ignore[method-assign]
        for name in ("resolve", "trigger_scope", "process", "trigger"):
            stage = getattr(h.approval, name)
            stage.run = self._in_phase(name, stage.run)

    def _in_phase(self, name: str, run: Callable[..., None]) -> Callable[..., None]:
        def wrapped(uow: Any, state: t.CommandState, ctx: t.ExecutionContext) -> None:
            self.phase = name
            try:
                run(uow, state, ctx)
            finally:
                self.phase = "加锁读取"
        return wrapped

    def commands(self) -> list[list[tuple[str, LockLine]]]:
        """每个命令新加的锁，按加锁的先后：（阶段，（层级、表、主键））。"""
        by_uow: dict[int, list[tuple[str, LockLine]]] = {}
        for uow, phase, targets in self.events:
            by_uow.setdefault(uow, []).extend((phase, (x.layer, x.table, x.key)) for x in targets)
        return list(by_uow.values())

    def in_order(self) -> bool:
        """每个命令都按统一顺序加锁：层级 → 表 → 主键（数值）。"""
        def key(line: LockLine) -> tuple[int, str, Any]:
            layer, table, value = line
            return t.LOCK_LAYERS.index(layer), table, D(value)  # type: ignore[arg-type]
        return all(all(key(a[1]) < key(b[1]) for a, b in zip(seq, seq[1:])) for seq in self.commands())

    def freezes_on_locked(self) -> bool:
        """冻结只登记在已经锁住的单据和行上（规则 6）。"""
        return all(entries <= held for entries, held in self.freezes)


# ---------------------------------------------------------------- 往后找：成本单改价冻结物料清单

@pytest.mark.parametrize("register_goods", [False, True], ids=["物料清单没注册", "物料清单注册为实体"])
def test_cost_to_goods_locks_cost_first_then_goods_before_freezing(register_goods: bool) -> None:
    """杨娜把 2550 的聚维酮K30 单价 75 改成 90（COST_TO_GOODS）：加锁读取先锁成本单 2550；触发审批算出要冻结物料清单 25，
    它排在成本单之后，冻结前再锁（规则 2），锁后才查冻结、登记。"""
    h = Harness(["COST_TO_GOODS"], register_goods=register_goods)
    log = LockLog(h)
    e37_save(h)
    assert log.commands() == [[("加锁读取", ("document", "T_COST_PINGGU", "2550")), ("trigger", ("base", "T_COST_GOODS", "25"))]]
    assert log.freezes_on_locked() and h.frozen() == {("T_COST_PINGGU", "2550"), ("T_COST_GOODS", "25")}


# ---------------------------------------------------------------- 往前找：物料清单改价冻结成本单

def test_goods_to_cost_finds_cost_documents_before_locking_and_locks_all_at_once() -> None:
    """杨娜把物料清单 25 的执行价改成 80（GOODS_TO_COST）：要冻结的成本单 2550、2556 排在物料清单之前，所以本单据推迟加锁
    （defer_lock），冻结的 SQL 在加锁前普通执行一次，再把 2550、2556 和物料清单 25 按顺序一次锁完（规则 3）。"""
    h = Harness(["GOODS_TO_COST"])
    log = LockLog(h)
    run = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")])
    assert run.state.defer_lock
    assert log.commands() == [[("trigger", ("document", "T_COST_PINGGU", "2550")), ("trigger", ("document", "T_COST_PINGGU", "2556")),
                               ("trigger", ("base", "T_COST_GOODS", "25"))]]
    assert log.freezes_on_locked()
    assert h.frozen() == {("T_COST_GOODS", "25"), ("T_COST_PINGGU", "2550"), ("T_COST_PINGGU", "2556")}


def test_goods_changed_between_read_and_lock_rolls_back_and_runs_again() -> None:
    """规则 4：冻结范围取决于物料清单 25 自己的数据；它在加锁前读取之后、加锁之前被别人改了（锁住后核对不一致），整个事务
    回滚（什么都没冻结、没有审批），用新的范围重来一次，第二次提交。只在这种情况下命令执行两遍。"""
    h = Harness(["GOODS_TO_COST"])

    def someone_saves_goods(_new: list[t.LockTarget]) -> None:
        h.world.tables["T_COST_GOODS"]["25"]["GOODSNAME"] = "聚维酮K30（别人刚改了名称）"

    h.locks.before_lock = someone_saves_goods
    with pytest.raises(t.LockScopeChanged):
        h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")])
    assert h.frozen() == set() and h.pipeline.executed == []
    h.locks.before_lock = None
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    assert len(h.pipeline.executed) == 1 and approval.document == t.RecordRef(entity="COST_GOODS_PRICE", record_key="25")


# ---------------------------------------------------------------- 三方交叉（假设）

def _cross_harness() -> Harness:
    h = Harness(["COST_TO_GOODS", "GOODS_TO_COST"], extra_flows=[CROSS])
    h.world.add_cost(2551, "说明用成本单甲", [_dtl(255101, 2551, 25, "75", "1"), _dtl(255102, 2551, 117, "13", "1")])
    h.world.add_cost(2552, "说明用成本单乙", [_dtl(255201, 2552, 116, "12", "1"), _dtl(255202, 2552, 117, "13", "1")])
    return h


def _outcome(fn: Callable[[], Any]) -> str:
    try:
        fn()
    except t.PlatformError as error:
        return error.code.value
    return "approvalSubmitted"


def test_three_way_cross_every_command_locks_in_the_unified_order() -> None:
    """假设的三方交叉（model_check_v3 场景三）：赵六改 2552 的二氧化硅（117）要冻结含 117 的成本单 2551、2552（同层找）；
    王五改物料清单 116 要冻结 2552（往前找）；张三改 2551 的聚维酮K30 单价要冻结物料清单 25（往后找）。每个命令都按同一顺序
    加锁，所以并发时不可能互相等成环；依次执行时赵六先冻结，另外两人被拒绝，与穷举结果中的一种结局相同。"""
    h = _cross_harness()
    log = LockLog(h)
    outcomes = [
        _outcome(lambda: h.save(MAKER, "COST_PINGGU", [cost(2552, modify("COST_MATERIAL", 255202, MEMO="赵六改"))])),
        _outcome(lambda: h.save(BUYER, "GOODS_PRICE_MANAGE", [goods(116, ZX_PRICE="14")])),
        _outcome(lambda: h.save(YANGNA, "COST_PINGGU", [cost(2551, modify("COST_MATERIAL", 255101, PRICE="80"))])),
    ]
    assert outcomes == ["approvalSubmitted", "FROZEN_BY_APPROVAL", "FROZEN_BY_APPROVAL"]
    commands = log.commands()
    assert [line for _, line in commands[0]] == [("document", "T_COST_PINGGU", "2551"), ("document", "T_COST_PINGGU", "2552")]
    assert [line for _, line in commands[1]] == [("document", "T_COST_PINGGU", "2552"), ("base", "T_COST_GOODS", "116")]
    assert ("document", "T_COST_PINGGU", "2551") in [line for _, line in commands[2]]
    assert log.in_order() and log.freezes_on_locked()


# ---------------------------------------------------------------- 审批最终通过：开头锁全

def test_final_pass_locks_approval_then_all_documents_to_write_at_the_start() -> None:
    """系统管理员最终通过物料清单 25 改价（GOODS_TO_COST）：在"确定涉及的单据"先锁审批记录，再把要写的成本单 2550、2556
    （提交时记下的受影响行所属的单据）和来源物料清单 25 一次锁完（规则 5）；审批处理和之后写入的轮次不再加锁。"""
    h = Harness(["GOODS_TO_COST"])
    [approval] = h.save(YANGNA, "GOODS_PRICE_MANAGE", [goods(25, ZX_PRICE="80")]).state.approvals
    log = LockLog(h)
    h.pass_(ADMIN, approval.approval_id)
    [locks] = log.commands()
    assert locks == [("resolve", ("approval", "PF_APPROVAL", approval.approval_id)),
                     ("resolve", ("document", "T_COST_PINGGU", "2550")), ("resolve", ("document", "T_COST_PINGGU", "2556")),
                     ("resolve", ("base", "T_COST_GOODS", "25"))]
    assert h.world.row("T_COST_GOODS", 25)["ZX_PRICE"] == 80 and h.frozen() == set()  # type: ignore[index]


def test_final_pass_unregistered_goods_row_locked_at_the_start() -> None:
    """COST_TO_GOODS 最终通过（物料清单没注册，经 TableWriter 写）：审批记录 → 成本单 2550 → T_COST_GOODS 的 25 这一行，
    都在"确定涉及的单据"锁住，写物料清单时不再追加。"""
    h = Harness(["COST_TO_GOODS"])
    approval = e37_save(h, "80")
    log = LockLog(h)
    h.pass_(ADMIN, approval.approval_id)
    [locks] = log.commands()
    assert [line for _, line in locks] == [("approval", "PF_APPROVAL", approval.approval_id),
                                           ("document", "T_COST_PINGGU", "2550"), ("base", "T_COST_GOODS", "25")]
    assert {phase for phase, _ in locks} == {"resolve"}
    assert h.world.table_writes == [("update", "T_COST_GOODS", "25", {"ZX_PRICE": D(80)})]
