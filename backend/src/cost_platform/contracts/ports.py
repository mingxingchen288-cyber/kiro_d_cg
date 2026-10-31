"""后端端口（C08）：模块之间只通过这些协议调用。

谁提供、谁使用见架构第 8 节。除第 5a 节外，每个端口在 contracts/fakes/ 中有内存替代实现，并有一套契约测试
（backend/tests/contracts/test_<端口名>.py）；真实实现必须通过同一套测试。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .types import (
    AccountBatch,
    AccountRef,
    ApprovalFlowConfig,
    ApprovalFlowEntry,
    ColumnInfo,
    Command,
    CommandResult,
    CommandState,
    ConfigDraft,
    DbObject,
    Department,
    DictConfig,
    DocumentData,
    DocumentRef,
    EntityConfig,
    ExecutionContext,
    ExportConfig,
    FreezeEntry,
    Identity,
    ImportReport,
    LockLayer,
    LockTarget,
    LookupConfig,
    MenuItem,
    OperationConfig,
    PackHandle,
    PageView,
    PersonalConfigBatch,
    RealtimeEvent,
    RoleConfig,
    RowChange,
    SqlCondition,
    TableEntity,
    TargetFinderConfig,
    TargetObject,
    Value,
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
        """表或视图的列，键为列名；不存在时为 None。"""
        ...

    def object_type(self, name: str) -> Literal["table", "view"] | None:
        """这个名字在数据库中是表还是视图；都不是时为 None。config 用它检查审批的冻结表、修改表只能是表（C06 第 10 节）。"""
        ...

    def primary_key(self, table: str) -> str | None:
        """表的单列主键列名；没有主键、主键多于一列或不是表时为 None（C06 7.5 的 keyColumn 省略时用）。"""
        ...

    def column_comments(self, table: str) -> dict[str, str | None] | None:
        """C08 v21：表或视图每一列的注释，按列的顺序，没有注释的为 None；不存在时为 None。
        新建页面向导的列标题取注释，没有注释时取列名（同旧系统 `MetaConfigService.listViewColumns`）。"""
        ...

    def objects(self, keyword: str) -> list[DbObject]:
        """C08 v21：名称中含关键字的表和视图（不分大小写），最多 100 个，先表后视图、各按名称排列；关键字为空时不按名称筛选。
        同旧系统 `MetaConfigService.listDbObjects`（向导、"表与列"填视图名和目标表时搜索）。"""
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

    def department(self, department_id: str) -> Department | None:
        """部门；不存在时为 None。使用方 config：审批节点的 `department` 必须是已有部门（C06 第 10 节）。
        部门和账号同归 identity，所以放在这个读取端口里，不另设端口。"""
        ...


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

    def approval_flows(self, page: str) -> list[ApprovalFlowConfig]:
        """所属页面为 page 的启用审批流，按 order、编码排列（C06 7.1）。"""
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

    def rule_fields(self, pack_id: str) -> dict[str, frozenset[str]]:
        """规则包中保存时执行的规则（实体层、操作层的计算和校验规则）读取的字段，键为实体编码（WP-08）。
        write-pipeline 据此判断一次保存要不要读明细、要不要求值：只改了这里没有的字段时不求值（用户 2026-10-29 选定）。
        规则包不存在或没有规则时为空。"""
        ...

    # 以下四个方法 2026-10-29 接线时由使用方提出：要的是与本次请求同一版本的配置，所以放在快照里，不另设端口。

    def lookup(self, code: str) -> LookupConfig | None:
        """Lookup 配置（C06 第 9 节）；不存在时为 None。使用方 queries-export（QE-09、QE-11）。"""
        ...

    def dict_config(self, dict_type: str) -> DictConfig | None:
        """字典配置；不存在时为 None。使用方 queries-export（C09 第 4 节字典接口）。"""
        ...

    def exports(self, page: str) -> dict[str, ExportConfig]:
        """所属页面为 page 的导出配置，键为导出编码，按配置的顺序。使用方 queries-export（QE-06）。"""
        ...

    def approval_flow_entries(self, page: str) -> list[ApprovalFlowEntry]:
        """同 `approval_flows`，另带配置项的编码和名称（审批实例记命中的审批流编码，详情显示名称）。使用方 approval。"""
        ...


class ConfigSnapshotReader(Protocol):
    def read(self, role_code: str) -> ConfigSnapshot:
        """一次 Redis 读取（含当前代号和待生效登记）；只有待生效登记涉及本次要用的配置项、缺项或
        Redis 不可用时才查 Oracle；Oracle 也不可用时抛 CONFIG_UNAVAILABLE。"""
        ...

    def current_version(self) -> int:
        """当前配置代号。使用方 identity（还没选角色时 `/api/me` 的 `configVersion`）和 assembly（响应头
        `X-Config-Version`）：这两处没有角色，取不了快照，所以单列这个方法。"""
        ...


class EntityDirectory(Protocol):
    """最新已发布的实体配置，不按角色。2026-10-29 接线时由使用方提出：queries-export 的 `RelatedQuery`、`DocumentReader`
    和 approval 按表找实体时手里没有执行上下文（端口的方法不带 ctx），要的是实体层面的配置，不是某个角色的快照，
    所以不放进 `ConfigSnapshot`。"""

    def entity(self, code: str) -> EntityConfig:
        """不存在时抛 500 INTERNAL_ERROR（已发布配置的引用断了）。"""
        ...

    def master_of(self, code: str) -> tuple[str, str] | None:
        """明细实体所属的主表实体和明细中关联主表的字段；不是明细时为 None。"""
        ...

    def entities_on_table(self, table: str) -> list[TableEntity]:
        """`table` 上注册的实体（审批的冻结表、修改表注册与否，C06 7.4、7.5）；没有注册时为空。"""
        ...

    def tables(self) -> list[str]:
        """已发布的实体写入的表（实体的 `table`），去重，按名称排列。2026-10-30 由使用方 write-pipeline 提出：启动时和
        配置变更后，把这些表的列定义预读进缓存（WP-15），第一次保存不再多读一次列定义。"""
        ...


class ConfigImporter(Protocol):
    def import_items(self, items: list[ConfigDraft]) -> ImportReport:
        """导入还没有保存的配置项；与前端保存使用同一套校验。"""
        ...


# ============================================================ 5. orchestration 提供（消费各模块的能力）

class CommandExecutor(Protocol):
    def execute(self, command: Command, ctx: ExecutionContext) -> CommandResult:
        """失败时抛 PlatformError，事务已回滚。"""
        ...


# ============================================================ 5a. write-pipeline 提供的写入能力
#
# 由 orchestration 按命令的流程调用（2026-10-28 用户："模块是用来提供能力的，最终消费这些能力的是另外一个东西"）。
# 这两个端口直接用真实实现在 d_cg 上验证，没有替代实现。加锁读取、合并、计算、写入是 write-pipeline 的管道阶段（第 6 节）。

class CommandRecorder(Protocol):
    def begin(self, uow: UnitOfWork, user_id: str, command: Command, now: datetime) -> CommandResult | None:
        """事务的第一条语句插入命令记录（WP-01）。同一用户的同一请求键已完成且内容摘要相同时返回原结果，
        这时调用方不再执行业务流程；摘要不同时抛 IDEMPOTENCY_KEY_REUSED。"""
        ...

    def finish(self, uow: UnitOfWork, user_id: str, command: Command, result: CommandResult,
               audit: list[RowChange] | None, now: datetime) -> None:
        """用一条语句把命令记录标为完成，写入命令结果和审计差异（WP-11；audit 为 None 时不记）。"""
        ...

    def complete(self, uow: UnitOfWork, state: CommandState, ctx: ExecutionContext) -> CommandResult:
        """各阶段执行完后：按 `state` 生成命令结果（WP-12）；结果不是 unchanged 时连同审计差异（WP-11）写入命令记录。
        使用方 orchestration：结果和审计的写法属于 write-pipeline，编排层只决定何时调用、何时提交；这一步与 `finish`
        写的是同一条命令记录，所以放在这个端口里，不另设端口。"""
        ...

# 2026-10-29：原第 5a 节的 `DocumentStore`、`ChangeMerger` 只剩 write-pipeline 自己使用（加锁读取、合并改由它的管道阶段完成），
# 不再是端口，移到 write-pipeline 内部（pipeline/document_store.py 的 `RowStore`、pipeline/merge.py）。


class TableWriter(Protocol):
    """审批流通过后写没在平台注册的表（C06 7.5，WP-19）：按主键直接写，不校验、不重算。"""

    def lock_row(self, uow: UnitOfWork, table: str, key_column: str, key: str) -> dict[str, Value] | None:
        """经 `BusinessLocker` 的统一顺序（基础数据层）`SELECT … FOR UPDATE WAIT n` 读出整行；不存在时为 None。
        最终批准时要写的行已在"确定涉及的单据"锁住（AP-10），这里是再锁一次并读出。"""
        ...

    def update(self, uow: UnitOfWork, table: str, key_column: str, key: str, values: dict[str, Value]) -> None: ...

    def insert(self, uow: UnitOfWork, table: str, values: dict[str, Value]) -> str:
        """主键取 `<表名>_SEQ`，返回新主键。"""
        ...

    def delete(self, uow: UnitOfWork, table: str, key_column: str, key: str) -> None: ...


class CommandMonitor(Protocol):
    """命令审查（WP-17、C09 第 7a 节）：管理员开启后，每个命令结束时（提交或回滚之后）记一条：命令、结果、错误和期间执行的
    每条 SQL。2026-10-29 接线时由使用方 orchestration 提出：记录要包住整个命令事务，只有执行命令的一方做得到；
    `CommandRecorder` 的写入在命令事务里，命令回滚时一起撤销，所以不放进 `CommandRecorder`。"""

    def watch(self, command: Command, ctx: ExecutionContext) -> AbstractContextManager[None]:
        """进入时开始记录；退出时按有没有异常记一条（异常照常抛出，记录失败不影响命令）。开关关闭时什么都不做。"""
        ...


# ============================================================ 5b. write-pipeline 提供的业务加锁入口
#
# 2026-10-30 由使用方 approval、operations 提出：它们要加的锁（审批记录、冻结对象、找到的别的单据）必须和 write-pipeline
# 的加锁读取按同一顺序，而业务模块之间不能互相导入，所以单设端口。替代实现为 contracts/fakes 的 `FakeBusinessLocker`。

class BusinessLocker(Protocol):
    """业务加锁的唯一入口（write-pipeline 提供，WP-03；用户 2026-10-30 同意"固定加锁层级"）。

    统一顺序：审批记录 → 单据层 → 基础数据层（`LOCK_LAYERS`），同一层按（表名、主键），主键按类型比较（`LockTarget.order`）。
    一个事务中后加的锁必须排在已持有的全部锁之后；要锁的对象排在前面或同层时，调用方先用普通查询找出范围
    （`read` 和本来就要执行的查询），再和自己的单据合在一起一次锁完。使用方：approval（审批记录、冻结对象、最终通过要写的
    单据和行）、operations（按钮找到的别的单据）。"""

    def document(self, ctx: ExecutionContext, ref: DocumentRef) -> LockTarget:
        """单据的锁对象：主表实体的表和主键；有 details 的为单据层，没有的为基础数据层。"""
        ...

    def row(self, table: str, key_column: str, key: str) -> LockTarget:
        """没注册的表中一行的锁对象（基础数据层）；主键列是数值类型时按数值比较。"""
        ...

    def approval(self, approval_id: str) -> LockTarget:
        """审批记录（PF_APPROVAL）的锁对象，排在所有业务数据之前。"""
        ...

    def layer(self, ctx: ExecutionContext, entity: str) -> LockLayer:
        """实体所属单据的层级：有 details 的主表实体为单据层，其余为基础数据层。"""
        ...

    def read(self, uow: UnitOfWork, ctx: ExecutionContext, refs: list[DocumentRef]) -> dict[DocumentRef, DocumentData]:
        """加锁前的普通读取：主表和全部明细，不加锁；不存在的单据不在结果中。结果可作为 `lock` 的 `expected`。"""
        ...

    def lock(self, uow: UnitOfWork, ctx: ExecutionContext, targets: list[LockTarget],
             expected: dict[DocumentRef, DocumentData] | None = None) -> None:
        """按统一顺序一行一条 `SELECT … FOR UPDATE WAIT n` 锁住 `targets` 中本事务还没持有的（不存在的行没有锁可加）。
        `expected` 为加锁前普通读到的本命令单据（其中的单据也要在 `targets` 中）：锁住后重读核对，有一张不同就抛
        `LockScopeChanged`。要锁的对象排在本事务已持有的锁之前时 500 INTERNAL_ERROR（违反加锁顺序，属于实现错误）。
        等锁超时 409 DOCUMENT_BUSY。"""
        ...

    def held(self, uow: UnitOfWork) -> frozenset[LockTarget]:
        """本事务已持有的锁（经本入口加的）。"""
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
        """finder 为按钮通用动作 updateRecords 的 find（C06 6.1）；只读，参数用绑定变量。审批流不用它（C06 7.2）。

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
    def find(self, uow: UnitOfWork, table: str, record_keys: list[str]) -> dict[str, FreezeEntry]:
        """table 为根表（见 FreezeEntry）；按根表主键返回冻结记录，每个主键最多一条，未冻结的不在结果中；只读，不加锁。"""
        ...


# ============================================================ 15. assembly 提供

class ContextProvider(Protocol):
    """2026-10-29 接线时由使用方（config、queries-export、delivery、approval 的 HTTP 路由）提出：路由要把请求变成执行上下文
    （校验会话、写请求校验来源和 CSRF、取配置快照）。这件事要组合 identity 的 `Authenticator`、config 的
    `ConfigSnapshotReader` 和时间、编号，又只跟 HTTP 请求有关，不属于其中任何一个，所以单设端口，由 assembly 提供。"""

    def context(self, request: Any, is_write: bool) -> ExecutionContext:
        """`request` 为 FastAPI 的 Request。失败时抛 PlatformError（SESSION_REQUIRED、ORIGIN_REJECTED、CSRF_FAILED 等）。"""
        ...
