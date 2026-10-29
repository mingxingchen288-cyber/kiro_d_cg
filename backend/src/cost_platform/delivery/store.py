"""投递记录和站内通知的 SQL（表见 `tables.py`）。每个方法在调用方给出的事务（`UnitOfWork`）中执行，不提交。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, insert, select, update

from cost_platform.contracts.ports import UnitOfWork

from .tables import pf_delivery, pf_inbox

SENDABLE = ("pending", "failed")
"""后台重试任务领取的状态（DL-03）。"""


@dataclass(frozen=True)
class NewDelivery:
    delivery_id: str
    command_user: str
    request_key: str
    event: str
    recipient: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    next_retry_at: datetime


@dataclass(frozen=True)
class ClaimedDelivery:
    """领取到、准备发送的一条投递记录。"""

    delivery_id: str
    recipient: str
    title: str
    body: str
    link: str | None
    attempts: int


@dataclass(frozen=True)
class DeliveryRecord:
    delivery_id: str
    recipient: str
    status: str
    attempts: int
    next_retry_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class InboxRecord:
    delivery_id: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read: bool


def _text(value: object) -> str:
    """Oracle 把空串存为 NULL，读出时还原为空串；CLOB 读出为字符串（SQLAlchemy 的 oracledb 方言默认转换）。"""
    return "" if value is None else str(value)


class DeliveryStore:
    # ------------------------------------------------------------ 登记（DL-01，在命令事务内）

    @staticmethod
    def insert(uow: UnitOfWork, record: NewDelivery) -> None:
        uow.connection.execute(insert(pf_delivery).values(
            delivery_id=record.delivery_id, command_user=record.command_user, request_key=record.request_key,
            event=record.event, recipient=record.recipient, title=record.title, body=record.body, link=record.link,
            status="pending", attempts=0, next_retry_at=record.next_retry_at, last_error=None,
            created_at=record.created_at, sent_at=None))

    # ------------------------------------------------------------ 领取和发送（DL-02、DL-03）

    @staticmethod
    def due_ids(uow: UnitOfWork, now: datetime, limit: int) -> list[str]:
        """到期的 pending、failed 记录，按下次重试时间排列；只读，领取时再加锁。"""
        query = (select(pf_delivery.c.delivery_id)
                 .where(pf_delivery.c.status.in_(SENDABLE), pf_delivery.c.next_retry_at <= now)
                 .order_by(pf_delivery.c.next_retry_at, pf_delivery.c.delivery_id).limit(limit))
        return [row.delivery_id for row in uow.connection.execute(query)]

    @staticmethod
    def claim(uow: UnitOfWork, delivery_id: str, due_by: datetime | None) -> ClaimedDelivery | None:
        """`SELECT … FOR UPDATE SKIP LOCKED` 领取一条记录：别处正在发送（行已加锁）或已经不需要发送时为 None。

        `due_by` 为 None 时是提交后立即发送，只领取 pending；否则是后台重试，领取到期的 pending 和 failed。
        """
        query = select(pf_delivery.c.delivery_id, pf_delivery.c.recipient, pf_delivery.c.title, pf_delivery.c.body,
                       pf_delivery.c.link, pf_delivery.c.attempts).where(pf_delivery.c.delivery_id == delivery_id)
        if due_by is None:
            query = query.where(pf_delivery.c.status == "pending")
        else:
            query = query.where(pf_delivery.c.status.in_(SENDABLE), pf_delivery.c.next_retry_at <= due_by)
        row = uow.connection.execute(query.with_for_update(skip_locked=True)).first()
        if row is None:
            return None
        return ClaimedDelivery(delivery_id=row.delivery_id, recipient=row.recipient, title=row.title,
                               body=_text(row.body), link=row.link, attempts=int(row.attempts))

    @staticmethod
    def claim_attempts(uow: UnitOfWork, delivery_id: str) -> int | None:
        """记录发送失败前领取：还是 pending 或 failed 时返回已做过的发送次数；已发送、已放弃或正被别处发送时为 None。"""
        query = (select(pf_delivery.c.attempts)
                 .where(pf_delivery.c.delivery_id == delivery_id, pf_delivery.c.status.in_(SENDABLE))
                 .with_for_update(skip_locked=True))
        row = uow.connection.execute(query).first()
        return None if row is None else int(row.attempts)

    @staticmethod
    def write_inbox(uow: UnitOfWork, record: ClaimedDelivery, now: datetime) -> None:
        """写站内通知；同一投递编号已经有站内通知时不再写。"""
        exists = select(pf_inbox.c.delivery_id).where(pf_inbox.c.delivery_id == record.delivery_id)
        if uow.connection.execute(exists).first() is not None:
            return
        uow.connection.execute(insert(pf_inbox).values(
            delivery_id=record.delivery_id, user_id=record.recipient, title=record.title, body=record.body,
            link=record.link, created_at=now, read_at=None))

    @staticmethod
    def mark_sent(uow: UnitOfWork, delivery_id: str, attempts: int, now: datetime) -> None:
        uow.connection.execute(update(pf_delivery).where(pf_delivery.c.delivery_id == delivery_id).values(
            status="sent", attempts=attempts, next_retry_at=None, sent_at=now))

    @staticmethod
    def mark_failed(uow: UnitOfWork, delivery_id: str, attempts: int, status: str, next_retry_at: datetime | None,
                    error: str) -> None:
        uow.connection.execute(update(pf_delivery).where(pf_delivery.c.delivery_id == delivery_id).values(
            status=status, attempts=attempts, next_retry_at=next_retry_at, last_error=error[:2000]))

    # ------------------------------------------------------------ 管理（DL-04）

    @staticmethod
    def requeue(uow: UnitOfWork, delivery_id: str, now: datetime) -> bool:
        """已放弃的记录改回 pending，发送次数清零，下次重试时间为现在；不是 abandoned 时不改，返回 False。"""
        result = uow.connection.execute(
            update(pf_delivery)
            .where(pf_delivery.c.delivery_id == delivery_id, pf_delivery.c.status == "abandoned")
            .values(status="pending", attempts=0, next_retry_at=now))
        return result.rowcount == 1

    @staticmethod
    def status(uow: UnitOfWork, delivery_id: str) -> str | None:
        row = uow.connection.execute(
            select(pf_delivery.c.status).where(pf_delivery.c.delivery_id == delivery_id)).first()
        return None if row is None else str(row.status)

    @staticmethod
    def deliveries(uow: UnitOfWork, status: str | None, start: int, end: int) -> tuple[list[DeliveryRecord], int]:
        """投递记录，新登记的在前；`status` 为 None 时不按状态筛选。"""
        where: list[ColumnElement[bool]] = [] if status is None else [pf_delivery.c.status == status]
        query = (select(pf_delivery.c.delivery_id, pf_delivery.c.recipient, pf_delivery.c.status, pf_delivery.c.attempts,
                        pf_delivery.c.next_retry_at, pf_delivery.c.last_error)
                 .where(*where)
                 .order_by(pf_delivery.c.created_at.desc(), pf_delivery.c.delivery_id.desc())
                 .offset(start).limit(max(end - start, 0)))
        rows = [DeliveryRecord(delivery_id=r.delivery_id, recipient=r.recipient, status=r.status, attempts=int(r.attempts),
                               next_retry_at=r.next_retry_at, last_error=r.last_error)
                for r in uow.connection.execute(query)]
        total = uow.connection.execute(select(func.count()).select_from(pf_delivery).where(*where)).scalar_one()
        return rows, int(total)

    # ------------------------------------------------------------ 站内通知（C09 第 7 节）

    @staticmethod
    def inbox(uow: UnitOfWork, user_id: str, unread_only: bool, start: int, end: int) -> tuple[list[InboxRecord], int, int]:
        """当前用户的站内通知，新的在前；返回（这一页、筛选后的总数、未读数）。"""
        mine: list[ColumnElement[bool]] = [pf_inbox.c.user_id == user_id]
        unread = [*mine, pf_inbox.c.read_at.is_(None)]
        where = unread if unread_only else mine
        query = (select(pf_inbox.c.delivery_id, pf_inbox.c.title, pf_inbox.c.body, pf_inbox.c.link,
                        pf_inbox.c.created_at, pf_inbox.c.read_at)
                 .where(*where)
                 .order_by(pf_inbox.c.created_at.desc(), pf_inbox.c.delivery_id.desc())
                 .offset(start).limit(max(end - start, 0)))
        rows = [InboxRecord(delivery_id=r.delivery_id, title=r.title, body=_text(r.body), link=r.link,
                            created_at=r.created_at, read=r.read_at is not None)
                for r in uow.connection.execute(query)]

        def count(conditions: Sequence[ColumnElement[bool]]) -> int:
            return int(uow.connection.execute(select(func.count()).select_from(pf_inbox).where(*conditions)).scalar_one())

        return rows, count(where), count(unread)

    @staticmethod
    def mark_read(uow: UnitOfWork, user_id: str, delivery_id: str, now: datetime) -> None:
        uow.connection.execute(
            update(pf_inbox)
            .where(pf_inbox.c.delivery_id == delivery_id, pf_inbox.c.user_id == user_id, pf_inbox.c.read_at.is_(None))
            .values(read_at=now))
