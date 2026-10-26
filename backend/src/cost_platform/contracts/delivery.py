"""通知投递：在业务事务内登记投递意图，提交后由投递器发送，可追踪、可重试。

只有操作确实产生通知时才登记；普通保存不写投递记录。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class DeliveryChannel(StrEnum):
    INBOX = "inbox"
    """站内通知。"""
    REALTIME = "realtime"
    """实时推送（WebSocket）。"""


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class DeliveryIntent:
    delivery_id: str
    """投递编号；接收端按它去重，重试不会产生两条通知。"""
    command_request_key: str | None
    channel: DeliveryChannel
    recipient: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    intent: DeliveryIntent
    status: DeliveryStatus
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    created_at: datetime
