"""`EntityDirectory`（C08 第 4 节）：最新已发布的实体配置，不按角色。

使用方是 queries-export 的 `RelatedQuery`、`DocumentReader` 和 approval（按表找实体）：它们手里没有执行上下文，要的是
实体层面的配置。

每次调用先取当前配置代号（`ConfigReader.current_version`：一次 Redis 读取，Redis 不可用时读 Oracle 的代号行）。代号不比
已缓存的新时用缓存；否则用一条语句从 Oracle 读出全部实体配置项和代号，按读到的代号缓存（解析结果与配置快照共用
`ParsedCache`）。
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass

from cost_platform.contracts.ports import UnitOfWorkFactory
from cost_platform.contracts.types import EntityConfig, ErrorCode, PlatformError, TableEntity

from .snapshot import ConfigReader
from .store import ConfigStore


@dataclass(frozen=True)
class _Published:
    generation: int
    entities: dict[str, EntityConfig]
    masters: dict[str, tuple[str, str]]
    """明细实体 →（主表实体，明细中关联主表的字段）。"""
    tables: dict[str, list[TableEntity]]
    """表 → 表上注册的实体，按实体编码排列。"""

    @classmethod
    def of(cls, generation: int, entities: Mapping[str, EntityConfig]) -> _Published:
        masters = {d.entity: (code, d.parent_key) for code, e in entities.items() for d in e.details}
        tables: dict[str, list[TableEntity]] = {}
        for code in sorted(entities):
            master = masters.get(code)
            tables.setdefault(entities[code].table, []).append(
                TableEntity(entity=code, master=master[0] if master else code, parent_key=master[1] if master else None))
        return cls(generation, dict(entities), masters, tables)


class PublishedEntities:
    """`EntityDirectory` 的实现。"""

    def __init__(self, uow_factory: UnitOfWorkFactory, reader: ConfigReader, store: ConfigStore | None = None) -> None:
        self._uow = uow_factory
        self._reader = reader
        self._store = store or ConfigStore()
        self._state: _Published | None = None
        self._lock = threading.Lock()
        self.oracle_reads = 0
        """从 Oracle 读实体配置的次数（验证"代号没变时用缓存"用）。"""

    def _current(self) -> _Published:
        generation = self._reader.current_version()
        state = self._state
        if state is not None and generation <= state.generation:
            return state
        with self._uow.begin() as uow:
            found, records = self._store.read_all(uow, ["entity"])
        fresh = _Published.of(found, {r.key: self._reader.parsed.model(r) for r in records.values()})
        with self._lock:
            self.oracle_reads += 1
            if self._state is None or self._state.generation <= fresh.generation:
                self._state = fresh
            return self._state

    def entity(self, code: str) -> EntityConfig:
        found = self._current().entities.get(code)
        if found is None:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"已发布的配置中没有实体 {code}")
        return found

    def master_of(self, code: str) -> tuple[str, str] | None:
        return self._current().masters.get(code)

    def entities_on_table(self, table: str) -> list[TableEntity]:
        return list(self._current().tables.get(table, []))
