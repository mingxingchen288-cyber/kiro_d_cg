"""`RealtimePublisher` 的实现（C08 第 11 节、RT-02）。"""

from __future__ import annotations

import logging

from cost_platform.contracts.types import RealtimeEvent

from .channel import EventChannel
from .messages import encode_event

logger = logging.getLogger("cost_platform.realtime")


class ChannelPublisher:
    """把事件写入频道（Redis 时为一条 PUBLISH），不直接推给连接：本进程的连接也由订阅任务从频道收到后推送。

    RT-02：发布失败只记日志，不抛出，不影响调用方已经提交的事务；这条事件不再补发。
    """

    def __init__(self, channel: EventChannel) -> None:
        self._channel = channel

    def publish(self, event: RealtimeEvent) -> None:
        try:
            self._channel.publish(encode_event(event))
        except Exception:
            logger.warning("实时事件发布失败，没有推送：topic=%s eventId=%s", event.topic, event.event_id, exc_info=True)
