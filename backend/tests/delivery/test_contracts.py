"""delivery 的真实实现通过 `DeliveryDispatcher` 和管道阶段的契约测试（C08 第 6、10、14 节），用替代事务运行。
Oracle 上的同一套测试见 test_oracle.py。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack

import pytest

from cost_platform.contracts.ports import UnitOfWorkFactory
from cost_platform.delivery import DeliveryService, DispatchStage, RegisterNotificationsStage
from cost_platform.delivery.store import DeliveryStore, NewDelivery

from ..contracts.test_delivery_dispatcher import DeliveryDispatcherContract
from ..contracts.test_pipeline_stage import PipelineStageContract, StageCase
from .support import T0, YANG_NA, InboxOutage, commit_registration, context, delivery_row, state, submitted, world


def register_committed(factory: UnitOfWorkFactory, delivery_id: str) -> None:
    """登记一条已提交、等待发送的投递记录（E23 给系统管理员的通知）。"""
    notice = submitted()
    with factory.begin() as uow:
        DeliveryStore.insert(uow, NewDelivery(
            delivery_id=delivery_id, command_user=YANG_NA, request_key="7d0c8a3e-2f4b-4c6d-9e1a-5b3c7d9e1f20",
            event=notice.event, recipient=notice.recipients[0], title=notice.title, body=notice.body, link=notice.link,
            created_at=T0, next_retry_at=T0))
        uow.commit()


class DeliveryServiceHarness:
    def __init__(self, factory: UnitOfWorkFactory, outage: InboxOutage, dispatcher: DeliveryService) -> None:
        self._factory = factory
        self._outage = outage
        self.dispatcher = dispatcher

    def register(self, delivery_id: str, *, fails: bool) -> None:
        register_committed(self._factory, delivery_id)
        if fails:
            self._outage.ids.add(delivery_id)

    def status(self, delivery_id: str) -> str:
        return str(delivery_row(self._factory, delivery_id)["status"])


class TestDeliveryService(DeliveryDispatcherContract):
    @pytest.fixture
    def harness(self) -> DeliveryServiceHarness:
        w = world()
        return DeliveryServiceHarness(w.factory, w.outage, w.service)


class DeliveryStagesHarness:
    """登记通知：E23 杨娜保存，给系统管理员的通知意图；投递：这条通知已在另一个库中登记并提交，等待发送。"""

    kinds = frozenset({"登记通知", "投递"})

    def __init__(self) -> None:
        self._stack = ExitStack()
        self._register = world()
        self._uow = self._stack.enter_context(self._register.factory.begin())
        self._dispatch = world()

    def close(self) -> None:
        self._stack.close()

    def cases(self) -> list[StageCase]:
        ctx = context(YANG_NA)
        register = StageCase(kind="登记通知", stage=RegisterNotificationsStage(self._register.service),
                             state=state(submitted()), ctx=ctx, uow=self._uow)
        pending = state(submitted())
        commit_registration(self._dispatch, pending, ctx)
        dispatch = StageCase(kind="投递", stage=DispatchStage(self._dispatch.service), state=pending, ctx=ctx, uow=self._uow)
        return [register, dispatch]

    def failing_cases(self) -> list[StageCase]:
        return []  # 这两个阶段在 C08 第 6 节的表中没有错误码：发送失败只记录，不抛出


class TestDeliveryStages(PipelineStageContract):
    @pytest.fixture
    def harness(self) -> Iterator[DeliveryStagesHarness]:
        harness = DeliveryStagesHarness()
        yield harness
        harness.close()
