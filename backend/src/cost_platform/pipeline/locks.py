"""业务加锁的统一入口（WP-03；C08 第 5b 节 `BusinessLocker`；用户 2026-10-30 同意"固定加锁层级"）。

目标是从设计上杜绝死锁：等锁可以，不能死锁；每条命令只执行一遍。

1. 统一顺序：审批记录（PF_APPROVAL）→ 单据层 → 基础数据层；同一层按（表名、主键），主键按字段类型比较（`LockTarget.order`）。
   层级由配置自动判断，不新增配置：有 details 的主表实体为单据层（成本核算），其余注册实体和没注册的表为基础数据层
   （物料清单 T_COST_GOODS）。
2. 一个事务中新加的锁必须排在已持有的全部锁之后（往后找，可以执行到一半再锁）；排在前面或同层时，调用方先用普通查询找出
   范围，再和自己的单据合在一起一次锁完。违反时 `LockBook.claim` 返回 500：这是实现错误，用户操作触发不了。
3. 一次锁多行时按顺序一行一条 `SELECT … FOR UPDATE WAIT n`，不依赖一条 SQL 内部的加锁顺序（没有核实过）；只锁一行时
   （普通保存只锁一张单据）加锁和读数据仍是一条语句，SQL 条数不变。例外：实体的读取视图关联了别的表、视图或经数据库
   链接读的（`ReadViews`），只锁一行时也先锁 `table` 的行、再普通读视图，FOR UPDATE 不落到关联的行和链接上
   （`document_store.lock_load`）；只读本表的视图（物料清单）仍是一条。
4. 加锁前普通读到的本命令单据，锁住后核对；不同时抛 `LockScopeChanged`，编排回滚整个事务、整条命令重来。核对用的数据由
   加锁语句本身读出：这些单据按顺序轮到时用"锁一行并读出数据"的语句（`lock_select_sql`，与普通保存的加锁读取同一条），
   仍是一行一条；其余对象只锁不读（`lock_key_sql`）。有明细的单据另用一条普通查询读明细。
   这样往前冻结的页面（物料清单）保存只比普通保存多 1 条加锁前的普通读取。
5. 主从单据连明细一起锁（用户 2026-10-31："如果是主从保存，那么主从都要锁"）：保存、按钮、审批处理锁住本命令的单据
   （`DocumentLoader.lock`、`document_store.lock_document`）时，锁住主表行之后，每张明细表再一条 `lock_children_sql`，
   锁住这些单据在这张明细表中的全部行，不读数据（明细另用一条普通查询读，见上）；两个明细实体在同一张表上时只锁一次
   （成本核算的物料、包材都在 T_COST_PINGGU_DTL）。明细行只在持有主表行锁之后才锁，所以一条语句锁多行不会和平台的其他
   事务交叉等待。要写的单据（动作、审批展开出的意图所属的单据）都经加锁读取，同样连明细一起锁；只冻结、不写的单据
   （`PipelineLocks.lock` 的 `lock_key`）只锁主表行。

本文件是平台业务代码中唯一写 `FOR UPDATE` 的地方（`backend/tests/architecture/test_lock_entry.py` 检查）；例外是 config 的
代号行、identity 的账号行、delivery 的 SKIP LOCKED，它们不和业务锁同时持有。
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Protocol
from weakref import WeakKeyDictionary

from cost_platform.contracts.ports import SchemaInspector, UnitOfWork
from cost_platform.contracts.types import (
    DocumentData,
    DocumentRef,
    ErrorCode,
    ExecutionContext,
    LockLayer,
    LockScopeChanged,
    LockTarget,
    PlatformError,
)

APPROVAL_TABLE, APPROVAL_KEY = "PF_APPROVAL", "APPROVAL_ID"
_NUMERIC = frozenset({"NUMBER", "FLOAT", "INTEGER", "BINARY_FLOAT", "BINARY_DOUBLE"})


# ---------------------------------------------------------------- SQL（本文件以外不写 FOR UPDATE）

def lock_key_sql(table: str, key_column: str, wait: int) -> str:
    """锁一行，不读数据：`SELECT 主键 FROM 表 WHERE 主键 = :k FOR UPDATE WAIT n`。"""
    return f"SELECT {key_column} FROM {table} WHERE {key_column} = :k FOR UPDATE WAIT {wait}"


def lock_select_sql(select: str, source: str, key_column: str, wait: int) -> str:
    """锁一行并读出数据（只锁一张单据时，加锁读取一条语句）。绑定变量为 `:k0`，与多行时读数据的写法一致。"""
    return f"SELECT {select} FROM {source} WHERE {key_column} IN (:k0) ORDER BY {key_column} FOR UPDATE WAIT {wait}"


def lock_row_sql(table: str, key_column: str, wait: int) -> str:
    """锁没注册的表中的一行并读出整行（WP-19）。"""
    return f"SELECT * FROM {table} WHERE {key_column} = :k FOR UPDATE WAIT {wait}"


def lock_children_sql(table: str, key_column: str, parent_column: str, binds: Sequence[str], wait: int) -> str:
    """锁住这些单据在一张明细表中的全部行，不读数据（规则 5，一张明细表一条）：
    `SELECT 明细主键 FROM 明细表 WHERE 关联列 IN (:p0, …) ORDER BY 明细主键 FOR UPDATE WAIT n`。"""
    keys = ", ".join(":" + b for b in binds)
    return (f"SELECT {key_column} FROM {table} WHERE {parent_column} IN ({keys}) "
            f"ORDER BY {key_column} FOR UPDATE WAIT {wait}")


# ---------------------------------------------------------------- 读取视图读取哪些表（只锁一行时用哪种加锁语句）

class ReadViews:
    """实体的读取视图读取哪些表（WP-03），经 `SchemaInspector.view_sources` 读取，每个视图在进程内只读一次（视图变更随
    部署重启生效，同 `ColumnScales`）。

    只读实体自己的表的视图（例如物料清单的 T_COST_GOODS_PRICE_V 只读 T_COST_GOODS），只锁一行时仍一条
    `SELECT … FOR UPDATE` 加锁并读出（SQL 条数同 WP-10）；关联了别的表、视图或经数据库链接读的（产品信息维护的
    T_COST_GOODS_V、外币管理的 T_COST_FORMONEY_V），先锁 `table` 的行、再普通读视图，FOR UPDATE 不落到关联的行和链接上
    （`document_store.lock_load`）。插件 start 时和配置变更后由 `warmup.SchemaWarmup` 预读已发布实体的读取视图。"""

    def __init__(self, inspector: SchemaInspector) -> None:
        self._inspector = inspector
        self._views: dict[str, tuple[str, ...]] = {}

    def only_table(self, view: str, table: str) -> bool:
        """视图只读 `table` 这一张表（当前用户的）。"""
        key = view.upper()
        if key not in self._views:
            self._read(view)
        return self._views[key] == (table.upper(),)

    def preload(self, views: Iterable[str]) -> list[str]:
        """把还没读过的视图读进来，每个视图一次 `view_sources`；返回这次读了的视图。"""
        done = []
        for view in views:
            if view.upper() not in self._views:
                self._read(view)
                done.append(view)
        return done

    def _read(self, view: str) -> None:
        self._views[view.upper()] = tuple(s.upper() for s in self._inspector.view_sources(view) or [])


# ---------------------------------------------------------------- 锁对象

def entity_layer(ctx: ExecutionContext, entity: str) -> LockLayer:
    """主表实体的层级：有 details 的为单据层，其余为基础数据层。"""
    return "document" if ctx.config.entity(entity).details else "base"


def document_target(ctx: ExecutionContext, ref: DocumentRef) -> LockTarget:
    """单据的锁对象：主表实体的表和主键列。"""
    entity = ctx.config.entity(ref.entity)
    pk = next(f for f in entity.fields if f.name == entity.primary_key)
    return LockTarget(entity_layer(ctx, ref.entity), entity.table.upper(), str(pk.column or pk.name).upper(), ref.record_key,
                      pk.type == "number")


def row_target(inspector: SchemaInspector, table: str, key_column: str, key: str) -> LockTarget:
    """没注册的表中一行的锁对象（基础数据层）：主键列是数值类型时按数值比较。`TableWriter.lock_row` 和
    `BusinessLocker.row` 都用它，同一行得到同一个锁对象。"""
    columns = inspector.columns(table) or {}
    info = next((c for name, c in columns.items() if name.upper() == key_column.upper()), None)
    numeric = info is not None and info.data_type.upper() in _NUMERIC
    return LockTarget("base", table.upper(), key_column.upper(), key, numeric)


def approval_target(approval_id: str) -> LockTarget:
    return LockTarget("approval", APPROVAL_TABLE, APPROVAL_KEY, approval_id, True)


def same_document(now: DocumentData | None, expected: DocumentData) -> bool:
    """锁住后重读的数据与加锁前读到的是否相同：比较主表和 `expected` 中读过的明细实体（规则 4）。"""
    if now is None or now.master != expected.master:
        return False
    return all(now.details.get(entity, []) == rows for entity, rows in expected.details.items())


# ---------------------------------------------------------------- 已持有的锁

class LockBook:
    """按事务（`UnitOfWork`）记下已持有的锁，检查新锁的顺序。加锁读取（`DocumentLoader`）、`TableWriter.lock_row` 和
    `BusinessLocker` 共用一个，事务结束、`UnitOfWork` 被回收时一起丢弃。"""

    def __init__(self) -> None:
        self._held: WeakKeyDictionary[UnitOfWork, list[LockTarget]] = WeakKeyDictionary()

    def held(self, uow: UnitOfWork) -> frozenset[LockTarget]:
        return frozenset(self._held.get(uow, []))

    def claim(self, uow: UnitOfWork, targets: Iterable[LockTarget]) -> list[LockTarget]:
        """要新加的锁：去掉已持有的，按统一顺序排列，并记为已持有（随后由调用方逐个加锁；加锁失败时整个事务回滚）。
        有一个排在已持有的锁之前时 500 INTERNAL_ERROR。"""
        held = self._held.setdefault(uow, [])
        new = sorted(set(targets) - set(held), key=LockTarget.order)
        if new and held:
            top = max(held, key=LockTarget.order)
            early = [t for t in new if t.order() < top.order()]
            if early:
                first = early[0]
                raise PlatformError(ErrorCode.INTERNAL_ERROR,
                                    f"加锁顺序错误：{first.table} {first.key} 排在已锁住的 {top.table} {top.key} 之前")
        held.extend(new)
        return new


# ---------------------------------------------------------------- 端口

class KeyLocker(Protocol):
    """`PipelineLocks` 用到的存储操作（`document_store.OracleDocumentStore` 实现）。"""

    def lock_key(self, uow: UnitOfWork, table: str, key_column: str, key: str, numeric: bool) -> None: ...

    def lock_document(self, uow: UnitOfWork, ctx: ExecutionContext, ref: DocumentRef,
                      details: Collection[str]) -> DocumentData | None: ...

    def read_documents(self, uow: UnitOfWork, ctx: ExecutionContext,
                       refs: Sequence[DocumentRef]) -> dict[DocumentRef, DocumentData]: ...


class PipelineLocks:
    """`BusinessLocker` 的实现：顺序检查在 `LockBook`，SQL 由 `store` 执行（一行一条）。"""

    def __init__(self, book: LockBook, store: KeyLocker, inspector: SchemaInspector) -> None:
        self._book = book
        self._store = store
        self._inspector = inspector

    def document(self, ctx: ExecutionContext, ref: DocumentRef) -> LockTarget:
        return document_target(ctx, ref)

    def row(self, table: str, key_column: str, key: str) -> LockTarget:
        return row_target(self._inspector, table, key_column, key)

    def approval(self, approval_id: str) -> LockTarget:
        return approval_target(approval_id)

    def layer(self, ctx: ExecutionContext, entity: str) -> LockLayer:
        return entity_layer(ctx, entity)

    def read(self, uow: UnitOfWork, ctx: ExecutionContext, refs: list[DocumentRef]) -> dict[DocumentRef, DocumentData]:
        return self._store.read_documents(uow, ctx, refs)

    def lock(self, uow: UnitOfWork, ctx: ExecutionContext, targets: list[LockTarget],
             expected: dict[DocumentRef, DocumentData] | None = None) -> None:
        """按统一顺序一行一条加锁（规则 1、7）；`expected` 中的单据轮到时锁住并读出数据，锁住后用它核对（规则 4，见文件说明）。
        `expected` 中本事务已持有锁的单据这次不再加锁，另用普通查询重读核对。"""
        expected = expected or {}
        own = {document_target(ctx, ref): ref for ref in expected}
        now: dict[DocumentRef, DocumentData | None] = {}
        for target in self._book.claim(uow, targets):
            ref = own.get(target)
            if ref is None:
                self._store.lock_key(uow, target.table, target.key_column, target.key, target.numeric)
            else:
                now[ref] = self._store.lock_document(uow, ctx, ref, list(expected[ref].details))
        rest = [ref for ref in expected if ref not in now]
        if rest:
            now.update(self._store.read_documents(uow, ctx, rest))
        changed = [ref for ref, data in expected.items() if not same_document(now.get(ref), data)]
        if changed:
            raise LockScopeChanged("、".join(f"{r.entity} {r.record_key}" for r in changed) + " 在加锁前读取之后被修改")

    def held(self, uow: UnitOfWork) -> frozenset[LockTarget]:
        return self._book.held(uow)
