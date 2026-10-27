"""queries-export 端口的替代实现（C08 第 9 节）。"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from decimal import Decimal

from ..ports import UnitOfWork
from ..types import (
    DocumentData,
    DocumentRef,
    ErrorCode,
    ImportReport,
    PersonalConfig,
    PersonalConfigBatch,
    PlatformError,
    RelationKeyFinder,
    Row,
    SqlFinder,
    TargetFinder,
    TargetFinderConfig,
    TargetObject,
    Value,
    dump_wire,
)
from ._script import Scripted


def _finder_key(finder: TargetFinderConfig) -> str:
    """预设结果的键：`rows` 不参与，端口不按它筛选（C08 第 9 节）。"""
    data = dump_wire(TargetFinder, finder)
    data.pop("rows", None)
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _key_text(value: Value) -> str:
    """键值统一成文本比较：Decimal 115、"115" 都是 "115"。"""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def _source_rows(source: DocumentData, entity: str) -> list[Row]:
    if entity == source.master.entity:
        return [source.master]
    return list(source.details.get(entity, []))


def _identity(target: TargetObject) -> tuple[object, ...]:
    """同一对象的判断（C08 第 9 节）：按实体和主键；`missing` 的对象没有完整的主键，按 `record_key` 和 `display`。"""
    if target.missing:
        return (target.entity, target.record_key, True, tuple(sorted(target.display.items())))
    return (target.entity, target.record_key, target.row_keys, False)


_BindKey = tuple[tuple[str, str | None], ...]


def _bind_key(binds: Mapping[str, Value]) -> _BindKey:
    return tuple(sorted((name, None if value is None else _key_text(value)) for name, value in binds.items()))


def _bind_sets(finder: SqlFinder, source: DocumentData) -> list[dict[str, Value]]:
    """关联 SQL 每次执行的绑定值（C08 第 9 节）：只引用主表字段时执行一次；引用某个明细的字段时，这个明细每行一次，
    主表字段取主表行的值；这个明细没有行时不执行。"""
    master = source.master
    refs = {name: tuple(ref.split(".", 1)) for name, ref in finder.binds.items()}
    details = {entity for entity, _ in refs.values() if entity != master.entity}
    if len(details) > 1:
        raise ValueError("一个关联 SQL 的绑定变量最多引用一个明细实体（C06 第 10 节，保存时已拒绝）")
    rows = _source_rows(source, details.pop()) if details else [master]
    return [{name: (master if entity == master.entity else row).values.get(field) for name, (entity, field) in refs.items()}
            for row in rows]


class FakeRelatedQuery(Scripted):
    """`RelatedQuery`：不访问数据库，按 C08 第 9 节由预设的数据得出目标。

    - 按关联键：`add_target` 登记目标实体中键值为某值的目标；`find` 取 `source` 中 `sourceKey` 所指实体的全部行，
      按每行的键值找登记的目标，按行的顺序合并，同一目标只出现一次。
    - 按关联 SQL：`respond_rows` 给出查出的行。`find` 按绑定变量逐次"执行"：只引用主表字段时一次，引用某个明细的
      字段时这个明细每行一次；每次取这组绑定值预设的行，没有时取按来源单据或不限来源预设的行。各次的行按 C06 7.2
      换成目标后合并，同一对象只出现一次：实体取 `entity`，单据主键取 `recordKeyColumn`，明细主键取
      `rowKeyColumns`，展示数据取 `labelColumn` 和 `displayColumns`。有一行缺少 `recordKeyColumn` 或
      `rowKeyColumns` 中的列时，抛 500 INTERNAL_ERROR，不返回部分结果；有一行这些列的值为空时，这一行换成
      `missing` 的目标（`record_key` 为查到的值或 None，`row_keys` 为空），其余行照常。
    - `respond` 直接给出找到的目标，优先于上面两种。
    来源单据由调用方按 `rows` 准备，这里不按 `rows` 筛选。
    """

    scriptable = ('find',)

    def __init__(self) -> None:
        super().__init__()
        self._results: dict[tuple[str, DocumentRef | None], list[TargetObject] | _SqlRows] = {}
        self._by_binds: dict[tuple[str, _BindKey], _SqlRows] = {}
        self._by_key: dict[tuple[str, str, str], list[TargetObject]] = {}

    def respond(self, finder: TargetFinderConfig, targets: Iterable[TargetObject], *, source: DocumentRef | None = None) -> None:
        """预设查找结果；不给 `source` 时对任何来源单据生效。"""
        self._results[(_finder_key(finder), source)] = list(targets)

    def respond_rows(self, finder: SqlFinder, rows: Iterable[Mapping[str, Value]], *, source: DocumentRef | None = None,
                     binds: Mapping[str, Value] | None = None) -> None:
        """预设关联 SQL 查出的行。

        给 `binds` 时（须含全部绑定变量，值按文本比较，Decimal 115 与 "115" 相同）只对这组绑定值的那次执行生效；
        给 `source` 时对这张来源单据的每次执行生效；都不给时对任何执行生效。
        """
        if source is not None and binds is not None:
            raise ValueError("source 和 binds 只能给一个")
        sql_rows = _SqlRows(finder, [dict(r) for r in rows])
        if binds is not None:
            self._by_binds[(_finder_key(finder), _bind_key(binds))] = sql_rows
        else:
            self._results[(_finder_key(finder), source)] = sql_rows

    def add_target(self, entity: str, target_key: str, value: Value, target: TargetObject) -> None:
        """登记按关联键能找到的目标：`entity` 中 `target_key` 等于 `value` 的对象。按关联键找到的对象都存在（C08 第 9 节）。"""
        if target.missing:
            raise ValueError("按关联键找到的对象 missing 总为 False")
        self._by_key.setdefault((entity, target_key, _key_text(value)), []).append(target)

    def find(self, uow: UnitOfWork, finder: TargetFinderConfig, source: DocumentData) -> list[TargetObject]:
        self._record("find", uow, finder, source)
        key = _finder_key(finder)
        found = self._results.get((key, source.ref), self._results.get((key, None)))
        if isinstance(found, list):
            return list(found)
        if isinstance(finder, SqlFinder):
            return self._by_sql(key, finder, source, found)
        if isinstance(finder, RelationKeyFinder):
            return self._by_relation_key(finder, source)
        return []

    def _by_sql(self, key: str, finder: SqlFinder, source: DocumentData, preset: _SqlRows | None) -> list[TargetObject]:
        result: list[TargetObject] = []
        seen: set[tuple[object, ...]] = set()
        for binds in _bind_sets(finder, source):
            rows = self._by_binds.get((key, _bind_key(binds)), preset)
            if rows is None:
                continue
            for target in rows.targets():
                ident = _identity(target)
                if ident not in seen:
                    seen.add(ident)
                    result.append(target)
        return result

    def _by_relation_key(self, finder: RelationKeyFinder, source: DocumentData) -> list[TargetObject]:
        entity, _, field = finder.source_key.partition(".")
        result: list[TargetObject] = []
        seen: set[tuple[object, ...]] = set()
        for row in _source_rows(source, entity):
            value = row.values.get(field)
            if value is None:
                continue
            for target in self._by_key.get((finder.entity, finder.target_key, _key_text(value)), []):
                ident = _identity(target)
                if ident not in seen:
                    seen.add(ident)
                    result.append(target)
        return result


class _SqlRows:
    def __init__(self, finder: SqlFinder, rows: list[dict[str, Value]]) -> None:
        self.finder = finder
        self.rows = rows

    def targets(self) -> list[TargetObject]:
        f = self.finder
        key_columns = [f.record_key_column, *f.row_key_columns]
        for row in self.rows:
            absent = [c for c in key_columns if c not in row]
            if absent:
                raise PlatformError(ErrorCode.INTERNAL_ERROR, f"关联 SQL 的结果缺少 {', '.join(absent)}")
        shown = [*([f.label_column] if f.label_column else []), *f.display_columns]
        result = []
        for row in self.rows:
            display = {c: row.get(c) for c in shown}
            record_key = row[f.record_key_column]
            if any(row[c] is None for c in key_columns):
                # 主键为空：这一行表示的记录已不存在，照常返回，由调用方跳过（C08 第 9 节）
                result.append(TargetObject(entity=f.entity, record_key=None if record_key is None else _key_text(record_key),
                                           row_keys=(), display=display, missing=True))
            else:
                result.append(TargetObject(entity=f.entity, record_key=_key_text(record_key),
                                           row_keys=tuple(_key_text(row[c]) for c in f.row_key_columns),
                                           display=display, missing=False))
        return result


class FakeDocumentReader(Scripted):
    """`DocumentReader`：单据由 `put` 预设；每次读取返回副本，调用方修改它不影响存储的内容。"""

    scriptable = ('load', 'load_many')

    def __init__(self) -> None:
        super().__init__()
        self._documents: dict[DocumentRef, DocumentData] = {}

    def put(self, document: DocumentData) -> None:
        self._documents[document.ref] = copy.deepcopy(document)

    def remove(self, ref: DocumentRef) -> None:
        self._documents.pop(ref, None)

    def load(self, ref: DocumentRef) -> DocumentData | None:
        self._record("load", ref)
        found = self._documents.get(ref)
        return None if found is None else copy.deepcopy(found)

    def load_many(self, refs: list[DocumentRef]) -> dict[DocumentRef, DocumentData]:
        self._record("load_many", refs)
        return {ref: copy.deepcopy(self._documents[ref]) for ref in refs if ref in self._documents}


class FakePersonalConfigImporter(Scripted):
    """`PersonalConfigImporter`：按（用户、页面）存放个人配置；已有配置的不覆盖，列入 `skipped`。"""

    scriptable = ('import_batch',)

    def __init__(self) -> None:
        super().__init__()
        self.configs: dict[tuple[str, str], PersonalConfig] = {}

    def put(self, user_id: str, page_code: str, config: PersonalConfig) -> None:
        """预设已有的个人配置。"""
        self.configs[(user_id, page_code)] = config

    def import_batch(self, batch: PersonalConfigBatch) -> ImportReport:
        self._record("import_batch", batch)
        imported = 0
        skipped: list[tuple[str, str]] = []
        for entry in batch.entries:
            key = (entry.user_id, entry.page_code)
            if key in self.configs:
                skipped.append((f"personal:{entry.user_id}/{entry.page_code}", "已有个人配置，没有覆盖"))
                continue
            self.configs[key] = entry.config
            imported += 1
        return ImportReport(imported=imported, skipped=skipped)
