"""通知投递和站内通知（docs/模块/delivery.md）。

接线见 `plugin.py` 的 `DeliveryPlugin`（plugin-spec 第 2 节）：
- `DeliveryService(uow_factory, realtime_publisher, clock, ids)`，它就是 `DeliveryDispatcher`，orchestration 提交后调用；
- 管道阶段只注册 `RegisterNotificationsStage(service)`（"登记通知"，命令事务内）；`DispatchStage` 不注册
  （"投递"不是管道位置，见 plugin-spec 第 3 节），保留给单独使用；
- 路由 `delivery_router(service, context)`（C09 第 7 节）；
- 后台重试：插件 start 时在线程中运行 `run_retry_loop(service, stop_event)`，stop 时结束；
- 平台表迁移目录：`plugin.MIGRATIONS`。
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
