"""端口：领域层和应用层通过这些抽象访问外部世界。

每个端口都有内存假实现（adapters.memory），并由同一套契约测试（tests/contracts）约束；
Oracle、Redis 等真实实现必须通过同一套测试。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .changes import AuditEntry, ChangePlan
from .config import ConfigItem, SnapshotRead
from .delivery import DeliveryIntent, DeliveryRecord
from .document import RowState, TableBinding
from .identity import SessionData, UserAccount
from .realtime import RealtimeEvent
from .rules import EvaluationRequest, EvaluationResult, RulesPackRef

# ---------------------------------------------------------------- 时间与编号


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """带时区的当前时间。"""


class IdGenerator(ABC):
    @abstractmethod
    def new_id(self) -> str:
        """全局唯一编号（文本）。"""


# ---------------------------------------------------------------- 命令记录（判重前置）


class ClaimOutcome(StrEnum):
    CLAIMED = "claimed"
    """新请求：已在本事务中登记为“处理中”，继续执行业务流程。"""
    REPLAY = "replay"
    """同一请求键已完成且内容摘要相同：直接返回原结果，不再执行业务流程。"""
    DIGEST_MISMATCH = "digest_mismatch"
    """同一请求键已完成，但内容摘要不同：请求键被复用。"""
    IN_PROGRESS = "in_progress"
    """同一请求键的请求仍在处理中，等待超时。"""


@dataclass(frozen=True, slots=True)
class ClaimResult:
    outcome: ClaimOutcome
    stored_result: Mapping[str, Any] | None = None


class CommandLog(ABC):
    """命令记录。claim 必须是事务的第一条语句。

    - 同一用户、同一请求键只会有一条已提交的记录；
    - 业务被拒绝或出错时整笔回滚，记录随之撤销，同一个键可以重试；
    - 另一个事务正持有同一个键时，最多等待 wait_seconds：对方提交则按其结果判断，
      对方回滚则本请求正常登记，超时返回 IN_PROGRESS。
    """

    @abstractmethod
    def claim(
        self, *, subject: str, request_key: str, operation: str, digest: str, wait_seconds: float
    ) -> ClaimResult: ...

    @abstractmethod
    def complete(
        self, *, subject: str, request_key: str, result: Mapping[str, Any], audit: Sequence[AuditEntry]
    ) -> None:
        """把本事务登记的记录改为“已完成”，写入结果和审计差异。"""


# ---------------------------------------------------------------- 业务数据


class DocumentStore(ABC):
    @abstractmethod
    def lock_rows(
        self, binding: TableBinding, keys: Sequence[str], *, fields: Sequence[str] | None, wait_seconds: int
    ) -> Mapping[str, RowState]:
        """按主键排序批量加锁并读出当前值（SELECT … FOR UPDATE WAIT n）。

        不存在的键不出现在结果中。等待超时抛 PlatformError(DOCUMENT_BUSY)。
        """

    @abstractmethod
    def read_rows(
        self,
        binding: TableBinding,
        *,
        keys: Sequence[str] | None = None,
        parent_keys: Sequence[str] | None = None,
        fields: Sequence[str] | None = None,
    ) -> tuple[RowState, ...]:
        """不加锁读取。keys 与 parent_keys 至少给一个；结果按主键排序。"""

    @abstractmethod
    def apply(self, bindings: Mapping[str, TableBinding], plan: ChangePlan) -> Mapping[str, str]:
        """按变更计划写入，只写计划中出现的字段。返回新增行：临时编号 → 正式主键。"""


@dataclass(frozen=True, slots=True)
class FreezeEntry:
    approval_id: str
    entity: str
    record_key: str
    row_key: str | None = None
    """为空表示整张单据冻结。"""


class FreezeStore(ABC):
    @abstractmethod
    def find(self, entity: str, record_keys: Sequence[str]) -> tuple[FreezeEntry, ...]: ...

    @abstractmethod
    def add(self, entries: Sequence[FreezeEntry]) -> None: ...

    @abstractmethod
    def release(self, approval_id: str) -> int:
        """解除某个审批的全部冻结，返回解除的条数。"""


class DeliveryOutbox(ABC):
    """在业务事务内登记投递意图，随业务一起提交或回滚。"""

    @abstractmethod
    def enqueue(self, intents: Sequence[DeliveryIntent]) -> None: ...


class UnitOfWork(AbstractContextManager["UnitOfWork"], ABC):
    """一个命令一个根事务。退出上下文时未提交则回滚。"""

    commands: CommandLog
    documents: DocumentStore
    freezes: FreezeStore
    deliveries: DeliveryOutbox

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @abstractmethod
    def close(self) -> None:
        """未提交则回滚并释放连接。"""


class UnitOfWorkFactory(ABC):
    @abstractmethod
    def begin(self) -> UnitOfWork: ...


# ---------------------------------------------------------------- 通知投递（提交之后）


class DeliveryBatch(ABC):
    """投递器取到的一批待发记录（已加锁，其他进程不会重复取到）。"""

    records: tuple[DeliveryRecord, ...]

    @abstractmethod
    def mark_sent(self, delivery_id: str, at: datetime) -> None: ...

    @abstractmethod
    def mark_failed(self, delivery_id: str, error: str, next_attempt_at: datetime) -> None: ...

    @abstractmethod
    def mark_abandoned(self, delivery_id: str, error: str) -> None: ...


class DeliveryQueue(ABC):
    @abstractmethod
    def claim_due(
        self, *, now: datetime, limit: int, delivery_ids: Sequence[str] | None = None
    ) -> AbstractContextManager[DeliveryBatch]:
        """取到期的待发和失败记录（FOR UPDATE SKIP LOCKED）。退出上下文时提交状态变化。"""

    @abstractmethod
    def get(self, delivery_id: str) -> DeliveryRecord | None: ...

    @abstractmethod
    def list(self, *, statuses: Sequence[str], limit: int = 100) -> tuple[DeliveryRecord, ...]: ...

    @abstractmethod
    def requeue(self, delivery_id: str, *, now: datetime) -> bool:
        """把失败或已放弃的记录重新排队。"""


class DeliverySender(ABC):
    @abstractmethod
    def send(self, record: DeliveryRecord) -> None:
        """真正发送。失败时抛异常，由投递器记录并安排重试。"""


# ---------------------------------------------------------------- 配置快照


class ConfigSnapshotReader(ABC):
    @abstractmethod
    def read(
        self, *, session_id: str | None, item_keys: Sequence[str], known_versions: Mapping[str, str]
    ) -> SnapshotRead:
        """一次往返读出会话和各配置项当前版本；调用方未持有的版本连同内容一起返回。"""


class ConfigSource(ABC):
    """配置的唯一来源（Oracle PF_ 配置表）。"""

    @abstractmethod
    def load(self, item_keys: Sequence[str]) -> Mapping[str, ConfigItem]:
        """读出各配置项的当前版本内容；不存在的项不在结果中。"""

    @abstractmethod
    def publish(self, items: Sequence[ConfigItem]) -> None:
        """写入新版本并切换当前版本（同一事务）。已存在的同号版本内容不得改变。"""


# ---------------------------------------------------------------- 身份


class SessionStore(ABC):
    @abstractmethod
    def create(self, session: SessionData) -> None: ...

    @abstractmethod
    def get(self, session_id: str) -> SessionData | None: ...

    @abstractmethod
    def replace(self, session: SessionData) -> None:
        """更新已存在的会话（例如选定角色）；会话不存在时抛 KeyError。"""

    @abstractmethod
    def delete(self, session_id: str) -> None: ...


class AccountStore(ABC):
    @abstractmethod
    def find_by_username(self, username: str) -> UserAccount | None: ...

    @abstractmethod
    def get(self, user_id: str) -> UserAccount | None: ...

    @abstractmethod
    def create(self, account: UserAccount) -> None:
        """用户名已存在时抛 ValueError。"""

    @abstractmethod
    def update_password_hash(self, user_id: str, password_hash: str) -> None: ...

    @abstractmethod
    def set_active(self, user_id: str, active: bool) -> None: ...


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, password: str) -> str: ...

    @abstractmethod
    def verify(self, password: str, password_hash: str) -> bool: ...

    @abstractmethod
    def needs_rehash(self, password_hash: str) -> bool:
        """旧算法（如 BCrypt）的哈希登录成功后需要改存为新算法。"""


# ---------------------------------------------------------------- 规则内核与实时推送


class RulesHandle(ABC):
    """已加载、已编译的规则包。"""

    pack_id: str
    version: str


class RulesEngine(ABC):
    @abstractmethod
    def load_pack(self, pack: RulesPackRef) -> RulesHandle: ...

    @abstractmethod
    def evaluate(self, handle: RulesHandle, request: EvaluationRequest) -> EvaluationResult: ...

    @abstractmethod
    def core_version(self) -> str: ...


class RealtimePublisher(ABC):
    @abstractmethod
    def publish(self, event: RealtimeEvent) -> None: ...
