"""业务表的加锁读取、明细读取和写入（WP-03、WP-06、WP-09）。

- 读取：有 readView 时经视图按字段名读取，否则按 `column` 读表（C06 第 2 节）。
- 加锁（加锁的顺序和 SQL 见 `locks.py`）：只锁一张单据时一条 `SELECT … FOR UPDATE WAIT n` 加锁并读出主表行；一个实体
  锁多行时按主键顺序每行一条加锁语句，再一条普通查询读出数据。用户发起时把行权限条件作为判断列一起查出（C08 第 7 节）。
  推迟加锁的单据锁住后核对（`lock_document`）用同一条加锁并读出的语句，不另外重读。
- 明细：一次读出若干张单据在若干个明细实体中的全部行，一条语句（多个明细实体用 UNION ALL），不加锁：
  单据锁在主表行上；多表视图加 FOR UPDATE 会锁住关联表的行（C08 第 5a 节）。
- 写入：只写有变化的列；同一实体的同一种操作按写入的列分组，每组一条批量语句；新增行的主键取序列 `<表名>_SEQ`，
  用 RETURNING 取回；审批通过时写入的新增行使用已取得的主键（`RowChange.row_key` 不为空，approval AP-02）。
  删除主表行前按关联字段删除它的全部明细，同一张明细表只删一次（WP-06）。

SQL 文本中的表名、列名来自已发布的配置（config 保存时已核对表和列，C06 第 10 节），值一律用绑定变量。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import Date, DateTime, Integer, Numeric, String, bindparam, column, insert, literal_column, table, text
from sqlalchemy.types import TypeEngine

from cost_platform.contracts.ports import UnitOfWork
from cost_platform.contracts.types import (
    DocumentData,
    DocumentRef,
    EntityConfig,
    EntityField,
    ErrorCode,
    ErrorDetail,
    ExecutionContext,
    FieldType,
    PlatformError,
    Row,
    RowChange,
    SqlCondition,
)
from cost_platform.contracts.values import from_db, from_wire, to_db, to_wire

from .locks import lock_key_sql, lock_select_sql

_ALLOWED = "WP_ALLOWED"


@dataclass(frozen=True)
class DetailSource:
    """要读取的一个明细实体：编码、配置，以及它关联主表的字段（主表实体的 `details[].parentKey`）。"""

    entity_code: str
    entity: EntityConfig
    parent_key: str


class RowStore(Protocol):
    """加锁读取和写入业务表的操作，`DocumentLoader`、`ChangeWriter` 经它访问数据库。"""

    def lock_load(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, row_keys: list[str],
                  row_condition: SqlCondition | None = None) -> dict[str, Row]: ...

    def read_masters(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, row_keys: list[str],
                     row_condition: SqlCondition | None = None) -> dict[str, Row]: ...

    def load_details_many(self, uow: UnitOfWork, sources: Sequence[DetailSource],
                          record_keys: Sequence[str]) -> dict[str, dict[str, list[Row]]]: ...

    def insert(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None: ...

    def update(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None: ...

    def delete(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None: ...

    def delete_children(self, uow: UnitOfWork, entity: EntityConfig, parent_key: str, record_keys: list[str]) -> None: ...


def sa_type(field_type: FieldType) -> TypeEngine[Any]:
    """绑定变量的类型：批量语句中第一行为空值时，驱动也能按列的类型绑定。是非字段写 1/0。"""
    return {"number": Numeric(asdecimal=True), "date": Date(), "datetime": DateTime(), "boolean": Integer()}.get(
        field_type, String())


def _source(entity: EntityConfig) -> tuple[str, list[tuple[EntityField, str]]]:
    """读取的表或视图，以及每个字段在其中的列：视图按字段名，表按 `column`。"""
    if entity.read_view:
        return entity.read_view, [(f, f.name) for f in entity.fields]
    return entity.table, [(f, f.column) for f in entity.fields if f.column]


def _field(entity: EntityConfig, name: str) -> EntityField:
    return next(f for f in entity.fields if f.name == name)


def _read_column(entity: EntityConfig, name: str) -> str:
    """字段在读取来源（视图或表）中的列名。"""
    return name if entity.read_view else str(_field(entity, name).column)


def _key_text(entity: EntityConfig, values: dict[str, Any]) -> str:
    pk = _field(entity, entity.primary_key)
    return str(to_wire(pk.type, values[pk.name]))


def _row(entity_code: str, entity: EntityConfig, columns: Sequence[tuple[EntityField, str]],
         record: Sequence[object]) -> Row:
    values = {field.name: from_db(field.type, raw) for (field, _), raw in zip(columns, record)}
    return Row(entity=entity_code, row_key=_key_text(entity, values), client_row_id=None, values=values)


def _rows(entity_code: str, entity: EntityConfig, columns: Sequence[tuple[EntityField, str]],
          records: Iterable[Sequence[object]]) -> dict[str, Row]:
    rows = (_row(entity_code, entity, columns, record) for record in records)
    return {row.row_key or "": row for row in rows}


def _sorted_keys(field: EntityField, keys: Iterable[str]) -> list[Any]:
    return sorted({from_wire(field.type, k) for k in keys})  # type: ignore[type-var]


class OracleDocumentStore:
    def __init__(self, lock_wait_seconds: int) -> None:
        self._wait = int(lock_wait_seconds)

    # ---------------------------------------------------------------- 读取

    def lock_load(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, row_keys: list[str],
                  row_condition: SqlCondition | None = None) -> dict[str, Row]:
        """加锁并读出主表行（WP-03），顺序已由 `locks.LockBook` 检查。只有一个主键时一条 `SELECT … FOR UPDATE WAIT n`，
        加锁、读数据和行权限判断列同一条（普通保存的 SQL 条数不变）；多个主键时按主键顺序每行一条加锁语句
        （`locks.lock_key_sql`，锁 `table` 的行），再一条普通查询读出数据和判断列。给出 `row_condition` 时有一行不满足就
        拒绝整个命令（403 PERMISSION_DENIED）。不存在的主键不在结果中。"""
        pk = _field(entity, entity.primary_key)
        keys = _sorted_keys(pk, row_keys)
        if len(keys) == 1:
            return self._masters(uow, entity_code, entity, keys, row_condition, lock=True)
        for key in keys:
            uow.connection.execute(text(lock_key_sql(entity.table, str(pk.column), self._wait)), {"k": key})
        return self._masters(uow, entity_code, entity, keys, row_condition, lock=False)

    def read_masters(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, row_keys: list[str],
                     row_condition: SqlCondition | None = None) -> dict[str, Row]:
        """不加锁读出主表行（加锁前的普通读取，`CommandState.defer_lock`、`BusinessLocker.read`），其余同 `lock_load`。"""
        pk = _field(entity, entity.primary_key)
        return self._masters(uow, entity_code, entity, _sorted_keys(pk, row_keys), row_condition, lock=False)

    def lock_key(self, uow: UnitOfWork, table: str, key_column: str, key: str, numeric: bool) -> None:
        """锁一行，不读数据（`BusinessLocker.lock`，一行一条）；行不存在时没有锁可加。"""
        uow.connection.execute(text(lock_key_sql(table, key_column, self._wait)), {"k": Decimal(key) if numeric else key})

    def lock_document(self, uow: UnitOfWork, ctx: ExecutionContext, ref: DocumentRef,
                      details: Collection[str]) -> DocumentData | None:
        """锁住一张单据的主表行并读出数据（`BusinessLocker.lock` 核对加锁前读到的本命令单据，规则 4）：与普通保存的加锁读取
        同一条语句（`lock_load` 只有一个主键时）；`details` 中的明细实体再一条普通查询读出（不加锁）。单据已不存在时为 None。"""
        entity = ctx.config.entity(ref.entity)
        master = self.lock_load(uow, ref.entity, entity, [ref.record_key]).get(ref.record_key)
        if master is None:
            return None
        sources = [DetailSource(link.entity, ctx.config.entity(link.entity), link.parent_key)
                   for link in entity.details if link.entity in details]
        rows = self.load_details_many(uow, sources, [ref.record_key]) if sources else {}
        return DocumentData(ref=ref, master=master, details={s.entity_code: rows[s.entity_code][ref.record_key] for s in sources})

    def read_documents(self, uow: UnitOfWork, ctx: ExecutionContext,
                       refs: Sequence[DocumentRef]) -> dict[DocumentRef, DocumentData]:
        """不加锁读出单据：每个实体一条主表查询，明细一条语句（全部明细实体）；不存在的单据不在结果中。"""
        by_entity: dict[str, list[str]] = defaultdict(list)
        for ref in refs:
            by_entity[ref.entity].append(ref.record_key)
        found: dict[DocumentRef, DocumentData] = {}
        for code in sorted(by_entity):
            entity = ctx.config.entity(code)
            masters = self.read_masters(uow, code, entity, by_entity[code])
            sources = [DetailSource(link.entity, ctx.config.entity(link.entity), link.parent_key) for link in entity.details]
            details = self.load_details_many(uow, sources, list(masters)) if sources and masters else {}
            for key, master in masters.items():
                ref = DocumentRef(code, key)
                found[ref] = DocumentData(ref=ref, master=master, details={s.entity_code: details[s.entity_code][key] for s in sources})
        return found

    def _masters(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, keys: list[Any],
                 row_condition: SqlCondition | None, *, lock: bool) -> dict[str, Row]:
        source, columns = _source(entity)
        pk_column = _read_column(entity, entity.primary_key)
        binds: dict[str, Any] = {f"k{i}": k for i, k in enumerate(keys)}
        names = list(binds)
        select = ", ".join(c for _, c in columns)
        if row_condition is not None:
            select += f", CASE WHEN ({row_condition.sql}) THEN 1 ELSE 0 END AS {_ALLOWED}"
            binds.update(row_condition.binds)
        if lock:
            sql = lock_select_sql(select, source, pk_column, self._wait)
        else:
            sql = f"SELECT {select} FROM {source} WHERE {pk_column} IN ({', '.join(':' + b for b in names)}) ORDER BY {pk_column}"
        records = [tuple(r) for r in uow.connection.execute(text(sql), binds)]
        rows = _rows(entity_code, entity, columns, (r[:len(columns)] for r in records))
        if row_condition is not None:
            outside = [key for key, r in zip(rows, records) if not r[len(columns)]]
            if outside:
                raise PlatformError(ErrorCode.PERMISSION_DENIED, "要修改的数据超出了你的行权限",
                                    [ErrorDetail(message="超出行权限", entity=entity_code, row_key=k) for k in outside])
        return rows

    def load_details(self, uow: UnitOfWork, entity_code: str, entity: EntityConfig, parent_key: str,
                     record_key: str) -> dict[str, Row]:
        """一条查询读出一张单据在这个明细实体中的全部行，不加锁（C08 第 5a 节）。"""
        found = self.load_details_many(uow, [DetailSource(entity_code, entity, parent_key)], [record_key])
        return {row.row_key or "": row for row in found[entity_code][record_key]}

    def load_details_many(self, uow: UnitOfWork, sources: Sequence[DetailSource],
                          record_keys: Sequence[str]) -> dict[str, dict[str, list[Row]]]:
        """一条语句读出这些单据在这些明细实体中的全部行，不加锁。结果按明细实体、主单主键分组，组内按明细主键排序。

        多个明细实体时用 UNION ALL：第一列是明细实体的序号，每个实体的列各占一段位置，其他实体的位置为 NULL，
        这样各段的类型互不影响。"""
        result: dict[str, dict[str, list[Row]]] = {s.entity_code: {k: [] for k in record_keys} for s in sources}
        if not sources or not record_keys:
            return result
        layouts = [_source(s.entity) for s in sources]
        widths = [len(columns) for _, columns in layouts]
        offsets = [1 + sum(widths[:i]) for i in range(len(sources))]
        total = 1 + sum(widths)
        binds: dict[str, Any] = {}
        branches, order = [], ["1"]
        for index, (source, (view, columns)) in enumerate(zip(sources, layouts)):
            parent = _field(source.entity, source.parent_key)
            names = []
            for k in _sorted_keys(parent, record_keys):
                name = f"r{index}_{len(names)}"
                binds[name] = k
                names.append(":" + name)
            slots = ["NULL"] * total
            slots[0] = str(index)
            for i, (_, col) in enumerate(columns):
                slots[offsets[index] + i] = col
            if index == 0:
                slots = [f"{expr} AS C{i}" for i, expr in enumerate(slots)]
            branches.append(f"SELECT {', '.join(slots)} FROM {view} "
                            f"WHERE {_read_column(source.entity, source.parent_key)} IN ({', '.join(names)})")
            pk_position = offsets[index] + [f.name for f, _ in columns].index(source.entity.primary_key)
            order.append(str(pk_position + 1))
        sql = " UNION ALL ".join(branches) + f" ORDER BY {', '.join(order)}"
        for record in uow.connection.execute(text(sql), binds):
            index = int(record[0])
            source, (_, columns) = sources[index], layouts[index]
            row = _row(source.entity_code, source.entity, columns, record[offsets[index]:offsets[index] + widths[index]])
            parent = _field(source.entity, source.parent_key)
            result[source.entity_code][str(to_wire(parent.type, row.values[parent.name]))].append(row)
        return result

    # ---------------------------------------------------------------- 写入

    def write(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None:
        """原端口 `DocumentStore.write`（2026-10-29 起不是端口）：按变更计划写这个实体，依次删除、修改、新增（WP-09）。
        新增行取得的主键写回 `RowChange.row_key`。删除主表行连同明细的顺序由 `ChangeWriter` 安排。"""
        by_op: dict[str, list[RowChange]] = defaultdict(list)
        for change in changes:
            by_op[change.op].append(change)
        if by_op["delete"]:
            self.delete(uow, entity, by_op["delete"])
        if by_op["modify"]:
            self.update(uow, entity, by_op["modify"])
        if by_op["add"]:
            self.insert(uow, entity, by_op["add"])

    def update(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None:
        """修改：按写入的列分组，每组一条批量 UPDATE，写到 `table` 的列。"""
        fields = {f.name: f for f in entity.fields}
        pk = fields[entity.primary_key]
        groups: dict[tuple[str, ...], list[RowChange]] = defaultdict(list)
        for change in changes:
            names = tuple(sorted(n for n in change.values if fields[n].column))
            if names:
                groups[names].append(change)
        for names, group in groups.items():
            assignments = ", ".join(f"{fields[n].column} = :v{i}" for i, n in enumerate(names))
            statement = text(f"UPDATE {entity.table} SET {assignments} WHERE {pk.column} = :pk").bindparams(
                *(bindparam(f"v{i}", type_=sa_type(fields[n].type)) for i, n in enumerate(names)),
                bindparam("pk", type_=sa_type(pk.type)))
            params = [{**{f"v{i}": to_db(fields[n].type, c.values[n]) for i, n in enumerate(names)},
                       "pk": from_wire(pk.type, c.row_key)} for c in group]
            uow.connection.execute(statement, params)

    def insert(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None:
        """新增：按写入的列分组，每组一条批量 INSERT；主键取 `<表名>_SEQ.NEXTVAL`，用 RETURNING 取回并写入
        `RowChange.row_key`。已取得主键的行（审批通过时，AP-02）直接写这个主键。"""
        fields = {f.name: f for f in entity.fields}
        pk = fields[entity.primary_key]
        pk_column = str(pk.column).upper()
        groups: dict[tuple[tuple[str, ...], bool], list[RowChange]] = defaultdict(list)
        for change in changes:
            names = tuple(sorted(n for n in change.values if fields[n].column and n != pk.name))
            groups[(names, change.row_key is not None)].append(change)
        for (names, preset), group in groups.items():
            columns = {n: str(fields[n].column).upper() for n in names}
            target = table(entity.table.upper(), column(pk_column, sa_type(pk.type)),
                           *(column(columns[n], sa_type(fields[n].type)) for n in names))
            params = [{columns[n]: to_db(fields[n].type, c.values[n]) for n in names} for c in group]
            if preset:
                for row, change in zip(params, group):
                    row[pk_column] = from_wire(pk.type, change.row_key)
                uow.connection.execute(insert(target), params)
                continue
            statement = (insert(target).values({pk_column: literal_column(f"{entity.table}_SEQ.NEXTVAL")})
                         .returning(target.c[pk_column], sort_by_parameter_order=True))
            keys = [record[0] for record in uow.connection.execute(statement, params)]
            for change, key in zip(group, keys):
                change.row_key = str(to_wire(pk.type, from_db(pk.type, key)))

    def delete(self, uow: UnitOfWork, entity: EntityConfig, changes: list[RowChange]) -> None:
        """按主键物理删除，一条批量 DELETE。"""
        pk = _field(entity, entity.primary_key)
        statement = text(f"DELETE FROM {entity.table} WHERE {pk.column} = :pk").bindparams(
            bindparam("pk", type_=sa_type(pk.type)))
        uow.connection.execute(statement, [{"pk": from_wire(pk.type, c.row_key)} for c in changes])

    def delete_children(self, uow: UnitOfWork, entity: EntityConfig, parent_key: str, record_keys: list[str]) -> None:
        """删除这些主单在这个明细表中的全部行（WP-06），一条语句。"""
        parent = _field(entity, parent_key)
        binds = {f"p{i}": k for i, k in enumerate(_sorted_keys(parent, record_keys))}
        uow.connection.execute(
            text(f"DELETE FROM {entity.table} WHERE {parent.column} IN ({', '.join(':' + b for b in binds)})"), binds)
