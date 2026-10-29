"""登记、发送、重试和放弃通知，维护站内通知（delivery DL-01–DL-05，架构 10.8）。

发送渠道只有站内通知：发送 = 写 PF_INBOX，提交后经 realtime 推送 `notification`（C10）。模块说明没有其他渠道，
旧系统也没有（旧系统的"消息中心"直接查审批表，见 `.reports/modules/delivery/findings.md`）。

- 登记（DL-01）在命令事务内执行，不提交：业务回滚时投递记录一起回滚。
- 每次发送在 delivery 自己的事务里：`SELECT … FOR UPDATE SKIP LOCKED` 领取记录 → 写站内通知 → 标为 sent → 提交，
  提交后推送。推送失败只记日志，不影响发送结果；接收人不在线时，写入站内通知即算发送成功（DL-05）。
- 发送失败时另开一个事务记下错误、发送次数和下次重试时间（DL-02、DL-03）；`dispatch_now` 和 `retry_due`
  都不向调用方抛出发送失败，已经提交的业务不受影响。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from cost_platform.contracts.ports import Clock, IdGenerator, RealtimePublisher, UnitOfWork, UnitOfWorkFactory
from cost_platform.contracts.types import (
    DeliveryList,
    DeliveryRow,
    ErrorCode,
    InboxItem,
    InboxList,
    NotificationEvent,
    NotificationIntent,
    NotificationPayload,
    PlatformError,
    UsersAudience,
)

from .store import ClaimedDelivery, DeliveryStore, NewDelivery

_log = logging.getLogger(__name__)

FIRST_TRY_DELAY = timedelta(minutes=1)
"""DL-01：登记时下次重试时间为登记时间加 1 分钟；提交后没能立即发送时，后台任务到时补发。"""

RETRY_INTERVALS = tuple(timedelta(minutes=m) for m in (1, 2, 4, 8, 16))
"""DL-03：首次发送失败后最多重试 5 次，第 n 次失败后隔 RETRY_INTERVALS[n-1] 再试；第 5 次重试（第 6 次发送）失败后放弃。"""

RETRY_BATCH = 500
"""后台任务每轮最多领取的记录数；没领完的下一轮（1 分钟后）接着发。"""


def after_failure(attempts: int, now: datetime) -> tuple[str, datetime | None]:
    """第 `attempts` 次发送失败后的状态和下次重试时间（DL-03）。"""
    if attempts > len(RETRY_INTERVALS):
        return "abandoned", None
    return "failed", now + RETRY_INTERVALS[attempts - 1]


def _describe(error: BaseException) -> str:
    """记进 last_error 的错误说明。经 db-core 的事务出来的数据库错误已是 PlatformError，不含 ORA- 原文（DB-02）。"""
    if isinstance(error, PlatformError):
        return f"{error.code.value}：{error.message}"
    return f"{type(error).__name__}：{error}"


class DeliveryService:
    """`DeliveryDispatcher`（C08 第 10 节），以及登记、后台重试、重新排队和 C09 第 7 节接口用到的读写。"""

    def __init__(self, uow_factory: UnitOfWorkFactory, publisher: RealtimePublisher, clock: Clock, ids: IdGenerator,
                 store: DeliveryStore | None = None, batch_size: int = RETRY_BATCH) -> None:
        self._uow = uow_factory
        self._publisher = publisher
        self._clock = clock
        self._ids = ids
        self._store = store or DeliveryStore()
        self._batch = batch_size

    # ------------------------------------------------------------ DL-01 登记

    def register(self, uow: UnitOfWork, command_user: str, request_key: str,
                 notifications: Sequence[NotificationIntent], now: datetime) -> list[str]:
        """在命令事务 `uow` 内为每条通知的每个接收人写一条 pending 的投递记录，返回投递编号；不提交。"""
        delivery_ids: list[str] = []
        for intent in notifications:
            for recipient in intent.recipients:
                delivery_id = self._ids.uuid()
                self._store.insert(uow, NewDelivery(
                    delivery_id=delivery_id, command_user=command_user, request_key=request_key, event=intent.event,
                    recipient=recipient, title=intent.title, body=intent.body, link=intent.link, created_at=now,
                    next_retry_at=now + FIRST_TRY_DELAY))
                delivery_ids.append(delivery_id)
        return delivery_ids

    # ------------------------------------------------------------ DL-02 提交后立即发送

    def dispatch_now(self, delivery_ids: list[str]) -> None:
        """提交后调用；逐条在自己的事务里发送。失败只记录，由后台任务重试。"""
        for delivery_id in delivery_ids:
            self._attempt(delivery_id, due_by=None)

    # ------------------------------------------------------------ DL-03 后台重试

    def retry_due(self) -> int:
        """后台任务的一轮：领取到期的 pending、failed 记录逐条发送，返回这一轮实际领取到的条数。"""
        now = self._clock.now()
        with self._uow.begin() as uow:
            due = self._store.due_ids(uow, now, self._batch)
        return sum(1 for delivery_id in due if self._attempt(delivery_id, due_by=now))

    def _attempt(self, delivery_id: str, due_by: datetime | None) -> bool:
        """发送一条：领取不到（别处正在发送、已经发送或还没到期）时返回 False。"""
        now = self._clock.now()
        try:
            with self._uow.begin() as uow:
                claimed = self._store.claim(uow, delivery_id, due_by)
                if claimed is None:
                    return False
                self._store.write_inbox(uow, claimed, now)
                self._store.mark_sent(uow, delivery_id, claimed.attempts + 1, now)
                uow.commit()
        except Exception as error:  # 发送失败只记录（C08 第 10 节），不影响已经提交的业务
            _log.warning("投递 %s 发送失败：%s", delivery_id, error)
            self._record_failure(delivery_id, error, now)
            return True
        self._push(claimed)
        return True

    def _record_failure(self, delivery_id: str, error: BaseException, now: datetime) -> None:
        try:
            with self._uow.begin() as uow:
                attempts = self._store.claim_attempts(uow, delivery_id)
                if attempts is None:
                    return
                status, next_retry_at = after_failure(attempts + 1, now)
                self._store.mark_failed(uow, delivery_id, attempts + 1, status, next_retry_at, _describe(error))
                uow.commit()
        except Exception as again:  # 数据库不可用时记不下来：记录保持原状态，后台任务到时照样领取
            _log.error("投递 %s 记录发送失败时出错：%s", delivery_id, again)

    def _push(self, record: ClaimedDelivery) -> None:
        """经 realtime 推送（C10）。推送失败不影响发送结果（DL-02）；接收人不在线也算发送成功（DL-05）。"""
        event = NotificationEvent(
            event_id=self._ids.uuid(), topic="notification", audience=UsersAudience(users=[record.recipient]),
            payload=NotificationPayload(delivery_id=record.delivery_id, title=record.title, body=record.body,
                                        link=record.link))
        try:
            self._publisher.publish(event)
        except Exception as error:
            _log.warning("投递 %s 推送失败：%s", record.delivery_id, error)

    # ------------------------------------------------------------ DL-04 管理

    def list_deliveries(self, status: str | None, start: int, end: int) -> DeliveryList:
        with self._uow.begin() as uow:
            rows, total = self._store.deliveries(uow, status, start, end)
        return DeliveryList(rows=[DeliveryRow(delivery_id=r.delivery_id, recipient=r.recipient, status=r.status,
                                              attempts=r.attempts, next_retry_at=r.next_retry_at, last_error=r.last_error)
                                  for r in rows], total=total)

    def requeue(self, delivery_id: str, now: datetime) -> None:
        """把 abandoned 的记录重新排队：改回 pending、发送次数清零，下一轮后台任务发送，失败后重新按 1、2、4、8、16 分钟重试。"""
        with self._uow.begin() as uow:
            if self._store.requeue(uow, delivery_id, now):
                uow.commit()
                return
            status = self._store.status(uow, delivery_id)
        if status is None:
            raise PlatformError(ErrorCode.NOT_FOUND, "投递记录不存在")
        raise PlatformError(ErrorCode.VALIDATION_FAILED, f"只有已放弃的投递记录可以重新排队，这条记录的状态为 {status}")

    # ------------------------------------------------------------ 站内通知

    def inbox(self, user_id: str, unread_only: bool, start: int, end: int) -> InboxList:
        with self._uow.begin() as uow:
            rows, total, unread = self._store.inbox(uow, user_id, unread_only, start, end)
        return InboxList(rows=[InboxItem(delivery_id=r.delivery_id, title=r.title, body=r.body, link=r.link,
                                         created_at=r.created_at, read=r.read) for r in rows],
                         total=total, unread=unread)

    def mark_read(self, user_id: str, delivery_id: str, now: datetime) -> None:
        """把当前用户的一条站内通知标为已读；已读的不再改。"""
        with self._uow.begin() as uow:
            self._store.mark_read(uow, user_id, delivery_id, now)
            uow.commit()
