"""实时推送事件。后端各进程经 Redis 发布订阅转发，再推给相关的 WebSocket 连接。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class RealtimeTopic(StrEnum):
    CONFIG_CHANGED = "config.changed"
    """配置发布了新版本；payload 含受影响的页面和新版本号。"""
    SESSION_REVOKED = "session.revoked"
    NOTIFICATION = "notification"
    """站内通知（投递器发送）。"""


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    topic: RealtimeTopic
    payload: Mapping[str, Any] = field(default_factory=dict)
    roles: tuple[str, ...] = ()
    """只推给这些角色的连接；为空表示不按角色过滤。"""
    pages: tuple[str, ...] = ()
    """只推给打开了这些页面的连接；为空表示不按页面过滤。"""
    users: tuple[str, ...] = ()
    """只推给这些用户；为空表示不按用户过滤。"""
    event_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
