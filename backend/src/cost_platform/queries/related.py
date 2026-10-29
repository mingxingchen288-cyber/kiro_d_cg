"""`RelatedQuery`（C08 第 9 节、QE-08）：按钮通用动作 `updateRecords` 的查找（C06 6.1）。只读，不加锁，参数用绑定变量。

- 按关联键：用来源单据中 `sourceKey` 所指实体（主表或某个明细）全部行的键值，到目标实体中查 `targetKey` 等于这些值的行，
  每批最多 1000 个键；按来源行的顺序合并，同一键值的目标按目标主键排序。目标实体是明细时，每行明细一个对象，
  `record_key` 为所属主单的主键（主表实体 `details[].parentKey` 所指字段的值），`row_keys` 为这行明细的主键。
  `display` 为目标中 `targetKey` 的值。按关联键找到的对象都存在（`missing` 为 False）。
- 按关联 SQL：绑定变量只引用主表字段时用主表行执行一次；引用某个明细的字段时，按来源单据中这个明细的行的顺序逐行各执行
  一次，主表字段取主表行的值；这个明细没有行时不执行。结果缺少 `recordKeyColumn` 或 `rowKeyColumns` 中的列时整个查找
  失败（500）；某一行这些列的值为空时，这一行返回为 `missing` 的对象。
- 合并：按执行的先后、每次按 SQL 返回的顺序；同一对象只保留第一次出现的那一个，同一次执行中查出的重复行也只算一个。
  实体、`record_key`、`row_keys` 相同的是同一对象；`missing` 的对象按 `record_key` 和 `display` 判断。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text

from cost_platform.contracts.ports import EntityDirectory, UnitOfWork
from cost_platform.contracts.types import (
    DocumentData,
    ErrorCode,
    PlatformError,
    RelationKeyFinder,
    Row,
    SqlFinder,
    TargetFinderConfig,
    TargetObject,
    Value,
)

from .sql import Binds, Columns, Source, batches, db_value, key_text


def _rows_of(source: DocumentData, entity: str) -> list[Row]:
    if entity == source.master.entity:
        return [source.master]
    return list(source.details.get(entity, []))


def _identity(target: TargetObject) -> tuple[object, ...]:
    if target.missing:
        return (target.entity, target.record_key, True, tuple(sorted(target.display.items(), key=lambda kv: kv[0])))
    return (target.entity, target.record_key, target.row_keys, False)


class _Merged:
    def __init__(self) -> None:
        self.items: list[TargetObject] = []
        self._seen: set[tuple[object, ...]] = set()

    def add(self, targets: Iterable[TargetObject]) -> None:
        for target in targets:
            ident = _identity(target)
            if ident not in self._seen:
                self._seen.add(ident)
                self.items.append(target)


class OracleRelatedQuery:
    def __init__(self, entities: EntityDirectory) -> None:
        self._entities = entities

    def find(self, uow: UnitOfWork, finder: TargetFinderConfig, source: DocumentData) -> list[TargetObject]:
        if isinstance(finder, RelationKeyFinder):
            return self._by_key(uow, finder, source)
        assert isinstance(finder, SqlFinder)
        return self._by_sql(uow, finder, source)

    # ---------------------------------------------------------------- 按关联键

    def _by_key(self, uow: UnitOfWork, finder: RelationKeyFinder, source: DocumentData) -> list[TargetObject]:
        entity, _, field = finder.source_key.partition(".")
        values: dict[str, Value] = {}
        for row in _rows_of(source, entity):
            value = row.values.get(field)
            if value is not None:
                values.setdefault(key_text(value), value)
        if not values:
            return []
        target = Source.of(finder.entity, self._entities.entity(finder.entity))
        master = self._entities.master_of(finder.entity)
        key_column = target.columns[finder.target_key]
        pk_column = target.columns[target.entity.primary_key]
        select = [key_column, pk_column] + ([target.columns[master[1]]] if master else [])
        found: dict[str, list[TargetObject]] = {}
        for chunk in batches(list(values.values())):
            binds = Binds()
            sql = (f"SELECT {', '.join('t.' + c for c in select)} FROM {target.name} t "
                   f"WHERE t.{key_column} IN ({', '.join(binds.add(v) for v in chunk)}) ORDER BY t.{pk_column}")
            for record in uow.connection.execute(text(sql), binds.values):
                hit, pk = db_value(record[0]), record[1]
                record_key, row_keys = (key_text(record[2]), (key_text(pk),)) if master else (key_text(pk), ())
                found.setdefault(key_text(hit), []).append(
                    TargetObject(entity=finder.entity, record_key=record_key, row_keys=row_keys,
                                 display={finder.target_key: hit}, missing=False))
        merged = _Merged()
        for key in values:
            merged.add(found.get(key, []))
        return merged.items

    # ---------------------------------------------------------------- 按关联 SQL

    def _by_sql(self, uow: UnitOfWork, finder: SqlFinder, source: DocumentData) -> list[TargetObject]:
        master = source.master
        refs = {name: tuple(ref.split(".", 1)) for name, ref in finder.binds.items()}
        details = {entity for entity, _ in refs.values() if entity != master.entity}
        rows = _rows_of(source, details.pop()) if details else [master]
        statement = text(finder.sql)
        merged = _Merged()
        for row in rows:
            binds = {name: (master if entity == master.entity else row).values.get(field) for name, (entity, field) in refs.items()}
            result = uow.connection.execute(statement, binds)
            merged.add(self._targets(finder, Columns(result.keys()), result.all()))
        return merged.items

    @staticmethod
    def _targets(finder: SqlFinder, columns: Columns, records: list[object]) -> list[TargetObject]:
        key_columns = [finder.record_key_column, *finder.row_key_columns]
        absent = [c for c in key_columns if c not in columns]
        if absent:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"关联 SQL 的结果缺少 {', '.join(absent)}")
        shown = [*([finder.label_column] if finder.label_column else []), *finder.display_columns]
        positions = {c: columns.index(c) for c in {*key_columns, *shown}}
        targets = []
        for record in records:
            cells = list(record)  # type: ignore[call-overload]

            def get(column: str, cells: list[object] = cells) -> Value:
                position = positions[column]
                return None if position is None else db_value(cells[position])

            display = {c: get(c) for c in shown}
            record_key = get(finder.record_key_column)
            if any(get(c) is None for c in key_columns):
                # 主键为空：这一行表示的记录在查找时已不存在，照常返回，由调用方跳过（C08 第 9 节）
                targets.append(TargetObject(entity=finder.entity, record_key=None if record_key is None else key_text(record_key),
                                            row_keys=(), display=display, missing=True))
            else:
                targets.append(TargetObject(entity=finder.entity, record_key=key_text(record_key),
                                            row_keys=tuple(key_text(get(c)) for c in finder.row_key_columns),
                                            display=display, missing=False))
        return targets
