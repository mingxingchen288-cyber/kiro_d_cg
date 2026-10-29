"""通知投递和站内通知（docs/模块/delivery.md）。

assembly 的接法（架构 6.1、第 7 节）：
- `DeliveryService(uow_factory, realtime_publisher, clock, ids)`，它就是 `DeliveryDispatcher`；
- 把 `RegisterNotificationsStage(service)`（第 11 阶段，命令事务内）和 `DispatchStage(service)`（第 13 阶段，提交后）注册进写入管道；
- 挂载 `delivery_router(service, context)`（C09 第 7 节）；
- 启动后台任务：在线程中运行 `run_retry_loop(service, stop_event)`；
- 平台表迁移目录：`cost_platform.delivery.migrations`。
"""

from .router import delivery_router
from .service import FIRST_TRY_DELAY, RETRY_INTERVALS, DeliveryService, after_failure
from .stages import DispatchStage, RegisterNotificationsStage
from .worker import run_retry_loop

__all__ = [
    "FIRST_TRY_DELAY",
    "RETRY_INTERVALS",
    "DeliveryService",
    "DispatchStage",
    "RegisterNotificationsStage",
    "after_failure",
    "delivery_router",
    "run_retry_loop",
]
