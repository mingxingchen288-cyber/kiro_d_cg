"""delivery 的真实验证（d_cg）。本次没有运行，由合并后统一运行。

前提：已执行 `platform db upgrade`，迁移目录包含 `cost_platform.delivery.migrations`（dl_0001 建 PF_DELIVERY、PF_INBOX）。
测试数据的投递编号以 `00000000-0000-4000-8000-` 开头（替代编号生成器和契约测试的编号），每个测试前后删除；
接收人用 E23 的真实用户 111（系统管理员）、112（杨娜），断言只看本测试的投递编号。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Engine, delete, select

from cost_platform.assembly.settings import Settings
from cost_platform.contracts.fakes import FakeClock, FakeIdGenerator, FakeRealtimePublisher
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.delivery import DeliveryService, RegisterNotificationsStage
from cost_platform.delivery.tables import pf_delivery, pf_inbox

from ..contracts.test_delivery_dispatcher import DeliveryDispatcherContract
from .support import ADMIN, SUBMITTED_TITLE, T0, YANG_NA, InboxOutage, context, delivery_row, state, submitted
from .test_contracts import DeliveryServiceHarness, register_committed

pytestmark = pytest.mark.oracle

TEST_IDS = "00000000-0000-4000-8000-%"


def _engine() -> Engine:
    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


def _cleanup(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(delete(pf_inbox).where(pf_inbox.c.delivery_id.like(TEST_IDS)))
        conn.execute(delete(pf_delivery).where(pf_delivery.c.delivery_id.like(TEST_IDS)))


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = _engine()
    _cleanup(engine)
    yield engine
    _cleanup(engine)
    engine.dispose()


def _service(engine: Engine, start: int = 0xD1E500000000) -> tuple[DeliveryService, FakeRealtimePublisher, FakeClock]:
    clock, publisher = FakeClock(T0), FakeRealtimePublisher()
    return DeliveryService(OracleUnitOfWorkFactory(engine), publisher, clock, FakeIdGenerator(start)), publisher, clock


class TestOracleDeliveryDispatcher(DeliveryDispatcherContract):
    @pytest.fixture
    def harness(self, engine: Engine) -> DeliveryServiceHarness:
        service, _, _ = _service(engine)
        return DeliveryServiceHarness(OracleUnitOfWorkFactory(engine), InboxOutage(engine), service)


def test_rolled_back_command_keeps_no_delivery(engine: Engine) -> None:
    """T-DL-1 真实验证：业务回滚时投递记录不保留。"""
    service, _, _ = _service(engine)
    s = state(submitted())
    with OracleUnitOfWorkFactory(engine).begin() as uow:  # 命令事务没有提交（例如后面的阶段失败），退出时回滚
        RegisterNotificationsStage(service).run(uow, s, context(YANG_NA))
    with engine.connect() as conn:
        assert conn.execute(select(pf_delivery.c.delivery_id).where(pf_delivery.c.delivery_id.in_(s.delivery_ids))).all() == []


def test_e23_on_oracle(engine: Engine) -> None:
    """E23 在 d_cg 上：登记并提交，立即发送，系统管理员的站内通知可以读到（正文空串在 Oracle 中存为 NULL，读出为空串），标为已读。"""
    factory = OracleUnitOfWorkFactory(engine)
    service, publisher, clock = _service(engine)
    s = state(submitted())
    with factory.begin() as uow:
        RegisterNotificationsStage(service).run(uow, s, context(YANG_NA))
        uow.commit()
    [delivery_id] = s.delivery_ids
    clock.set(T0 + timedelta(seconds=1))
    service.dispatch_now([delivery_id])

    row = delivery_row(factory, delivery_id)
    assert (row["status"], row["attempts"], row["next_retry_at"]) == ("sent", 1, None)
    mine = [r for r in service.inbox(ADMIN, True, 0, 200).rows if r.delivery_id == delivery_id]
    assert [(r.title, r.body, r.link, r.read) for r in mine] == [(SUBMITTED_TITLE, "", "/approval/203", False)]
    assert [e.payload.delivery_id for e in publisher.events] == [delivery_id]

    service.mark_read(ADMIN, delivery_id, T0 + timedelta(minutes=1))
    assert [r.read for r in service.inbox(ADMIN, False, 0, 200).rows if r.delivery_id == delivery_id] == [True]
    listed = [r for r in service.list_deliveries("sent", 0, 200).rows if r.delivery_id == delivery_id]
    assert [(r.recipient, r.attempts) for r in listed] == [(ADMIN, 1)]


def test_two_workers_send_each_record_once(engine: Engine) -> None:
    """T-DL-2 真实验证：两个后台任务（各自的连接池，相当于两个进程）同时领取同一批到期记录，每条只发送一次。"""
    count = 30
    ids = [f"00000000-0000-4000-8000-0000000c{i:04x}" for i in range(count)]
    factory = OracleUnitOfWorkFactory(engine)
    for delivery_id in ids:  # 已提交、没有立即发送的记录，下次重试时间为 T0，两个任务在 T0 后 1 分钟运行时都已到期
        register_committed(factory, delivery_id)

    other = _engine()
    try:
        a, events_a, clock_a = _service(engine, 0xA00000000000)
        b, events_b, clock_b = _service(other, 0xB00000000000)
        clock_a.set(T0 + timedelta(minutes=1))
        clock_b.set(T0 + timedelta(minutes=1))
        start = threading.Barrier(2)
        claimed: list[int] = []

        def run(service: DeliveryService) -> None:
            start.wait(10)
            claimed.append(service.retry_due())

        threads = [threading.Thread(target=run, args=(s,)) for s in (a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
    finally:
        other.dispose()

    assert sum(claimed) == count
    pushed = [e.payload.delivery_id for e in events_a.events + events_b.events]
    assert sorted(pushed) == sorted(ids)
    with engine.connect() as conn:
        inbox = conn.execute(select(pf_inbox.c.delivery_id).where(pf_inbox.c.delivery_id.in_(ids))).scalars().all()
        sent = conn.execute(select(pf_delivery.c.status, pf_delivery.c.attempts)
                            .where(pf_delivery.c.delivery_id.in_(ids))).all()
    assert sorted(inbox) == sorted(ids)
    assert sorted(set(sent)) == [("sent", 1)]
