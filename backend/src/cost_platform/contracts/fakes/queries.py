"""queries-export 端口的替代实现（C08 第 9 节）。"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable

from ..ports import UnitOfWork
from ..types import (
    DocumentData,
    DocumentRef,
    ImportReport,
    PersonalConfig,
    PersonalConfigBatch,
    TargetFinder,
    TargetFinderConfig,
    TargetObject,
    dump_wire,
)
from ._script import Scripted


def _finder_key(finder: TargetFinderConfig) -> str:
    return json.dumps(dump_wire(TargetFinder, finder), sort_keys=True, ensure_ascii=False)


class FakeRelatedQuery(Scripted):
    """`RelatedQuery`：不执行查询，结果由 `respond` 按（查找方式、来源单据）预设，没有预设时为空列表。"""

    scriptable = ('find',)

    def __init__(self) -> None:
        super().__init__()
        self._results: dict[tuple[str, DocumentRef | None], list[TargetObject]] = {}

    def respond(self, finder: TargetFinderConfig, targets: Iterable[TargetObject], *, source: DocumentRef | None = None) -> None:
        """预设查找结果；不给 `source` 时对任何来源单据生效。"""
        self._results[(_finder_key(finder), source)] = list(targets)

    def find(self, uow: UnitOfWork, finder: TargetFinderConfig, source: DocumentData) -> list[TargetObject]:
        self._record("find", uow, finder, source)
        key = _finder_key(finder)
        found = self._results.get((key, source.ref), self._results.get((key, None), []))
        return list(found)


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
                skipped.append((f"personal:{entry.user_id}:{entry.page_code}", "已有个人配置，没有覆盖"))
                continue
            self.configs[key] = entry.config
            imported += 1
        return ImportReport(imported=imported, skipped=skipped)
