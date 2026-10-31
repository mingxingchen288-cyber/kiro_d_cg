"""固定加锁层级真实验证（`test_oracle_lock_order.py`）用的组装、测试表、钩子和并发执行。

组装：write-pipeline 的真实实现（`OracleDocumentStore`、`DocumentLoader`、`OracleTableWriter`、`PipelineLocks` 共用一个
`LockBook`，加锁等待 `WAIT` 秒）、approval 的管道阶段（`ApprovalStore` 写 d_cg 的 PF_APPROVAL*）、orchestration 的
`CommandRunner`。配置只在内存中（`FakeConfigSnapshot`、`ItemsApprovalCatalog`），不写 PF_CONFIG_ITEM。

测试表（PF_TEST_LK_DOC 主表、PF_TEST_LK_DTL 明细、PF_TEST_LK_GOODS 物料，仿成本核算和物料清单）由 fixture 建、结束时删；
测试产生的审批（PF_APPROVAL*）和命令记录（用户 990101–990104）每个场景结束时删掉。

数据：成本单 2551 含物料 3（W）、2（Y）；2552 含物料 1（K）、2（Y）。审批流（只在内存中）：
- PF_COST_PAGE 的 L_COST_TO_GOODS：改明细的物料或单价，冻结物料清单中这个物料（往后找，同 d_cg 的 COST_TO_GOODS）；
- PF_GOODS_PAGE 的 L_GOODS_TO_COST：改物料的执行价，冻结含这个物料的成本单（往前找，同 GOODS_TO_COST）；
- PF_COST_PAGE2 的 L_CROSS（假设）：改明细，冻结含这个物料的成本单（同层找）。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from cost_platform.approval import ApprovalDeps, ItemsApprovalCatalog, create_approval
from cost_platform.approval.store import ApprovalStore
from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import (
    FakeCommandMonitor,
    FakeConfigSnapshot,
    FakeDeliveryDispatcher,
    FakeDirectory,
    FakeDocumentReader,
    FakePermissionChecker,
    FakeRulesEngine,
    FakeSchemaInspector,
    FakeStage,
)
from cost_platform.db_core.engine import OracleUnitOfWorkFactory
from cost_platform.db_core.schema import OracleSchemaInspector
from cost_platform.orchestration.runner import CommandRunner
from cost_platform.pipeline.calc import Recalculator
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.loader import DocumentLoader, PageSaveInvolved
from cost_platform.pipeline.locks import LockBook, PipelineLocks, ReadViews
from cost_platform.pipeline.merge import DocumentMerger, IntentMerger
from cost_platform.pipeline.stages import LockStage, MergeIntentsStage, MergePatchesStage, RecalculateStage, WriteChangesStage
from cost_platform.pipeline.table_writer import OracleTableWriter
from cost_platform.pipeline.values import ColumnScales
from cost_platform.pipeline.writer import ChangeWriter

from .support import fld, view_fields

WAIT = 10
"""加锁等待秒数（FOR UPDATE WAIT 10）：比 Oracle 检出死锁的约 3 秒长，有死锁时先报 ORA-00060，不会先等锁超时。"""
PAUSE = 1.5
"""让别的连接走到等锁的位置再继续。"""

DOC, DTL, GOODS = "PF_DOC", "PF_DTL", "PF_GOODS"
COST_PAGE, COST_PAGE2, GOODS_PAGE = "PF_COST_PAGE", "PF_COST_PAGE2", "PF_GOODS_PAGE"
PAGES = (COST_PAGE, COST_PAGE2, GOODS_PAGE)
ZHANG, LI, WANG, ZHAO = "990101", "990102", "990103", "990104"
NAMES = {ZHANG: "张三", LI: "李四", WANG: "王五", ZHAO: "赵六"}
TABLE_DOC, TABLE_DTL, TABLE_GOODS = "PF_TEST_LK_DOC", "PF_TEST_LK_DTL", "PF_TEST_LK_GOODS"
FROZEN = "FROZEN_BY_APPROVAL"

DDL = [
    f"CREATE TABLE {TABLE_DOC} (DOCID NUMBER(12) PRIMARY KEY, MEMO VARCHAR2(200))",
    f"CREATE TABLE {TABLE_DTL} (DTLID NUMBER(12) PRIMARY KEY, DOCID NUMBER(12) NOT NULL, GOODSID NUMBER(12), "
    "PRICE NUMBER(18,2), MEMO VARCHAR2(200))",
    f"CREATE TABLE {TABLE_GOODS} (GOODSID NUMBER(12) PRIMARY KEY, NAME VARCHAR2(100), ZX_PRICE NUMBER(18,2))",
]
DROP = [f"DROP TABLE {TABLE_DTL} PURGE", f"DROP TABLE {TABLE_DOC} PURGE", f"DROP TABLE {TABLE_GOODS} PURGE"]
ROWS = [
    f"INSERT INTO {TABLE_DOC} VALUES (2551, NULL)", f"INSERT INTO {TABLE_DOC} VALUES (2552, NULL)",
    f"INSERT INTO {TABLE_DTL} VALUES (255101, 2551, 3, 30, NULL)", f"INSERT INTO {TABLE_DTL} VALUES (255102, 2551, 2, 20, NULL)",
    f"INSERT INTO {TABLE_DTL} VALUES (255201, 2552, 1, 10, NULL)", f"INSERT INTO {TABLE_DTL} VALUES (255202, 2552, 2, 20, NULL)",
    f"INSERT INTO {TABLE_GOODS} VALUES (1, 'K', 10)", f"INSERT INTO {TABLE_GOODS} VALUES (2, 'Y', 20)",
    f"INSERT INTO {TABLE_GOODS} VALUES (3, 'W', 30)",
]
_SOURCES = "('PF_DOC', 'PF_GOODS')"
CLEANUP = [
    f"DELETE FROM pf_approval_freeze WHERE approval_id IN (SELECT approval_id FROM pf_approval WHERE source_entity IN {_SOURCES})",
    "DELETE FROM pf_approval_freeze WHERE root_table LIKE 'PF_TEST_LK_%'",
    f"DELETE FROM pf_approval_affected WHERE approval_id IN (SELECT approval_id FROM pf_approval WHERE source_entity IN {_SOURCES})",
    f"DELETE FROM pf_approval_record WHERE approval_id IN (SELECT approval_id FROM pf_approval WHERE source_entity IN {_SOURCES})",
    f"DELETE FROM pf_approval WHERE source_entity IN {_SOURCES}",
    f"DELETE FROM pf_command WHERE user_id IN ('{ZHANG}', '{LI}', '{WANG}', '{ZHAO}')",
]

ENTITIES = {
    DOC: t.EntityConfig(table=TABLE_DOC, primary_key="DOCID", freezable=True,
                        fields=[fld("DOCID", "number", role="system"), fld("MEMO")],
                        details=[t.DetailLink(entity=DTL, parent_key="DOCID")]),
    DTL: t.EntityConfig(table=TABLE_DTL, primary_key="DTLID", freezable=True,
                        fields=[fld("DTLID", "number", role="system"), fld("DOCID", "number", role="system"),
                                fld("GOODSID", "number"), fld("PRICE", "number"), fld("MEMO")]),
    GOODS: t.EntityConfig(table=TABLE_GOODS, primary_key="GOODSID", freezable=True,
                          fields=[fld("GOODSID", "number", role="system"), fld("NAME"), fld("ZX_PRICE", "number")]),
}
WRITABLE = {(COST_PAGE, DOC): ("MEMO",), (COST_PAGE, DTL): ("GOODSID", "PRICE", "MEMO"),
            (COST_PAGE2, DOC): ("MEMO",), (COST_PAGE2, DTL): ("GOODSID", "PRICE", "MEMO"),
            (GOODS_PAGE, GOODS): ("NAME", "ZX_PRICE")}
_GRID = t.GridOptions(side_bar=True, cell_selection=True, group_by=[])


def _cost_view(page: str) -> t.PageView:
    return t.PageView(page_code=page, title="成本核算（加锁测试）", version=1, layout="masterDetail", detail_mode="tabs",
                      audit=False, save_operation=f"{page}.save", rules_pack=t.PackRef(pack_id=page, version=1),
                      master=t.ViewMaster(entity=DOC, primary_key="DOCID", fields=view_fields(ENTITIES[DOC], WRITABLE[(page, DOC)]),
                                          buttons=[], grid=_GRID, form_layout=[]),
                      details=[t.ViewDetail(entity=DTL, title="明细", primary_key="DTLID", parent_key="DOCID",
                                            fields=view_fields(ENTITIES[DTL], WRITABLE[(page, DTL)]), buttons=[], grid=_GRID,
                                            form_layout=[])],
                      system_buttons=["save"])


VIEWS = {COST_PAGE: _cost_view(COST_PAGE), COST_PAGE2: _cost_view(COST_PAGE2),
         GOODS_PAGE: t.PageView(page_code=GOODS_PAGE, title="物料清单（加锁测试）", version=1, layout="single", detail_mode="tabs",
                                audit=False, save_operation=f"{GOODS_PAGE}.save", rules_pack=t.PackRef(pack_id=GOODS_PAGE, version=1),
                                master=t.ViewMaster(entity=GOODS, primary_key="GOODSID",
                                                    fields=view_fields(ENTITIES[GOODS], WRITABLE[(GOODS_PAGE, GOODS)]),
                                                    buttons=[], grid=_GRID, form_layout=[]),
                                details=[], system_buttons=["save"])}


def _flow(page: str, order: int, entity: str, condition: str | None, freeze_table: str) -> t.ApprovalFlowConfig:
    node: dict[str, Any] = {"name": "管理员审批", "conditionType": "sql" if condition else "always", "department": None,
                            "approvers": [{"type": "role", "role": "ADMIN"}], "mode": "or", "enabled": True}
    if condition:
        node["condition"] = condition
    return t.parse_config_content("approvalFlow", {  # type: ignore[return-value]
        "page": page, "order": order, "enabled": True, "operations": {entity: ["modify"]},
        "levels": [{"level": 1, "nodes": [node]}],
        "freeze": [{"table": freeze_table, "condition": "GOODSID = :new_GOODSID", "enabled": True}],
        "display": [], "propagation": "end", "notify": []})


FLOWS = {
    "L_COST_TO_GOODS": ("成本单改价冻结物料清单（测试）", _flow(
        COST_PAGE, 1, DTL, "DECODE(:new_GOODSID, :old_GOODSID, 0, 1) = 1 OR DECODE(:new_PRICE, :old_PRICE, 0, 1) = 1", TABLE_GOODS)),
    "L_GOODS_TO_COST": ("物料清单改价冻结成本单（测试）", _flow(GOODS_PAGE, 2, GOODS, "DECODE(:new_ZX_PRICE, :old_ZX_PRICE, 0, 1) = 1",
                                                     TABLE_DTL)),
    "L_CROSS": ("（假设）同物料成本单互相冻结", _flow(COST_PAGE2, 3, DTL, None, TABLE_DTL)),
}
CATALOG = ItemsApprovalCatalog(FLOWS, ENTITIES, {"ADMIN": "系统管理员"})


def _inspector() -> FakeSchemaInspector:
    found = FakeSchemaInspector()
    scales = {(TABLE_DTL, "PRICE"): 2, (TABLE_GOODS, "ZX_PRICE"): 2}
    for entity in ENTITIES.values():
        found.add_table(entity.table, [t.ColumnInfo(name=str(f.column), data_type="NUMBER" if f.type == "number" else "VARCHAR2",
                                                    nullable=True, length=None, precision=None, scale=scales.get((entity.table, f.column)))
                                       for f in entity.fields], primary_key=entity.primary_key)
    return found


# ---------------------------------------------------------------- 钩子

CURRENT = threading.local()
"""执行命令的线程中当前用户的编号（钩子按用户和位置停下）。"""


@dataclass
class Gate:
    arrived: threading.Event = field(default_factory=threading.Event)
    released: threading.Event = field(default_factory=threading.Event)

    def wait(self) -> None:
        assert self.arrived.wait(30), "命令没有走到钩子的位置"

    def release(self) -> None:
        self.released.set()


class Gates:
    """`hold(用户, 位置)` 之后，这个用户的命令走到这个位置时停下，等 `release`；每个钩子只停一次（规则 4 重来时不再停）。
    位置："加锁前"（`BusinessLocker.lock` 之前，触发审批冻结前加锁）、"冻结前"（已锁住、登记冻结之前）、"查冻结前"
    （加锁读取之后、冻结检查之前）。"""

    def __init__(self) -> None:
        self._gates: dict[tuple[str, str], Gate] = {}
        self._lock = threading.Lock()

    def hold(self, user: str, point: str) -> Gate:
        gate = Gate()
        with self._lock:
            self._gates[(user, point)] = gate
        return gate

    def reach(self, point: str) -> None:
        with self._lock:
            gate = self._gates.pop((getattr(CURRENT, "user", ""), point), None)
        if gate is not None:
            gate.arrived.set()
            assert gate.released.wait(30)


class PausingLocks(PipelineLocks):
    def __init__(self, gates: Gates, *args: Any) -> None:
        super().__init__(*args)
        self._gates = gates

    def lock(self, uow: Any, ctx: t.ExecutionContext, targets: list[t.LockTarget],
             expected: dict[t.DocumentRef, t.DocumentData] | None = None) -> None:
        self._gates.reach("加锁前")
        super().lock(uow, ctx, targets, expected)


class PausingStore(ApprovalStore):
    def __init__(self, gates: Gates) -> None:
        self._gates = gates

    def freeze(self, uow: Any, entries: Any) -> None:
        self._gates.reach("冻结前")
        super().freeze(uow, entries)


class CountingRecorder(OracleCommandRecorder):
    """记下每个请求键开始执行的次数（判重那一步）：规则 4 回滚重来时同一请求键执行两次。"""

    def __init__(self) -> None:
        super().__init__(10)
        self.attempts: Counter[str] = Counter()

    def begin(self, uow: Any, user_id: str, command: t.Command, now: datetime) -> t.CommandResult | None:
        self.attempts[command.request_key] += 1
        return super().begin(uow, user_id, command, now)


# ---------------------------------------------------------------- 组装和执行

class Worker(threading.Thread):
    def __init__(self, platform: Platform, user: str, command: t.Command) -> None:
        super().__init__(daemon=True)
        self.platform, self.user, self.command = platform, user, command
        self.result: t.CommandResult | None = None
        self.error: BaseException | None = None
        self.seconds = 0.0

    def run(self) -> None:
        CURRENT.user = self.user
        start = time.monotonic()
        try:
            self.result = self.platform.runner.execute(self.command, self.platform.context(self.user))
        except BaseException as error:  # 记下，由测试判断
            self.error = error
        self.seconds = time.monotonic() - start

    @property
    def outcome(self) -> str:
        if self.error is not None:
            return self.error.code.value if isinstance(self.error, t.PlatformError) else repr(self.error)
        assert self.result is not None
        return self.result.outcome

    @property
    def database_error(self) -> str:
        return str(getattr(self.error, "__cause__", None) or "")

    def summary(self) -> str:
        return f"{NAMES[self.user]} {self.outcome}（{self.seconds:.2f} 秒，执行 {self.platform.recorder.attempts[self.command.request_key]} 次）"


class Platform:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.gates = Gates()
        inspector = _inspector()
        scales = ColumnScales(inspector)
        views = ReadViews(OracleSchemaInspector(engine))  # 同 plugin.py：读取视图读取哪些表取 d_cg 的数据字典
        permission = FakePermissionChecker()
        for (page, entity), names in WRITABLE.items():
            permission.set_writable(page, entity, names)
        rules = FakeRulesEngine()
        self.pack = rules.load_pack(b'{"packId": "PF", "version": 1, "coreVersion": "0.1.0", "fields": {}, "rules": [], "jdm": {}}')
        book = LockBook()
        store = OracleDocumentStore(WAIT, views)
        directory = FakeDirectory()
        directory.add_account(t.AccountRef("990100", "pf_test_admin", "系统管理员（测试）", None, True), ["ADMIN"])
        deps = ApprovalDeps(catalog=lambda ctx: CATALOG, schema=inspector, directory=directory, documents=FakeDocumentReader(),
                            tables=OracleTableWriter(WAIT, inspector, book), locks=PausingLocks(self.gates, book, store, inspector),
                            store=PausingStore(self.gates))
        approval = create_approval(deps)
        self.recorder = CountingRecorder()
        stages = [PageSaveInvolved(), LockStage(DocumentLoader(store, permission, book)), MergePatchesStage(DocumentMerger(permission, scales)),
                  MergeIntentsStage(IntentMerger(scales)), RecalculateStage(Recalculator(rules, scales)), WriteChangesStage(ChangeWriter(store)),
                  FakeStage("冻结检查", effect=lambda uow, state, ctx: self.gates.reach("查冻结前")), *approval.stages()]
        self.runner = CommandRunner(OracleUnitOfWorkFactory(engine), self.recorder, FakeCommandMonitor(), FakeDeliveryDispatcher(),
                                    stages)
        self.workers: list[Worker] = []

    def context(self, user: str) -> t.ExecutionContext:
        operation = t.OperationConfig(label="保存", kind="save", propagation="continue")
        snapshot = FakeConfigSnapshot(version=1, role_code="PF_TEST", role=t.RoleConfig(name="测试", admin=False, pages={}),
                                      page_views=VIEWS, entities=ENTITIES, operations={f"{p}.save": operation for p in PAGES},
                                      packs={p: self.pack for p in PAGES}, rule_fields={p: {} for p in PAGES})
        identity = t.Identity(user_id=user, username=f"u{user}", display_name=NAMES[user], department_id="10", role_code="PF_TEST",
                              session_id=f"s-{user}")
        return t.ExecutionContext(request_id=str(uuid.uuid4()), identity=identity, config=snapshot, config_version=1,
                                  origin=t.Origin(kind="user", approval_id=None), now=datetime.now().replace(microsecond=0))

    def start(self, user: str, command: t.Command) -> Worker:
        worker = Worker(self, user, command)
        self.workers.append(worker)
        worker.start()
        return worker

    def run(self, user: str, command: t.Command) -> Worker:
        worker = self.start(user, command)
        worker.join(60)
        return worker

    def problems(self, retried: frozenset[str] = frozenset()) -> list[str]:
        """不允许的情况：死锁（ORA-00060）、等锁超时、命令执行了不止一次（`retried` 中的规则 4 例外除外）、线程没结束。"""
        found = []
        for w in self.workers:
            if w.is_alive():
                found.append(f"{NAMES[w.user]} 还没结束")
            if "ORA-00060" in w.database_error:
                found.append(f"{NAMES[w.user]} 死锁：{w.database_error}")
            if w.outcome == "DOCUMENT_BUSY":
                found.append(f"{NAMES[w.user]} 等锁超时")
            expected = 2 if w.command.request_key in retried else 1
            if self.recorder.attempts[w.command.request_key] != expected:
                found.append(f"{NAMES[w.user]} 执行了 {self.recorder.attempts[w.command.request_key]} 次")
        return found


# ---------------------------------------------------------------- 命令和查询

def save(page: str, documents: list[dict[str, Any]]) -> t.Command:
    return t.parse_wire(t.Command, {"requestKey": str(uuid.uuid4()), "page": page, "operation": f"{page}.save",
                                    "documents": documents, "params": {}})


def cost(docid: int, *details: dict[str, Any], master: dict[str, Any] | None = None) -> dict[str, Any]:
    head = {"op": "modify", "rowKey": str(docid), "changes": master} if master else {"op": "none", "rowKey": str(docid)}
    return {"entity": DOC, "master": head, "details": list(details)}


def dtl(key: int, **changes: str) -> dict[str, Any]:
    return {"entity": DTL, "op": "modify", "rowKey": str(key), "changes": changes}


def goods(goods_id: int, **changes: str) -> dict[str, Any]:
    return {"entity": GOODS, "master": {"op": "modify", "rowKey": str(goods_id), "changes": changes}, "details": []}


def execute(engine: Engine, statements: list[str], ignore_errors: bool = False) -> None:
    with engine.connect() as connection:
        for sql in statements:
            try:
                connection.execute(text(sql))
            except DBAPIError:
                if not ignore_errors:
                    raise
        connection.commit()


def fetch(engine: Engine, sql: str, **binds: Any) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(r) for r in connection.execute(text(sql), binds).mappings()]


def frozen(engine: Engine) -> set[tuple[str, str]]:
    return {(r["root_table"], r["record_key"]) for r in fetch(engine, "SELECT root_table, record_key FROM pf_approval_freeze "
                                                                     "WHERE root_table LIKE 'PF_TEST_LK_%'")}


def row_is_free(engine: Engine, table: str, column: str, key: int) -> bool:
    """另开一个连接试锁这一行（NOWAIT），马上回滚：被别的事务锁着时为 False（ORA-00054）。"""
    with engine.connect() as connection:
        try:
            connection.execute(text(f"SELECT {column} FROM {table} WHERE {column} = :k FOR UPDATE NOWAIT"), {"k": key})
            return True
        except DBAPIError as error:
            if "ORA-00054" in str(error.orig):
                return False
            raise
        finally:
            connection.rollback()
