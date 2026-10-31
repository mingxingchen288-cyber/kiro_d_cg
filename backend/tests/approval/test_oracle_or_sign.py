"""或签一人通过后其余审批人显示已跳过（approval T-AP-8，AP-04，C09 v12）的真实验证（d_cg）。

在进程内接上真实的权限、写入管道、审批阶段和审批服务（接法同 tests/pipeline/test_oracle_updated_by.py）：配置取
`backend/seed/config` 加一条测试用的审批流，放在内存中的配置库里，d_cg 的 PF_CONFIG_ITEM 不动，别组正在跑的用例不受影响；
业务表、审批表、命令记录和审批人账号都在 d_cg。没有接投递（不发通知）。

测试审批流 PF_TEST_OR_SIGN：成本核算的原辅料有修改就进入；第 1 级"两人或签"配了 admin（系统管理员，用户 1）和
chengben01（成本会计一，用户 88）两个账号；第 2 级"管理员复核"只有 admin。审批停在第 2 级时，页面上的审批进度弹窗
（读同一个详情接口 GET /api/approvals/{id}）能看到第 1 级的结果。

数据自己建、自己删：admin 经平台新建一张成本单（原辅料一行聚维酮K30），改这一行的备注提交审批；admin 通过第 1 级后
chengben01 为已跳过、不能再处理，审批进入第 2 级；admin 驳回（不写业务表），再经平台删掉这张成本单；结束时删掉本测试的
审批和命令记录（中途失败留下的成本单直接按主键删）。

运行：`uv run --with <wheel> pytest -m oracle tests/approval/test_oracle_or_sign.py`。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine, text

from cost_platform.approval import ApprovalDeps, create_approval
from cost_platform.approval.catalog import catalog_of
from cost_platform.approval.service import ApprovalService
from cost_platform.assembly.settings import Settings
from cost_platform.authz.checker import RolePermissionChecker
from cost_platform.authz.stage import OperationPermissionStage
from cost_platform.contracts import types as t
from cost_platform.contracts.fakes import FakeCommandMonitor, FakeDeliveryDispatcher, FakeEntityDirectory
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.db_core.schema import OracleSchemaInspector
from cost_platform.identity.accounts import OracleAccounts
from cost_platform.orchestration.runner import CommandRunner
from cost_platform.pipeline.calc import Recalculator
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.copies import OracleCopySources
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.loader import DocumentLoader, PageSaveInvolved
from cost_platform.pipeline.locks import LockBook, PipelineLocks, ReadViews
from cost_platform.pipeline.merge import DocumentMerger, IntentMerger
from cost_platform.pipeline.stages import LockStage, MergeIntentsStage, MergePatchesStage, RecalculateStage, WriteChangesStage
from cost_platform.pipeline.table_writer import OracleTableWriter
from cost_platform.pipeline.values import ColumnScales
from cost_platform.pipeline.writer import ChangeWriter
from cost_platform.queries.documents import OracleDocumentReader

from tests.config.support import Env, seed_drafts

cost_rules_core = pytest.importorskip("cost_rules_core", reason="需要 rules-core 的 wheel")
from cost_rules_core import RulesEngine  # noqa: E402

pytestmark = pytest.mark.oracle

PAGE, SAVE = "COST_PINGGU", "COST_PINGGU.save"
FLOW_CODE = "PF_TEST_OR_SIGN"
MARKER = "PF_TEST test_oracle_or_sign"


def _node(name: str, users: list[str]) -> dict[str, Any]:
    return {"name": name, "conditionType": "always", "mode": "or", "approvers": [{"type": "user", "userId": u} for u in users]}


FLOW = t.ConfigDraft(type="approvalFlow", key=FLOW_CODE, name="PF_TEST两人或签", content={
    "page": PAGE, "order": 99, "operations": {"COST_MATERIAL": ["modify"]},
    "levels": [{"level": 1, "nodes": [_node("两人或签", ["1", "88"])]}, {"level": 2, "nodes": [_node("管理员复核", ["1"])]}],
})


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    s = Settings.load()
    found = create_oracle_engine(s.db_user, s.db_password, s.db_dsn)
    yield found
    found.dispose()


def _rows(engine: Engine, sql: str, **binds: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), binds).mappings()]


class Platform:
    """进程内的平台：真实的配置快照（seed 加测试审批流）、权限、写入管道、审批，d_cg 上的事务。"""

    def __init__(self, engine: Engine) -> None:
        rules = RulesEngine()
        env = Env(engine=rules)
        env.save([*seed_drafts(), FLOW])
        self.config = env.reader
        snapshot = self.config.read("ADMIN")
        entities = FakeEntityDirectory({code: snapshot.entity(code) for code in
                                        ("COST_PINGGU", "COST_MATERIAL", "COST_PACKAGE", "COST_GOODS_PRICE")})
        self.uow = OracleUnitOfWorkFactory(engine)
        schema = OracleSchemaInspector(engine)
        book = LockBook()
        tables = OracleTableWriter(5, schema, book)
        self.accounts = OracleAccounts(self.uow)
        permission = RolePermissionChecker()
        scales = ColumnScales(schema)
        store = OracleDocumentStore(5, ReadViews(schema))  # 同 pipeline 插件
        loader = DocumentLoader(store, permission, book)
        deps = ApprovalDeps(catalog=catalog_of(entities, self.config), schema=schema, directory=self.accounts,
                            documents=OracleDocumentReader(self.uow, entities), rules=rules, tables=tables,
                            locks=PipelineLocks(book, store, schema))
        stages = [OperationPermissionStage(permission), PageSaveInvolved(), LockStage(loader),
                  MergePatchesStage(DocumentMerger(permission, scales), OracleCopySources(permission)),
                  MergeIntentsStage(IntentMerger(scales)),
                  RecalculateStage(Recalculator(rules, scales)), WriteChangesStage(ChangeWriter(store)),
                  *create_approval(deps).stages()]
        self.executor = CommandRunner(self.uow, OracleCommandRecorder(5, tables), FakeCommandMonitor(), FakeDeliveryDispatcher(),
                                      stages)
        self.service = ApprovalService(deps, self.uow, self.executor)
        self.request_keys: list[str] = []

    def key(self) -> str:
        key = str(uuid.uuid4())
        self.request_keys.append(key)
        return key

    def ctx(self, username: str) -> t.ExecutionContext:
        """以 ADMIN 角色的配置快照执行（seed 只有 ADMIN 和技术中心两个角色）；身份是这个账号。"""
        account = self.accounts.find(username)
        assert account is not None
        identity = t.Identity(user_id=account.user_id, username=account.username, display_name=account.display_name,
                              department_id=account.department_id, role_code="ADMIN", session_id="b2-or-sign")
        snapshot = self.config.read("ADMIN")
        return t.ExecutionContext(request_id=str(uuid.uuid4()), identity=identity, config=snapshot, config_version=snapshot.version,
                                  origin=t.Origin(kind="user", approval_id=None), now=datetime.now().replace(microsecond=0))

    def save(self, ctx: t.ExecutionContext, documents: list[dict[str, Any]]) -> t.CommandResult:
        command = t.parse_wire(t.Command, {"requestKey": self.key(), "page": PAGE, "operation": SAVE, "params": {},
                                           "documents": documents})
        return self.executor.execute(command, ctx)

    def steps(self, ctx: t.ExecutionContext, approval_id: str) -> list[tuple[int, str, str, list[tuple[str, str]]]]:
        detail = self.service.detail(ctx, approval_id)
        return [(s.level, s.node, s.status, [(m.name, m.status) for m in s.members]) for s in detail.steps]


def test_or_sign_second_approver_skipped_after_first_passes(engine: Engine) -> None:
    platform = Platform(engine)
    admin = platform.ctx("admin")
    names = {r["user_id"]: r["display_name"] for r in _rows(engine, "SELECT user_id, display_name FROM pf_user "
                                                                    "WHERE user_id IN (1, 88)")}
    admin_name, accountant_name = names[1], names[88]
    approvals: list[str] = []
    docid = None
    try:
        # admin 新建一张成本单（原辅料一行聚维酮K30），新增不在测试审批流的审核操作中，直接保存
        master, line = f"tmp-{uuid.uuid4()}", f"tmp-{uuid.uuid4()}"
        created = platform.save(admin, [{"entity": PAGE, "master": {"op": "add", "clientRowId": master, "values": {
            "MEMO": MARKER, "APEX_PL": "1000000", "P_PERPACK": "112", "S_PERBACK": "80", "YIELD": "93.94"}},
            "details": [{"entity": "COST_MATERIAL", "op": "add", "clientRowId": line,
                         "values": {"GOODSID": "25", "PER_HL": "10", "PRICE": "75"}}]}])
        assert created.outcome == "saved"
        docid, dtlid = created.id_map[master], created.id_map[line]

        # 改原辅料的备注：进入测试审批流，第 1 级两人都待处理，第 2 级预计进入
        submitted = platform.save(admin, [{"entity": PAGE, "master": {"op": "none", "rowKey": docid}, "details": [
            {"entity": "COST_MATERIAL", "op": "modify", "rowKey": dtlid, "changes": {"MEMO": "B2 或签"}}]}])
        assert submitted.outcome == "approvalSubmitted"
        [approval] = submitted.approvals
        approval_id = approval.approval_id
        approvals.append(approval_id)
        assert approval.flows == [FLOW_CODE]
        assert platform.steps(admin, approval_id) == [
            (1, "两人或签", "pending", [(admin_name, "pending"), (accountant_name, "pending")]),
            (2, "管理员复核", "upcoming", [(admin_name, "pending")])]

        # admin 通过第 1 级：chengben01 记为已跳过（存进进度），审批进入第 2 级
        detail = platform.service.detail(admin, approval_id)
        passed = platform.service.pass_(admin, approval_id, t.PassRequest(
            request_key=platform.key(), fingerprint=detail.fingerprint, checked_rows=[], params={}))
        assert passed.outcome == "approvalProcessed" and passed.approvals[0].level == 2
        steps = platform.steps(admin, approval_id)
        print(f"审批 {approval_id}（成本单 {docid}）第 1 级通过后：{steps}")
        assert steps == [(1, "两人或签", "passed", [(admin_name, "passed"), (accountant_name, "skipped")]),
                         (2, "管理员复核", "pending", [(admin_name, "pending")])]
        [stored] = _rows(engine, "SELECT progress FROM pf_approval WHERE approval_id = :a", a=int(approval_id))
        first = json.loads(stored["progress"])["nodes"][0]
        assert [(m["id"], m["status"]) for m in first["members"]] == [("1", "passed"), ("88", "skipped")]
        accountant = platform.ctx("chengben01")
        assert platform.service.detail(accountant, approval_id).actions.can_pass is False

        # admin 驳回（不写业务表）：第 1 级的结果不变，第 2 级为已驳回
        platform.service.reject(admin, approval_id, t.RejectRequest(request_key=platform.key(), comment="B2 或签测试结束"))
        assert platform.steps(admin, approval_id) == [
            (1, "两人或签", "passed", [(admin_name, "passed"), (accountant_name, "skipped")]),
            (2, "管理员复核", "rejected", [(admin_name, "rejected")])]
        assert _rows(engine, "SELECT memo FROM t_cost_pinggu_dtl WHERE dtlid = :d", d=int(dtlid)) == [{"memo": None}]

        # 经平台删掉这张成本单
        removed = platform.save(admin, [{"entity": PAGE, "master": {"op": "delete", "rowKey": docid}, "details": []}])
        assert removed.outcome == "saved"
        assert _rows(engine, "SELECT docid FROM t_cost_pinggu WHERE docid = :d", d=int(docid)) == []
    finally:
        with engine.begin() as conn:
            for key in platform.request_keys:
                conn.execute(text("DELETE FROM pf_command WHERE request_key = :k"), {"k": key})
            for approval_id in approvals:
                for table in ("pf_approval_freeze", "pf_approval_record", "pf_approval_affected", "pf_approval"):
                    conn.execute(text(f"DELETE FROM {table} WHERE approval_id = :a"), {"a": int(approval_id)})
            if docid is not None:
                conn.execute(text("DELETE FROM t_cost_pinggu_dtl WHERE docid = :d"), {"d": int(docid)})
                conn.execute(text("DELETE FROM t_cost_pinggu WHERE docid = :d"), {"d": int(docid)})
