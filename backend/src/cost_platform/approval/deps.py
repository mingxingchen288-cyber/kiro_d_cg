"""approval 用到的端口（模块说明第 4 节），由 assembly 创建实现后注入；模块内部不创建其他模块的实现。"""

from __future__ import annotations

from dataclasses import dataclass, field

from cost_platform.contracts.ports import (
    BusinessLocker,
    DirectoryReader,
    DocumentReader,
    RulesEngine,
    SchemaInspector,
    TableWriter,
)
from cost_platform.contracts.types import ErrorCode, PlatformError

from .catalog import CatalogOf
from .sql import KeyAllocator, SequenceKeys, SqlRunner, UowSqlRunner
from .store import ApprovalStore


@dataclass(frozen=True)
class ApprovalDeps:
    catalog: CatalogOf
    """审批流（带编码和名称）和按表找实体（契约缺口，见 catalog.py）。"""
    schema: SchemaInspector
    directory: DirectoryReader
    documents: DocumentReader
    """审批详情读取来源单据和受影响单据的当前数据（不加锁）。"""
    rules: RulesEngine | None = None
    """审批详情和预览的计算；为空时修改后只含待审修改本身，不重算。"""
    tables: TableWriter | None = None
    """最终批准时写没注册的表（WP-19）。"""
    locks: BusinessLocker | None = None
    """业务加锁的统一入口（write-pipeline，C08 第 5b 节）：审批记录、冻结对象、最终通过要写的单据和行都经它加锁。"""
    store: ApprovalStore = field(default_factory=ApprovalStore)
    sql: SqlRunner = field(default_factory=UowSqlRunner)
    keys: KeyAllocator = field(default_factory=SequenceKeys)

    def locker(self) -> BusinessLocker:
        if self.locks is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, "没有接入 BusinessLocker，不能加锁")
        return self.locks
