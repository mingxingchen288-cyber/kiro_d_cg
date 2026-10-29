"""T-DL-1：登记通知和提交后立即发送（DL-01、DL-02、DL-05），用业务例子 E23 的数据做模拟验证。"""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa

from cost_platform.contracts.types import NotificationEvent, NotificationIntent, dump_wire
from cost_platform.delivery import DispatchStage, RegisterNotificationsStage
from cost_platform.delivery.tables import pf_delivery, pf_inbox

from .support import (
    ADMIN,
    APPROVAL_LINK,
    PASSED_TITLE,
    SUBMITTED_TITLE,
    T0,
    YANG_NA,
    commit_registration,
    context,
    count,
    passed,
    save_command,
    state,
    submitted,
    world,
)


def test_no_notification_intent_writes_no_delivery() -> None:
    """普通保存没有通知意图："登记通知"阶段不执行，不写投递记录，"投递"阶段也不执行。"""
    w = world()
    s = state()
    ctx = context(YANG_NA)
    assert RegisterNotificationsStage(w.service).applies(s, ctx) is False
    assert commit_registration(w, s, ctx) == []
    assert DispatchStage(w.service).applies(s, ctx) is False
    assert count(w.factory, pf_delivery) == 0


def test_e23_registered_in_command_transaction_and_sent_after_commit() -> None:
    """E23：杨娜保存，命令事务内为系统管理员登记一条 pending 投递记录；提交后立即发送：写站内通知、发布 notification。"""
    w = world()
    s = state(submitted())
    ctx = context(YANG_NA)
    [delivery_id] = commit_registration(w, s, ctx)

    registered = w.delivery(delivery_id)
    assert registered["status"] == "pending" and registered["attempts"] == 0
    assert registered["next_retry_at"] == T0 + timedelta(minutes=1)  # DL-01：登记时间加 1 分钟
    assert (registered["recipient"], registered["command_user"], registered["request_key"]) == (
        ADMIN, YANG_NA, save_command().request_key)
    assert (registered["event"], registered["title"], registered["link"]) == ("approvalSubmitted", SUBMITTED_TITLE,
                                                                             APPROVAL_LINK)

    w.clock.set(T0 + timedelta(seconds=1))
    stage = DispatchStage(w.service)
    assert stage.applies(s, ctx) is True
    stage.run(w.factory.units[-1], s, ctx)  # 提交后执行；命令事务已经结束，阶段不使用它

    sent = w.delivery(delivery_id)
    assert (sent["status"], sent["attempts"], sent["next_retry_at"], sent["last_error"]) == ("sent", 1, None, None)
    assert sent["sent_at"] == T0 + timedelta(seconds=1)
    [inbox] = w.inbox_rows()
    assert inbox == {"delivery_id": delivery_id, "user_id": ADMIN, "title": SUBMITTED_TITLE, "body": "",
                     "link": APPROVAL_LINK, "created_at": T0 + timedelta(seconds=1), "read_at": None}

    [event] = w.publisher.events
    assert isinstance(event, NotificationEvent)
    wire = dump_wire(NotificationEvent, event)
    assert wire["topic"] == "notification" and wire["audience"] == {"users": [ADMIN]}
    assert wire["payload"] == {"deliveryId": delivery_id, "title": SUBMITTED_TITLE, "body": "", "link": APPROVAL_LINK}


def test_e23_passed_notifies_applicant() -> None:
    """E23：最终批准的命令登记给杨娜的"已通过"通知，提交后杨娜收到；管理员之前那条不受影响。"""
    w = world()
    [first] = commit_registration(w, state(submitted()), context(YANG_NA))
    w.service.dispatch_now([first])

    w.clock.set(T0 + timedelta(hours=1))
    approve = state(passed(), command=save_command("9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"))
    [second] = commit_registration(w, approve, context(ADMIN, now=T0 + timedelta(hours=1)))
    w.service.dispatch_now([second])

    assert [(r["user_id"], r["title"]) for r in sorted(w.inbox_rows(), key=lambda r: r["created_at"])] == [
        (ADMIN, SUBMITTED_TITLE), (YANG_NA, PASSED_TITLE)]
    assert w.delivery(second)["command_user"] == ADMIN
    assert [e.audience.users for e in w.publisher.events] == [[ADMIN], [YANG_NA]]


def test_each_recipient_gets_its_own_delivery() -> None:
    """DL-01：一条通知有两个接收人时写两条投递记录，各自发送。
    假设的场景：本级审批人按角色配置，角色下有系统管理员（111）和胡奕清（114，cmx 的真实用户）两个账号。"""
    w = world()
    notice = NotificationIntent(event="approvalSubmitted", recipients=(ADMIN, "114"), title=SUBMITTED_TITLE, body="",
                                link=APPROVAL_LINK)
    ids = commit_registration(w, state(notice), context(YANG_NA))
    assert len(ids) == 2 and [w.delivery(i)["recipient"] for i in ids] == [ADMIN, "114"]
    w.service.dispatch_now(ids)
    assert sorted(r["user_id"] for r in w.inbox_rows()) == [ADMIN, "114"]
    assert all(w.delivery(i)["status"] == "sent" for i in ids)


def test_push_failure_does_not_change_send_result() -> None:
    """推送失败不影响发送结果；接收人不在线时写入站内通知即算发送成功（DL-02、DL-05）。"""
    w = world()
    [delivery_id] = commit_registration(w, state(submitted()), context(YANG_NA))
    w.publisher.break_channel()
    w.service.dispatch_now([delivery_id])
    assert w.delivery(delivery_id)["status"] == "sent"
    assert [r["delivery_id"] for r in w.inbox_rows()] == [delivery_id]
    assert w.publisher.events == [] and len(w.publisher.failed) == 1


def test_same_delivery_id_writes_one_inbox_row() -> None:
    """同一投递编号只写一条站内通知：重复调用 dispatch_now、后台任务又到时运行，都不再发送。"""
    w = world()
    [delivery_id] = commit_registration(w, state(submitted()), context(YANG_NA))
    w.service.dispatch_now([delivery_id])
    w.service.dispatch_now([delivery_id])
    w.clock.set(T0 + timedelta(minutes=1))
    assert w.service.retry_due() == 0
    assert count(w.factory, pf_inbox) == 1 and len(w.publisher.events) == 1
    assert w.delivery(delivery_id)["attempts"] == 1


def test_send_failure_is_recorded_and_committed_business_stays() -> None:
    """E23 最终批准：执行价 75 → 60 和给杨娜的通知在同一命令事务内提交；提交后写站内通知失败：
    dispatch_now 不抛出，执行价仍为 60，投递记录为 failed，记下错误，1 分钟后重试（DL-02、DL-03）。"""
    w = world()
    with w.factory.engine.begin() as conn:  # 物料清单（只取用到的列）：物料 115 执行价 75
        conn.execute(sa.text("CREATE TABLE T_COST_GOODS_PRICE (GOODSID INTEGER PRIMARY KEY, ZX_PRICE VARCHAR(20))"))
        conn.execute(sa.text("INSERT INTO T_COST_GOODS_PRICE VALUES (115, '75')"))
    ctx = context(ADMIN)
    s = state(passed())
    with w.factory.begin() as uow:  # 命令事务：写业务表，再登记通知，提交
        uow.connection.execute(sa.text("UPDATE T_COST_GOODS_PRICE SET ZX_PRICE = '60' WHERE GOODSID = 115"))
        RegisterNotificationsStage(w.service).run(uow, s, ctx)
        uow.commit()

    w.outage.down = True
    w.clock.set(T0 + timedelta(seconds=1))
    DispatchStage(w.service).run(w.factory.units[-1], s, ctx)

    with w.factory.engine.connect() as conn:
        assert conn.execute(sa.text("SELECT ZX_PRICE FROM T_COST_GOODS_PRICE WHERE GOODSID = 115")).scalar_one() == "60"
    failed = w.delivery(s.delivery_ids[0])
    assert (failed["status"], failed["attempts"]) == ("failed", 1)
    assert failed["next_retry_at"] == T0 + timedelta(seconds=1) + timedelta(minutes=1)
    assert failed["last_error"] == "RuntimeError：站内通知暂时写不进去"
    assert w.inbox_rows() == [] and w.publisher.events == []


def test_rolled_back_command_keeps_no_delivery() -> None:
    """业务回滚时投递记录不保留：登记在命令事务内，没有提交就回滚。真实验证见 test_oracle.py。"""
    w = world()
    s = state(submitted())
    with w.factory.begin() as uow:
        RegisterNotificationsStage(w.service).run(uow, s, context(YANG_NA))
    assert len(s.delivery_ids) == 1
    assert count(w.factory, pf_delivery) == 0
