"""后端端口（C08）：模块之间只通过这些协议调用。

谁提供、谁使用见架构第 8 节。每个端口在 contracts/fakes/ 中有内存替代实现，并有一套契约测试
（backend/tests/contracts/test_<端口名>.py）；真实实现必须通过同一套测试。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from .types import (
    AccountBatch,
    AccountRef,
    ApprovalFlowConfig,
    ColumnInfo,
    Command,
    CommandResult,
    CommandState,
    ConfigDraft,
    DocumentData,
    DocumentRef,
    EntityConfig,
    ExecutionContext,
    FreezeEntry,
    Identity,
    ImportReport,
    MenuItem,
    OperationConfig,
    PackHandle,
    PageView,
    PersonalConfigBatch,
    RealtimeEvent,
    RoleConfig,
    SqlCondition,
    TargetFinderConfig,
    TargetObject,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection


# ============================================================ 2. db-core 提供

class UnitOfWork(Protocol):
    connection: Connection
    """本事务的连接，各模块的存储实现都用它。"""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def begin(self) -> AbstractContextManager[UnitOfWork]:
        """开启事务；退出时没有提交就回滚。"""
        ...


class SchemaInspector(Protocol):
    def columns(self, table: str) -> dict[str, ColumnInfo] | None:
        """表的列，键为列名；表不存在时为 None。"""
        ...


class ConnectionFactory(Protocol):
    def legacy_readonly(self) -> AbstractContextManager[Connection]:
        """用 d_cg 账号开启只读事务（SET TRANSACTION READ ONLY），以 CMX.表名 读取旧库；只供 migration 和复制业务表使用。"""
        ...


# ============================================================ 3. identity 提供

class Authenticator(Protocol):
    def authenticate(self, session_id: str | None, csrf_token: str | None, is_write: bool, touch: bool = True) -> Identity:
        """校验会话。touch 为 True 时顺延会话；后台请求、realtime 的握手和心跳检查传 False。

        失败时抛 PlatformError：SESSION_REQUIRED、SESSION_ROLE_REVOKED、ROLE_SELECTION_REQUIRED、CSRF_FAILED。
        """
        ...


class DirectoryReader(Protocol):
    def enabled_accounts_with_role(self, role_code: str) -> list[AccountRef]: ...

    def account(self, user_id: str) -> AccountRef | None: ...


class AccountImporter(Protocol):
    def import_batch(self, batch: AccountBatch) -> ImportReport:
        """已存在的账号不覆盖，列入 skipped。"""
        ...


# ============================================================ 4. config 提供

class ConfigSnapshot(Protocol):
    """某个角色在某个配置版本下的配置，一个请求内不变。"""

    version: int
    role_code: str

    def page_view(self, page_code: str) -> PageView: ...

    def entity(self, code: str) -> EntityConfig: ...

    def operation(self, code: str) -> OperationConfig: ...

    def approval_flows(self, operation: str) -> list[ApprovalFlowConfig]:
        """来源操作为 operation 的审批流，按创建先后排列。"""
        ...

    def approval_flow(self, code: str) -> ApprovalFlowConfig: ...

    def role(self) -> RoleConfig:
        """快照所属的角色。"""
        ...

    def menus(self) -> list[MenuItem]:
        """菜单，已去掉该角色不能访问的页面。"""
        ...

    def rules_pack(self, pack_id: str) -> PackHandle:
        """已经 load_pack 的句柄。"""
        ...


class ConfigSnapshotReader(Protocol):
    def read(self, role_code: str) -> ConfigSnapshot:
        """一次 Redis 读取（含当前代号和待生效登记）；只有待生效登记涉及本次要用的配置项、缺项或
        Redis 不可用时才查 Oracle；Oracle 也不可用时抛 CONFIG_UNAVAILABLE。"""
        ...


class ConfigImporter(Protocol):
    def import_items(self, items: list[ConfigDraft]) -> ImportReport:
        """导入还没有保存的配置项；与前端保存使用同一套校验。"""
        ...


# ============================================================ 5. write-pipeline 提供

class CommandExecutor(Protocol):
    def execute(self, command: Command, ctx: ExecutionContext) -> CommandResult:
        """失败时抛 PlatformError，事务已回滚。"""
        ...


# ============================================================ 6. 管道阶段

class PipelineStage(Protocol):
    name: str

    def applies(self, state: CommandState, ctx: ExecutionContext) -> bool: ...

    def run(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> None:
        """失败时抛 PlatformError。"""
        ...


# ============================================================ 7. authz 提供

class PermissionChecker(Protocol):
    def can_run(self, ctx: ExecutionContext, operation: str, page: str | None) -> bool: ...

    def row_condition(self, ctx: ExecutionContext, page: str, entity: str) -> SqlCondition | None:
        """行权限的 SQL 条件；没有行权限时为 None。"""
        ...

    def writable_fields(self, ctx: ExecutionContext, page: str, entity: str) -> frozenset[str]: ...

    def can_export(self, ctx: ExecutionContext, page: str, export_code: str) -> bool: ...


# ============================================================ 8. rules-core 提供

class RulesEngine(Protocol):
    def load_pack(self, pack_json: bytes) -> PackHandle: ...

    def evaluate(self, handle: PackHandle, request_json: str) -> str:
        """输入输出见 C07。"""
        ...

    def core_version(self) -> str: ...


# ============================================================ 9. queries-export 提供

class RelatedQuery(Protocol):
    def find(self, uow: UnitOfWork, finder: TargetFinderConfig, source: DocumentData) -> list[TargetObject]:
        """finder 为审批流 targets.find 或 freeze 中按关联键、关联 SQL 查找的一项；只读，参数用绑定变量。

        关联 SQL 查出的行中主键为空的，返回为 `missing` 的对象，不报错；缺少主键列时为 500（C08 第 9 节）。
        """
        ...


class DocumentReader(Protocol):
    def load(self, ref: DocumentRef) -> DocumentData | None:
        """不加锁。"""
        ...

    def load_many(self, refs: list[DocumentRef]) -> dict[DocumentRef, DocumentData]: ...


class PersonalConfigImporter(Protocol):
    def import_batch(self, batch: PersonalConfigBatch) -> ImportReport: ...


# ============================================================ 10. delivery 提供

class DeliveryDispatcher(Protocol):
    def dispatch_now(self, delivery_ids: list[str]) -> None:
        """提交后调用；发送失败只记录，由后台重试。"""
        ...


# ============================================================ 11. realtime 提供

class RealtimePublisher(Protocol):
    def publish(self, event: RealtimeEvent) -> None:
        """事件格式见 C10；发布失败只记日志，不影响调用方已提交的事务。"""
        ...


# ============================================================ 12. 时间和编号

class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def uuid(self) -> str:
        """小写 UUID。"""
        ...


# ============================================================ 13. approval 提供

class FreezeReader(Protocol):
    def find(self, uow: UnitOfWork, entity: str, record_keys: list[str]) -> dict[str, FreezeEntry]:
        """按单据主键返回冻结记录，每张单据最多一条，未冻结的不在结果中；只读，不加锁。"""
        ...
