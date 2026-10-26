"""不依赖外部服务的系统实现：真实时钟与 UUID 编号。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cost_platform.contracts.ports import Clock, IdGenerator


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator(IdGenerator):
    def new_id(self) -> str:
        return uuid.uuid4().hex
