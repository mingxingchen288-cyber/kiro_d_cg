"""后台重试任务（DL-03）：每分钟领取一轮到期的投递记录。由 assembly 在启动时放进后台线程运行（架构 6.1 第 5 步）。"""

from __future__ import annotations

import logging
import threading

from .service import DeliveryService

_log = logging.getLogger(__name__)

RETRY_EVERY_SECONDS = 60.0


def run_retry_loop(deliveries: DeliveryService, stop: threading.Event,
                   interval_seconds: float = RETRY_EVERY_SECONDS) -> None:
    """先执行一轮，之后每隔 `interval_seconds` 秒执行一轮，直到 `stop` 被设置。

    一轮出错（例如数据库暂时不可用）只记日志，下一轮照常执行，任务不退出。多个后端进程可以同时运行：
    每条记录用 `FOR UPDATE SKIP LOCKED` 领取，同一记录不会被两处同时发送。
    """
    while True:
        try:
            sent = deliveries.retry_due()
            if sent:
                _log.info("投递重试：本轮领取 %d 条", sent)
        except Exception as error:
            _log.error("投递重试本轮失败：%s", error)
        if stop.wait(interval_seconds):
            return
