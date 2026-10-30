"""写入修改人（WP-20）的真实验证（d_cg），业务例子：物料清单页改 ERP 物料的单价，审批通过后记下修改人、变成黄底。

旧系统每次保存写 UPDATE_BY = 当前用户名（DynamicDataService.java 第 290–293、392–393 行），审批通过在审批人的请求中执行；
视图 T_COST_GOODS_PRICE_V 的 ROW_CLASS_FLAG：ISERP = 1 且 UPDATE_BY 不是 ERP_SYNC 时为 erp-updated（黄底）。

在进程内按 orchestration 的方式接上真实的模块：配置取 `backend/seed/config`（tests.config.support 的 Env，内存中的配置库，
d_cg 的 PF_CONFIG_ITEM 不动），其中物料清单实体配了 `updatedByColumn: UPDATE_BY`；权限、写入管道、审批的管道阶段和审批服务
都是真实实现，业务表、审批表、命令记录都在 d_cg。没有接投递（不发通知）。

数据自己建、自己删：测试先模拟 ERP 同步新增一个 ERP 物料（ISERP = 1、UPDATE_BY = 'ERP_SYNC'、参考价格 10、执行价为空，
写法同 tests/e2e/sample_two.py 的 `add_erp_goods`），没有成本单用到它；结束时删掉这个物料、本测试的审批和命令记录。

运行：`uv run --with <wheel> pytest -m oracle tests/pipeline/test_oracle_updated_by.py`。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
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
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.loader import DocumentLoader, PageSaveInvolved
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

D = Decimal
PAGE, SAVE, ENTITY = "GOODS_PRICE_MANAGE", "GOODS_PRICE_MANAGE.save", "COST_GOODS_PRICE"
GOODS_NAME = "P组修改人测试辅料"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    s = Settings.load()
    found = create_oracle_engine(s.db_user, s.db_password, s.db_dsn)
    yield found
    found.dispose()


def _one(engine: Engine, sql: str, **binds: Any) -> dict[str, Any]:
    with engine.connect() as conn:
        return dict(conn.execute(text(sql), binds).mappings().one())


class Platform:
    """进程内的平台：真实的配置快照（seed）、权限、写入管道、审批，d_cg 上的事务。"""

    def __init__(self, engine: Engine) -> None:
        rules = RulesEngine()
        env = Env(engine=rules)
        env.save(seed_drafts())
        self.config = env.reader
        snapshot = self.config.read("ADMIN")
        entities = FakeEntityDirectory({code: snapshot.entity(code) for code in
                                        ("COST_PINGGU", "COST_MATERIAL", "COST_PACKAGE", ENTITY)})
        self.uow = OracleUnitOfWorkFactory(engine)
        schema = OracleSchemaInspector(engine)
        tables = OracleTableWriter(5, schema)
        self.accounts = OracleAccounts(self.uow)
        permission = RolePermissionChecker()
        scales = ColumnScales(schema)
        store = OracleDocumentStore(5)
        loader = DocumentLoader(store, permission)
        deps = ApprovalDeps(catalog=catalog_of(entities, self.config), schema=schema, directory=self.accounts,
                            documents=OracleDocumentReader(self.uow, entities), rules=rules, tables=tables)
        stages = [OperationPermissionStage(permission), PageSaveInvolved(), LockStage(loader),
                  MergePatchesStage(DocumentMerger(permission, scales)), MergeIntentsStage(IntentMerger(loader, scales)),
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
        account = self.accounts.find(username)
        assert account is not None and "ADMIN" in account.role_codes
        identity = t.Identity(user_id=account.user_id, username=account.username, display_name=account.display_name,
                              department_id=account.department_id, role_code="ADMIN", session_id="p-updated-by")
        snapshot = self.config.read("ADMIN")
        return t.ExecutionContext(request_id=str(uuid.uuid4()), identity=identity, config=snapshot, config_version=snapshot.version,
                                  origin=t.Origin(kind="user", approval_id=None), now=datetime.now().replace(microsecond=0))


@pytest.fixture
def erp_goods(engine: Engine) -> Iterator[str]:
    """模拟 ERP 同步新增一个 ERP 物料（旧 PROC_SYNC_GOODS_PRICE 的 INSERT），结束时删掉。"""
    with engine.begin() as conn:
        goodsid = str(conn.execute(text("SELECT t_cost_goods_seq.NEXTVAL FROM dual")).scalar_one())
        conn.execute(text("INSERT INTO t_cost_goods (goodsid, goodsname, price, useflag, iserp, update_by) "
                          "VALUES (:g, :n, 10, '辅料', 1, 'ERP_SYNC')"), {"g": int(goodsid), "n": GOODS_NAME})
    yield goodsid
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM t_cost_goods WHERE goodsid = :g"), {"g": int(goodsid)})


def _cleanup(engine: Engine, platform: Platform, approvals: list[str]) -> None:
    with engine.begin() as conn:
        for key in platform.request_keys:
            conn.execute(text("DELETE FROM pf_command WHERE request_key = :k"), {"k": key})
        for approval in approvals:
            for table in ("pf_approval_freeze", "pf_approval_record", "pf_approval_affected", "pf_approval"):
                conn.execute(text(f"DELETE FROM {table} WHERE approval_id = :a"), {"a": int(approval)})


def test_erp_goods_price_approved_records_updater_and_turns_yellow(engine: Engine, erp_goods: str) -> None:
    platform = Platform(engine)
    approvals: list[str] = []
    try:
        before = _one(engine, "SELECT update_by, zx_price FROM t_cost_goods WHERE goodsid = :g", g=int(erp_goods))
        assert (before["update_by"], before["zx_price"]) == ("ERP_SYNC", None)
        assert _one(engine, "SELECT row_class_flag FROM t_cost_goods_price_v WHERE goodsid = :g", g=int(erp_goods))["row_class_flag"] == "erp"

        # admin 在物料清单页把这个 ERP 物料的单价改成 12：必须审批的字段（approvalRequired），提交审批 GOODS_TO_COST，不写业务表
        ctx = platform.ctx("admin")
        command = t.parse_wire(t.Command, {
            "requestKey": platform.key(), "page": PAGE, "operation": SAVE, "params": {},
            "documents": [{"entity": ENTITY, "master": {"op": "modify", "rowKey": erp_goods, "changes": {"ZX_PRICE": "12"}},
                           "details": []}]})
        submitted = platform.executor.execute(command, ctx)
        assert submitted.outcome == "approvalSubmitted"
        [approval] = submitted.approvals
        approvals.append(approval.approval_id)
        assert approval.flows == ["GOODS_TO_COST"]
        pending = _one(engine, "SELECT update_by, zx_price FROM t_cost_goods WHERE goodsid = :g", g=int(erp_goods))
        assert (pending["update_by"], pending["zx_price"]) == ("ERP_SYNC", None)

        # admin（系统管理员角色，GOODS_TO_COST 的审批人）通过：按审批详情当前的勾选预览取指纹，再通过
        detail = platform.service.detail(ctx, approval.approval_id)
        checked = [t.CheckedRow(flow=b.flow, block=b.key, key=r.ref.key) for b in detail.view.affected if b.editable
                   for r in b.rows if r.ref and r.checked]
        fingerprint = platform.service.preview(ctx, approval.approval_id, t.PreviewRequest(checked_rows=checked)).fingerprint
        passed = platform.service.pass_(ctx, approval.approval_id, t.PassRequest(
            request_key=platform.key(), fingerprint=fingerprint, checked_rows=checked, params={}))
        assert passed.outcome == "approvalProcessed"

        after = _one(engine, "SELECT update_by, zx_price, iserp FROM t_cost_goods WHERE goodsid = :g", g=int(erp_goods))
        assert (after["update_by"], after["zx_price"], after["iserp"]) == ("admin", 12, 1)
        view = _one(engine, "SELECT row_class_flag, zx_price FROM t_cost_goods_price_v WHERE goodsid = :g", g=int(erp_goods))
        assert (view["row_class_flag"], view["zx_price"]) == ("erp-updated", 12)
    finally:
        _cleanup(engine, platform, approvals)
