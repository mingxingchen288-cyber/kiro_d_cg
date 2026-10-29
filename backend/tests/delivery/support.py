"""delivery 模拟验证的共用部分：contracts 的 SQLite 替代事务（按迁移脚本建表）、替代的时钟、编号和实时推送，
以及业务例子 E23 的数据。

E23（docs/业务例子.md）：杨娜（cmx 用户 112）在物料清单及成本页把物料 115 的执行价从 75 改为 60 并保存，
系统管理员（cmx 用户 111，admin）收到通知"您有来自于物料清单及成本页面，业务单据为115的审批"；最终批准后，
杨娜收到"……的审批已通过"。用户编号取自 cmx 的 T_COST_USER（`.reports/modules/delivery/01-审批通知的接收人.out.txt`）。
审批编号 203 沿用 C09 的样例；通知意图由 approval 按 AP-17 生成，这里直接给出生成后的结果。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.pool import StaticPool

import cost_platform.delivery.migrations.dl_0001_pf_delivery as migration
from cost_platform.contracts.fakes import (
    FakeClock,
    FakeConfigSnapshot,
    FakeIdGenerator,
    FakeRealtimePublisher,
    FakeUnitOfWorkFactory,
)
from cost_platform.contracts.ports import UnitOfWorkFactory
from cost_platform.contracts.types import (
    Command,
    CommandState,
    ExecutionContext,
    Identity,
    NotificationIntent,
    Origin,
    RoleConfig,
    parse_wire,
)
from cost_platform.delivery import DeliveryService, RegisterNotificationsStage
from cost_platform.delivery.tables import pf_delivery, pf_inbox

ADMIN = "111"
"""系统管理员（cmx 的 admin）。"""
YANG_NA = "112"
"""杨娜（cmx 的 HY200702）。"""

SUBMITTED_TITLE = "您有来自于物料清单及成本页面，业务单据为115的审批"
PASSED_TITLE = "您有来自于物料清单及成本页面，业务单据为115的审批已通过"
APPROVAL_LINK = "/approval/203"

T0 = datetime(2026, 10, 24, 9, 30, 0)
"""杨娜保存的时间（C09 审批样例的 submittedAt）。"""


def submitted() -> NotificationIntent:
    """E23 保存时：通知系统管理员。"""
    return NotificationIntent(event="approvalSubmitted", recipients=(ADMIN,), title=SUBMITTED_TITLE, body="",
                              link=APPROVAL_LINK)


def passed() -> NotificationIntent:
    """E23 最终批准后：通知发起人杨娜。"""
    return NotificationIntent(event="approvalPassed", recipients=(YANG_NA,), title=PASSED_TITLE, body="",
                              link=APPROVAL_LINK)


def save_command(request_key: str = "7d0c8a3e-2f4b-4c6d-9e1a-5b3c7d9e1f20") -> Command:
    """E23 的保存命令：物料 115 的执行价 75 → 60。"""
    return parse_wire(Command, {
        "requestKey": request_key, "page": "GOODS_PRICE_MANAGE", "operation": "COST_GOODS_PRICE.save",
        "documents": [{"entity": "COST_GOODS_PRICE", "master": {"op": "modify", "rowKey": "115", "changes": {"ZX_PRICE": "60"}},
                       "details": []}],
        "params": {}})


def snapshot(admin: bool) -> FakeConfigSnapshot:
    if admin:
        return FakeConfigSnapshot(version=13, role_code="ADMIN", role=RoleConfig(name="系统管理员", admin=True, pages={}))
    return FakeConfigSnapshot(version=13, role_code="008", role=RoleConfig(name="采购", admin=False, pages={}))


def context(user_id: str, now: datetime = T0, admin: bool | None = None) -> ExecutionContext:
    is_admin = user_id == ADMIN if admin is None else admin
    snap = snapshot(is_admin)
    names = {ADMIN: ("admin", "系统管理员"), YANG_NA: ("HY200702", "杨娜")}
    username, display = names.get(user_id, (f"user{user_id}", f"用户{user_id}"))
    who = Identity(user_id=user_id, username=username, display_name=display, department_id=None,
                   role_code=snap.role_code, session_id=f"s-{user_id}")
    return ExecutionContext(request_id="00000000-0000-4000-8000-0000000000aa", identity=who, config=snap,
                            config_version=snap.version, origin=Origin(kind="user", approval_id=None), now=now)


def state(*notifications: NotificationIntent, command: Command | None = None) -> CommandState:
    """写入管道走到"登记通知"阶段时的状态：前面的阶段（例如 approval 的触发审批）已经给出了通知意图。"""
    result = CommandState(command=command or save_command())
    result.notifications.extend(notifications)
    return result


def database() -> FakeUnitOfWorkFactory:
    """按迁移脚本建好 PF_DELIVERY、PF_INBOX 的替代事务。

    换成不带 `detect_types` 的 SQLite 引擎：日期时间由 SQLAlchemy 的 DateTime 类型转换；路由在线程池中访问数据库，
    所以允许跨线程使用。
    """
    factory = FakeUnitOfWorkFactory()
    factory.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with factory.engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    return factory


class InboxOutage:
    """让写站内通知（INSERT INTO PF_INBOX）的语句失败，模拟发送时站内通知写不进去。

    挂在引擎的 `before_cursor_execute` 上，是数据库层面的失败，被测代码不变。`down` 为 True 时全部失败；
    `ids` 中的投递编号失败（契约测试的"这条记录发送失败"）。
    """

    def __init__(self, engine: Engine) -> None:
        self.down = False
        self.ids: set[str] = set()
        event.listen(engine, "before_cursor_execute", self._check)

    def _check(self, _conn: Any, _cursor: Any, statement: str, parameters: Any, _context: Any, _many: bool) -> None:
        if not statement.lstrip().upper().startswith("INSERT INTO PF_INBOX"):
            return
        values = parameters.values() if isinstance(parameters, dict) else parameters
        if self.down or self.ids & {v for v in values if isinstance(v, str)}:
            raise RuntimeError("站内通知暂时写不进去")


@dataclass
class World:
    """一套模拟环境：替代事务、可控时钟、编号、实时推送和被测的 DeliveryService。"""

    factory: FakeUnitOfWorkFactory
    clock: FakeClock
    ids: FakeIdGenerator
    publisher: FakeRealtimePublisher
    outage: InboxOutage
    service: DeliveryService

    def delivery(self, delivery_id: str) -> dict[str, Any]:
        return delivery_row(self.factory, delivery_id)

    def deliveries(self) -> list[dict[str, Any]]:
        with self.factory.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(select(pf_delivery).order_by(pf_delivery.c.created_at,
                                                                                         pf_delivery.c.delivery_id))]

    def inbox_rows(self) -> list[dict[str, Any]]:
        with self.factory.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(select(pf_inbox).order_by(pf_inbox.c.delivery_id))]


def world(now: datetime = T0) -> World:
    factory = database()
    clock, ids, publisher = FakeClock(now), FakeIdGenerator(), FakeRealtimePublisher()
    return World(factory=factory, clock=clock, ids=ids, publisher=publisher, outage=InboxOutage(factory.engine),
                 service=DeliveryService(factory, publisher, clock, ids))


def delivery_row(factory: UnitOfWorkFactory, delivery_id: str) -> dict[str, Any]:
    with factory.begin() as uow:
        row = uow.connection.execute(select(pf_delivery).where(pf_delivery.c.delivery_id == delivery_id)).one()
        return dict(row._mapping)


def count(factory: FakeUnitOfWorkFactory, table: Any) -> int:
    with factory.engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def commit_registration(w: World, s: CommandState, ctx: ExecutionContext) -> list[str]:
    """在一个命令事务里执行"登记通知"阶段并提交（相当于写入管道第 11、12 阶段），返回登记的投递编号。"""
    stage = RegisterNotificationsStage(w.service)
    with w.factory.begin() as uow:
        if stage.applies(s, ctx):
            stage.run(uow, s, ctx)
        uow.commit()
    return list(s.delivery_ids)


def every_minute(start: datetime, minutes: int) -> Iterator[datetime]:
    """后台任务每分钟一轮的时间点：start、start+1 分钟……共 minutes+1 个。"""
    for i in range(minutes + 1):
        yield start + timedelta(minutes=i)
