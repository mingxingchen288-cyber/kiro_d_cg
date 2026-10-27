"""queries-export 端口的替代实现（C08 第 9 节）。"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping

from ..ports import UnitOfWork
from ..types import (
    DocumentData,
    DocumentRef,
    ErrorCode,
    ImportReport,
    PersonalConfig,
    PersonalConfigBatch,
    PlatformError,
    SqlFinder,
    TargetFinder,
    TargetFinderConfig,
    TargetObject,
    Value,
    dump_wire,
)
from ._script import Scripted


def _finder_key(finder: TargetFinderConfig) -> str:
    return json.dumps(dump_wire(TargetFinder, finder), sort_keys=True, ensure_ascii=False)


class FakeRelatedQuery(Scripted):
    """`RelatedQuery`：不执行查询，结果按（查找方式、来源单据）预设，没有预设时为空列表。

    - `respond` 直接给出找到的目标。
    - `respond_rows` 给出关联 SQL 查出的行，`find` 时按 C06 7.2 换成目标：实体取 `entity`，单据主键取
      `recordKeyColumn`，明细主键取 `rowKeyColumns`，展示数据取 `displayColumns`；有一行缺少 `recordKeyColumn`
      时抛 500 INTERNAL_ERROR，不返回部分结果（C08 第 9 节）。
    来源单据按 C08 第 9 节由调用方准备，这里不按 `rows` 筛选。
    """

    scriptable = ('find',)

    def __init__(self) -> None:
        super().__init__()
        self._results: dict[tuple[str, DocumentRef | None], list[TargetObject] | _SqlRows] = {}

    def respond(self, finder: TargetFinderConfig, targets: Iterable[TargetObject], *, source: DocumentRef | None = None) -> None:
        """预设查找结果；不给 `source` 时对任何来源单据生效。"""
        self._results[(_finder_key(finder), source)] = list(targets)

    def respond_rows(self, finder: SqlFinder, rows: Iterable[Mapping[str, Value]], *, source: DocumentRef | None = None) -> None:
        """预设关联 SQL 查出的行；不给 `source` 时对任何来源单据生效。"""
        self._results[(_finder_key(finder), source)] = _SqlRows(finder, [dict(r) for r in rows])

    def find(self, uow: UnitOfWork, finder: TargetFinderConfig, source: DocumentData) -> list[TargetObject]:
        self._record("find", uow, finder, source)
        key = _finder_key(finder)
        found = self._results.get((key, source.ref), self._results.get((key, None), []))
        return found.targets() if isinstance(found, _SqlRows) else list(found)


class _SqlRows:
    def __init__(self, finder: SqlFinder, rows: list[dict[str, Value]]) -> None:
        self.finder = finder
        self.rows = rows

    def targets(self) -> list[TargetObject]:
        f = self.finder
        if any(f.record_key_column not in row for row in self.rows):
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"关联 SQL 的结果缺少 {f.record_key_column}")
        return [TargetObject(entity=f.entity, record_key=str(row[f.record_key_column]),
                             row_keys=tuple(str(row[c]) for c in f.row_key_columns),
                             display={c: row.get(c) for c in f.display_columns}) for row in self.rows]


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
