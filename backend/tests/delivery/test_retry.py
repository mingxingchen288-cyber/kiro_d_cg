"""T-DL-2：后台重试、放弃和重新排队（DL-03、DL-04），可控时钟下的模拟验证。

场景用 E23 最终批准后给杨娜的"已通过"通知；发送失败用 `InboxOutage` 模拟（写站内通知的语句失败）。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from cost_platform.delivery import RETRY_INTERVALS, after_failure, run_retry_loop
from cost_platform.delivery.tables import pf_inbox

from .support import T0, YANG_NA, World, commit_registration, context, count, every_minute, passed, state, world


def _minutes(m: int) -> datetime:
    return T0 + timedelta(minutes=m)


def _run_every_minute_until_abandoned(w: World, delivery_id: str) -> list[tuple[datetime, int, str, datetime | None]]:
    """发送一直失败：提交后立即发送一次，之后后台任务每分钟一轮；返回每次实际发送时的（时间、次数、状态、下次重试时间）。"""
    w.outage.down = True
    history = []
    w.service.dispatch_now([delivery_id])
    row = w.delivery(delivery_id)
    history.append((T0, row["attempts"], row["status"], row["next_retry_at"]))
    for now in every_minute(_minutes(1), 34):
        w.clock.set(now)
        w.service.retry_due()
        row = w.delivery(delivery_id)
        if row["attempts"] != history[-1][1]:
            history.append((now, row["attempts"], row["status"], row["next_retry_at"]))
    return history


def test_intervals_double_and_fifth_retry_failure_abandons() -> None:
    """首次发送失败后依次在 1、2、4、8、16 分钟后重试；第 5 次重试仍失败时为 abandoned（DL-03）。"""
    w = world()
    [delivery_id] = commit_registration(w, state(passed()), context(YANG_NA))
    history = _run_every_minute_until_abandoned(w, delivery_id)
    assert history == [
        (_minutes(0), 1, "failed", _minutes(1)),
        (_minutes(1), 2, "failed", _minutes(3)),
        (_minutes(3), 3, "failed", _minutes(7)),
        (_minutes(7), 4, "failed", _minutes(15)),
        (_minutes(15), 5, "failed", _minutes(31)),
        (_minutes(31), 6, "abandoned", None),
    ]
    assert w.delivery(delivery_id)["last_error"] == "RuntimeError：站内通知暂时写不进去"
    assert w.inbox_rows() == [] and w.publisher.events == []


def test_after_failure_table() -> None:
    assert [m.total_seconds() / 60 for m in RETRY_INTERVALS] == [1, 2, 4, 8, 16]
    assert [after_failure(n, T0) for n in range(1, 7)] == [
        ("failed", _minutes(1)), ("failed", _minutes(2)), ("failed", _minutes(4)), ("failed", _minutes(8)),
        ("failed", _minutes(16)), ("abandoned", None)]


def test_requeued_delivery_is_sent_again() -> None:
    """管理员把放弃的记录重新排队：改回 pending、次数清零，下一轮后台任务发送成功（DL-04）。"""
    w = world()
    [delivery_id] = commit_registration(w, state(passed()), context(YANG_NA))
    _run_every_minute_until_abandoned(w, delivery_id)

    w.outage.down = False
    w.service.requeue(delivery_id, _minutes(40))
    queued = w.delivery(delivery_id)
    assert (queued["status"], queued["attempts"], queued["next_retry_at"]) == ("pending", 0, _minutes(40))

    w.clock.set(_minutes(40))
    assert w.service.retry_due() == 1
    sent = w.delivery(delivery_id)
    assert (sent["status"], sent["attempts"], sent["sent_at"]) == ("sent", 1, _minutes(40))
    assert [r["user_id"] for r in w.inbox_rows()] == [YANG_NA]
    assert [e.payload.delivery_id for e in w.publisher.events] == [delivery_id]


def test_requeued_delivery_retries_from_one_minute_again() -> None:
    """重新排队后再次进入重试：又失败时按第 1 次失败处理，1 分钟后重试。"""
    w = world()
    [delivery_id] = commit_registration(w, state(passed()), context(YANG_NA))
    _run_every_minute_until_abandoned(w, delivery_id)
    w.service.requeue(delivery_id, _minutes(40))
    w.clock.set(_minutes(40))
    w.service.retry_due()
    again = w.delivery(delivery_id)
    assert (again["status"], again["attempts"], again["next_retry_at"]) == ("failed", 1, _minutes(41))


def test_process_exit_after_commit_is_sent_one_minute_later() -> None:
    """进程在提交后、发送前退出（dispatch_now 没有执行）：登记 1 分钟后，后台任务补发（DL-01）。"""
    w = world()
    [delivery_id] = commit_registration(w, state(passed()), context(YANG_NA))

    w.clock.set(T0 + timedelta(seconds=30))
    assert w.service.retry_due() == 0
    assert w.delivery(delivery_id)["status"] == "pending"

    w.clock.set(_minutes(1))
    assert w.service.retry_due() == 1
    assert w.delivery(delivery_id)["status"] == "sent"
    assert count(w.factory, pf_inbox) == 1 and len(w.publisher.events) == 1


def test_retry_loop_runs_a_round_before_waiting() -> None:
    """后台任务的循环：先执行一轮再等待；`stop` 已设置时执行完这一轮就返回。"""
    w = world()
    [delivery_id] = commit_registration(w, state(passed()), context(YANG_NA))
    w.clock.set(_minutes(1))
    stop = threading.Event()
    stop.set()
    run_retry_loop(w.service, stop, interval_seconds=0.01)
    assert w.delivery(delivery_id)["status"] == "sent"
