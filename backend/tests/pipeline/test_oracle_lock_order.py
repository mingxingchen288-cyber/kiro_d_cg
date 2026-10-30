"""固定加锁层级的真实验证（d_cg，用户 2026-10-30）：几个数据库连接同时执行命令，用钩子停在"加锁前""冻结前""查冻结前"，
按 `.reports/concurrency-c04-20261030/*.out.txt` 中的例子重放交错顺序。组装、测试表和数据见 `lock_order_support.py`。

要求：不出现 ORA-00060（死锁）；冻结生效后没有别人的修改提交成功；每条命令只执行一遍（规则 4 的例外场景除外）。
每个场景的结局记日志（`-o log_cli=true --log-cli-level=INFO` 可以看到）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from cost_platform.contracts import types as t
from cost_platform.pipeline.tracing import SqlTracer

from .lock_order_support import (
    CLEANUP,
    COST_PAGE,
    COST_PAGE2,
    DDL,
    DROP,
    FROZEN,
    GOODS_PAGE,
    LI,
    PAUSE,
    ROWS,
    TABLE_DOC,
    TABLE_DTL,
    TABLE_GOODS,
    WANG,
    ZHANG,
    ZHAO,
    Platform,
    cost,
    dtl,
    execute,
    fetch,
    frozen,
    goods,
    row_is_free,
    save,
)

pytestmark = pytest.mark.oracle
_log = logging.getLogger(__name__)
_tracer = SqlTracer()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    from cost_platform.assembly.settings import Settings
    from cost_platform.db_core.engine import create_oracle_engine

    settings = Settings.load()
    found = create_oracle_engine(settings.db_user, settings.db_password, settings.db_dsn)
    execute(found, DROP, ignore_errors=True)  # 上次中断时留下的
    execute(found, DDL)
    yield found
    execute(found, CLEANUP)
    execute(found, DROP, ignore_errors=True)
    found.dispose()


@pytest.fixture
def platform(engine: Engine) -> Iterator[Platform]:
    execute(engine, [*CLEANUP, f"DELETE FROM {TABLE_DTL}", f"DELETE FROM {TABLE_DOC}", f"DELETE FROM {TABLE_GOODS}", *ROWS])
    found = Platform(engine)
    yield found
    for worker in found.workers:
        worker.join(30)
    execute(engine, CLEANUP)


def _memo(engine: Engine, docid: int) -> str | None:
    return fetch(engine, f"SELECT MEMO FROM {TABLE_DOC} WHERE DOCID = :k", k=docid)[0]["memo"]


def _probe(p: Platform, docid: int) -> str:
    """冻结生效后，李四再改一次这张成本单的备注：必须被拒绝。"""
    return p.run(LI, save(COST_PAGE, [cost(docid, master={"MEMO": "冻结后再改"})])).outcome


# ---------------------------------------------------------------- (a) 冻结别的单据时，有人同时保存那张单据（场景一）

def test_a1_other_save_commits_before_the_freezing_command_locks(platform: Platform) -> None:
    """王五改物料 3 的执行价（要冻结含 3 的成本单 2551）：用普通查询找出 2551 后、加锁前停下；李四这时保存 2551 的备注，
    直接成功（冻结还没有）。王五继续：按顺序锁 2551、物料 3，冻结后提交。之后李四再改 2551 被拒绝。"""
    p = platform
    gate = p.gates.hold(WANG, "加锁前")
    wang = p.start(WANG, save(GOODS_PAGE, [goods(3, ZX_PRICE="31")]))
    gate.wait()
    li = p.run(LI, save(COST_PAGE, [cost(2551, master={"MEMO": "李四改"})]))
    gate.release()
    wang.join(60)
    _log.info("a1：%s；%s", li.summary(), wang.summary())
    assert (li.outcome, wang.outcome) == ("saved", "approvalSubmitted")
    assert frozen(p.engine) == {(TABLE_GOODS, "3"), (TABLE_DOC, "2551")}
    assert _probe(p, 2551) == FROZEN and _memo(p.engine, 2551) == "李四改"
    assert p.problems() == []


def test_a2_freezing_command_waits_for_the_other_save_without_holding_goods(platform: Platform) -> None:
    """李四保存 2551：锁住 2551 后、查冻结前停下。王五改物料 3：找出 2551 后按顺序先锁 2551，等李四；等的时候物料 3 没有被
    王五锁住（旧的做法王五先锁了物料 3）。李四继续，查冻结（没有）、提交；王五拿到 2551、再锁物料 3，冻结后提交。"""
    p = platform
    gate = p.gates.hold(LI, "查冻结前")
    li = p.start(LI, save(COST_PAGE, [cost(2551, master={"MEMO": "李四改"})]))
    gate.wait()
    wang = p.start(WANG, save(GOODS_PAGE, [goods(3, ZX_PRICE="31")]))
    time.sleep(PAUSE)
    assert wang.is_alive() and row_is_free(p.engine, TABLE_GOODS, "GOODSID", 3)
    gate.release()
    li.join(60)
    wang.join(60)
    _log.info("a2：%s；%s", li.summary(), wang.summary())
    assert (li.outcome, wang.outcome) == ("saved", "approvalSubmitted") and wang.seconds >= PAUSE
    assert _probe(p, 2551) == FROZEN and _memo(p.engine, 2551) == "李四改"
    assert p.problems() == []


def test_a3_save_waiting_on_the_lock_sees_the_freeze_committed_meanwhile(platform: Platform) -> None:
    """王五锁住 2551 和物料 3 后、登记冻结前停下；李四保存 2551，等 2551 的锁。王五登记冻结并提交后，李四拿到锁，
    锁后单独一条语句查冻结（规则 6），看到刚提交的冻结，被拒绝；2551 的备注不变。"""
    p = platform
    gate = p.gates.hold(WANG, "冻结前")
    wang = p.start(WANG, save(GOODS_PAGE, [goods(3, ZX_PRICE="31")]))
    gate.wait()
    li = p.start(LI, save(COST_PAGE, [cost(2551, master={"MEMO": "李四改"})]))
    time.sleep(PAUSE)
    assert li.is_alive()
    gate.release()
    wang.join(60)
    li.join(60)
    _log.info("a3：%s；%s", wang.summary(), li.summary())
    assert (wang.outcome, li.outcome) == ("approvalSubmitted", FROZEN) and li.seconds >= PAUSE
    assert _memo(p.engine, 2551) is None
    assert p.problems() == []


# ---------------------------------------------------------------- (b) 成本单改价和物料清单改价同时进审批（场景二）

def test_b1_the_old_deadlock_order_now_only_waits(platform: Platform) -> None:
    """model_check_v2 场景二的死锁例子：张三改 2551 的单价（要冻结物料 3），已锁住 2551、要锁物料 3 时停下；王五改物料 3 的
    执行价（要冻结 2551）。旧的做法王五先锁物料 3、再等 2551，两人互相等，Oracle 报 ORA-00060。现在王五先锁 2551、等张三，
    物料 3 没有被他锁住；张三锁住物料 3、冻结后提交，王五拿到锁后发现物料 3 已被张三的审批冻结，被拒绝。"""
    p = platform
    gate = p.gates.hold(ZHANG, "加锁前")
    zhang = p.start(ZHANG, save(COST_PAGE, [cost(2551, dtl(255101, PRICE="31"))]))
    gate.wait()
    wang = p.start(WANG, save(GOODS_PAGE, [goods(3, ZX_PRICE="32")]))
    time.sleep(PAUSE)
    assert wang.is_alive() and row_is_free(p.engine, TABLE_GOODS, "GOODSID", 3)
    gate.release()
    zhang.join(60)
    wang.join(60)
    _log.info("b1：%s；%s", zhang.summary(), wang.summary())
    assert (zhang.outcome, wang.outcome) == ("approvalSubmitted", FROZEN)
    assert frozen(p.engine) == {(TABLE_DOC, "2551"), (TABLE_GOODS, "3")}
    assert p.problems() == []


def test_b2_goods_command_paused_before_lock_finds_its_goods_frozen(platform: Platform) -> None:
    """王五找出 2551 后、加锁前停下；张三改 2551 的单价，锁 2551、再锁物料 3，冻结后提交。王五继续，锁住后核对物料 3 没变，
    查冻结时物料 3 已被张三的审批冻结，被拒绝。"""
    p = platform
    gate = p.gates.hold(WANG, "加锁前")
    wang = p.start(WANG, save(GOODS_PAGE, [goods(3, ZX_PRICE="32")]))
    gate.wait()
    zhang = p.run(ZHANG, save(COST_PAGE, [cost(2551, dtl(255101, PRICE="31"))]))
    gate.release()
    wang.join(60)
    _log.info("b2：%s；%s", zhang.summary(), wang.summary())
    assert (zhang.outcome, wang.outcome) == ("approvalSubmitted", FROZEN)
    assert p.problems() == []


def test_b3_cost_command_waits_and_finds_its_document_frozen(platform: Platform) -> None:
    """王五锁住 2551 和物料 3 后、登记冻结前停下；张三改 2551 的单价，加锁读取等 2551。王五冻结后提交，张三拿到锁，
    冻结检查看到 2551 已被王五的审批冻结，被拒绝。"""
    p = platform
    gate = p.gates.hold(WANG, "冻结前")
    wang = p.start(WANG, save(GOODS_PAGE, [goods(3, ZX_PRICE="32")]))
    gate.wait()
    zhang = p.start(ZHANG, save(COST_PAGE, [cost(2551, dtl(255101, PRICE="31"))]))
    time.sleep(PAUSE)
    assert zhang.is_alive()
    gate.release()
    wang.join(60)
    zhang.join(60)
    _log.info("b3：%s；%s", wang.summary(), zhang.summary())
    assert (wang.outcome, zhang.outcome) == ("approvalSubmitted", FROZEN)
    assert fetch(p.engine, f"SELECT PRICE FROM {TABLE_DTL} WHERE DTLID = 255101")[0]["price"] == 30
    assert p.problems() == []


# ---------------------------------------------------------------- (c) 三方交叉（假设，场景三）

def test_c_three_way_cross_without_deadlock(platform: Platform) -> None:
    """model_check_v2 场景三的死锁例子：张三把 2551 的一行换成物料 1（冻结物料 1，往后找）；王五改物料 1 的执行价（冻结含 1
    的 2552，往前找）；赵六在 PF_COST_PAGE2 改 2552 物料 2 那一行（冻结含 2 的 2551、2552，同层找）。三人都停在加锁前：
    张三已锁住 2551，王五、赵六还什么都没锁。先放赵六，他按顺序先锁 2551、等张三；再放王五，锁 2552、物料 1，冻结后提交；
    最后放张三，物料 1 已被王五冻结，被拒绝，放开 2551；赵六拿到 2551、2552，2552 已被王五冻结，被拒绝。旧的做法三人各先锁
    自己的单据，互相等成环。"""
    p = platform
    gates = {who: p.gates.hold(who, "加锁前") for who in (ZHANG, WANG, ZHAO)}
    zhang = p.start(ZHANG, save(COST_PAGE, [cost(2551, dtl(255101, GOODSID="1"))]))
    gates[ZHANG].wait()
    wang = p.start(WANG, save(GOODS_PAGE, [goods(1, ZX_PRICE="11")]))
    gates[WANG].wait()
    zhao = p.start(ZHAO, save(COST_PAGE2, [cost(2552, dtl(255202, MEMO="赵六改"))]))
    gates[ZHAO].wait()
    gates[ZHAO].release()
    time.sleep(PAUSE)
    assert zhao.is_alive() and row_is_free(p.engine, TABLE_DOC, "DOCID", 2552)
    gates[WANG].release()
    wang.join(60)
    gates[ZHANG].release()
    zhang.join(60)
    zhao.join(60)
    _log.info("c：%s；%s；%s", zhang.summary(), wang.summary(), zhao.summary())
    assert (zhang.outcome, wang.outcome, zhao.outcome) == (FROZEN, "approvalSubmitted", FROZEN)
    assert frozen(p.engine) == {(TABLE_GOODS, "1"), (TABLE_DOC, "2552")}
    assert p.problems() == []


# ---------------------------------------------------------------- (d) 规则 4 的例外：整个回滚，用新的范围重来一次

def test_d_own_document_changed_between_read_and_lock_runs_again(platform: Platform) -> None:
    """王五改物料 3 的执行价：普通读到物料 3、找出 2551 后、加锁前停下；李四这时改了物料 3 的名称（不触发审批）并提交。
    王五继续，锁住后核对物料 3 与加锁前读到的不同，整个事务回滚，命令记录一起撤销，用新的数据重来一次，第二次提交。
    只有王五这条命令执行了两次。"""
    p = platform
    gate = p.gates.hold(WANG, "加锁前")
    command = save(GOODS_PAGE, [goods(3, ZX_PRICE="31")])
    wang = p.start(WANG, command)
    gate.wait()
    li = p.run(LI, save(GOODS_PAGE, [goods(3, NAME="W（李四改名）")]))
    gate.release()
    wang.join(60)
    _log.info("d：%s；%s", li.summary(), wang.summary())
    assert (li.outcome, wang.outcome) == ("saved", "approvalSubmitted")
    assert fetch(p.engine, f"SELECT NAME, ZX_PRICE FROM {TABLE_GOODS} WHERE GOODSID = 3")[0] == {"name": "W（李四改名）", "zx_price": 30}
    assert frozen(p.engine) == {(TABLE_GOODS, "3"), (TABLE_DOC, "2551")}
    rows = fetch(p.engine, "SELECT COUNT(*) AS N FROM pf_command WHERE user_id = :u AND request_key = :k", u=WANG, k=command.request_key)
    assert rows[0]["n"] == 1
    assert p.problems(retried=frozenset({command.request_key})) == []


# ---------------------------------------------------------------- (e) 往前冻结的页面保存的 SQL 条数（WP-10）

def _traced(p: Platform, user: str, command: t.Command) -> tuple[t.CommandResult, list[str]]:
    """在当前线程执行命令（SQL 追踪按线程记），返回结果和每条 SQL 的文本。"""
    with _tracer.capture() as trace:
        result = p.runner.execute(command, p.context(user))
    return result, trace.texts


def _kinds(sql: list[str]) -> list[str]:
    """每条 SQL 的种类：加锁（带 FOR UPDATE）、入口条件（FROM DUAL）、其余按第一个词。"""
    return ["LOCK" if "FOR UPDATE" in s else "DUAL" if " FROM DUAL" in s else s.split(" ")[0] for s in sql]


def test_e1_goods_page_save_locks_and_reads_in_one_statement(platform: Platform) -> None:
    """物料清单页配了往前冻结的审批流（L_GOODS_TO_COST，同 d_cg 的 GOODS_TO_COST），保存推迟加锁（规则 3）。李四只改物料 3 的
    名称、不触发审批：插入命令记录、加锁前普通读取、入口条件、锁住物料 3 并读出数据（一条，锁住后用它核对，规则 4）、
    查冻结、改物料、完成命令记录，共 7 条。原来锁和核对重读是两条，共 8 条（`.reports/batch5-20261030/b1-pipeline/`）。"""
    result, sql = _traced(platform, LI, save(GOODS_PAGE, [goods(3, NAME="W（李四改名）")]))
    _log.info("e1：%s 条：%s", len(sql), sql)
    assert result.outcome == "saved"
    assert _kinds(sql) == ["INSERT", "SELECT", "DUAL", "LOCK", "SELECT", "UPDATE", "UPDATE"], sql
    assert f"FROM {TABLE_GOODS}" in sql[3] and "NAME" in sql[3]  # 加锁语句同时读出物料的数据
    assert fetch(platform.engine, f"SELECT NAME FROM {TABLE_GOODS} WHERE GOODSID = 3")[0]["name"] == "W（李四改名）"


def test_e2_goods_price_change_freezing_cost_saves_one_statement(platform: Platform) -> None:
    """王五改物料 3 的执行价，进入审批、冻结含物料 3 的成本单 2551：按顺序锁 2551（只锁，一条）、物料 3（锁并读出数据，
    一条，锁住后用它核对），锁后不再整批重读。加锁语句只有这两条，后面没有再读物料 3 的普通查询。"""
    result, sql = _traced(platform, WANG, save(GOODS_PAGE, [goods(3, ZX_PRICE="31")]))
    _log.info("e2：%s 条：%s", len(sql), sql)
    assert result.outcome == "approvalSubmitted"
    locks = [i for i, s in enumerate(sql) if "FOR UPDATE" in s]
    assert [sql[i].split(" FROM ")[1].split(" ")[0] for i in locks] == [TABLE_DOC, TABLE_GOODS], sql
    assert "ZX_PRICE" in sql[locks[1]]
    assert not any(f"FROM {TABLE_GOODS}" in s and "FOR UPDATE" not in s for s in sql[locks[1] + 1:]), sql
    assert frozen(platform.engine) == {(TABLE_GOODS, "3"), (TABLE_DOC, "2551")}
