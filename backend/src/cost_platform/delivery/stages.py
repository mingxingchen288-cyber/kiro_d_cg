"""delivery 实现的两个管道阶段（架构第 7 节第 11、13 阶段，C08 第 6 节），由 assembly 注册。"""

from __future__ import annotations

from cost_platform.contracts.ports import DeliveryDispatcher, UnitOfWork
from cost_platform.contracts.types import CommandState, ExecutionContext

from .service import DeliveryService


class RegisterNotificationsStage:
    """登记通知：读 `notifications`，写 `delivery_ids`。在命令事务内为每个接收人写一条投递记录（DL-01）。"""

    name = "登记通知"

    def __init__(self, deliveries: DeliveryService) -> None:
        self._deliveries = deliveries

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.notifications)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        state.delivery_ids.extend(self._deliveries.register(
            uow, ctx.identity.user_id, state.command.request_key, state.notifications, ctx.now))


class DispatchStage:
    """投递：读 `delivery_ids`，不写。命令事务提交后执行（DL-02）。

    `uow` 是已经提交的命令事务，这里不用：每次发送在 delivery 自己的事务里进行，发送失败不抛出。
    """

    name = "投递"

    def __init__(self, dispatcher: DeliveryDispatcher) -> None:
        self._dispatcher = dispatcher

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool:
        return bool(state.delivery_ids)

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        self._dispatcher.dispatch_now(list(state.delivery_ids))
