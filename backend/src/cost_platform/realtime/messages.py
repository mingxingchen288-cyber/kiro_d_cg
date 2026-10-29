"""C10 的消息与 JSON 文本之间的转换。类型都在 contracts（types.py 的 C10 一节），这里不另定义。"""

from __future__ import annotations

import json
from typing import Any

from cost_platform.contracts.types import (
    ChannelEvent,
    ClientMessage,
    PongMessage,
    PushConfigChanged,
    PushNotification,
    PushSessionRevoked,
    RealtimeEvent,
    ServerMessage,
    dump_wire,
    parse_wire,
)

_PUSH: dict[str, Any] = {
    "config.changed": PushConfigChanged,
    "notification": PushNotification,
    "session.revoked": PushSessionRevoked,
}


def _text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def encode_event(event: RealtimeEvent) -> str:
    """频道消息（C10 第 1 节）。"""
    return _text(dump_wire(ChannelEvent, event))


def decode_event(message: str) -> RealtimeEvent:
    """解析频道消息；不符合 C10 时抛 pydantic.ValidationError 或 ValueError。"""
    return parse_wire(ChannelEvent, json.loads(message))  # type: ignore[no-any-return]


def push_text(event: RealtimeEvent) -> str:
    """推给浏览器的消息（C10 第 2 节）：`topic`、`eventId`、`payload`，不带 audience。"""
    push = _PUSH[event.topic](topic=event.topic, event_id=event.event_id, payload=event.payload)
    return _text(dump_wire(ServerMessage, push))


PONG = _text(dump_wire(ServerMessage, PongMessage(type="pong")))


def decode_client(text: str) -> Any:
    """解析浏览器发来的消息（subscribe、unsubscribe、ping）；不符合 C10 时抛 pydantic.ValidationError 或 ValueError。"""
    return parse_wire(ClientMessage, json.loads(text))
