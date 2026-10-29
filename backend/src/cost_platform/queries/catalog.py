"""本模块需要、而契约中的配置快照还没有提供的配置读取（缺口见 `.reports/modules/queries-export/contract-gaps.md`）。

- `QueryCatalog`：按请求的执行上下文取 Lookup、字典、导出配置（C06 第 9 节）和汇总字段。C08 第 4 节的
  `ConfigSnapshot` 没有取这几类配置项的方法；assembly 按配置快照实现它，经 `CatalogOf` 注入。
- `EntityDirectory`：`RelatedQuery`、`DocumentReader`（C08 第 9 节）的方法不带执行上下文，读不到实体配置；
  构造时注入，assembly 按当前配置实现。

`ItemsCatalog`、`MappingEntityDirectory` 是按给定配置内容的实现，测试和 assembly 都可以直接用。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from cost_platform.contracts.types import (
    DictConfig,
    EntityConfig,
    ErrorCode,
    ExecutionContext,
    ExportConfig,
    LookupConfig,
    PlatformError,
)


class QueryCatalog(Protocol):
    def lookup(self, code: str) -> LookupConfig | None:
        """Lookup 配置（C06 第 9 节）；不存在时为 None。"""
        ...

    def dict_config(self, dict_type: str) -> DictConfig | None:
        """字典配置；不存在时为 None。"""
        ...

    def exports(self, page: str) -> Mapping[str, ExportConfig]:
        """所属页面为 page 的导出配置，键为导出编码，按配置的顺序。"""
        ...

    def sum_fields(self, page: str, area: str) -> Sequence[str]:
        """列表要汇总（求和）的字段：area 为 `master` 或明细实体。对应旧系统列配置 rulesConfig 的 `aggFunc: "sum"`。"""
        ...


CatalogOf = Callable[[ExecutionContext], QueryCatalog]
"""取本次请求所用的配置（与执行上下文中的配置快照同一版本）。"""


class ItemsCatalog:
    """按给定配置内容实现 `QueryCatalog`。"""

    def __init__(self, *, lookups: Mapping[str, LookupConfig] | None = None, dicts: Mapping[str, DictConfig] | None = None,
                 exports: Mapping[str, ExportConfig] | None = None,
                 sums: Mapping[tuple[str, str], Sequence[str]] | None = None) -> None:
        self._lookups = dict(lookups or {})
        self._dicts = dict(dicts or {})
        self._exports = dict(exports or {})
        self._sums = {k: list(v) for k, v in (sums or {}).items()}

    def lookup(self, code: str) -> LookupConfig | None:
        return self._lookups.get(code)

    def dict_config(self, dict_type: str) -> DictConfig | None:
        return self._dicts.get(dict_type)

    def exports(self, page: str) -> Mapping[str, ExportConfig]:
        return {code: cfg for code, cfg in self._exports.items() if cfg.page == page}

    def sum_fields(self, page: str, area: str) -> Sequence[str]:
        return self._sums.get((page, area), [])


class EntityDirectory(Protocol):
    def entity(self, code: str) -> EntityConfig:
        """实体配置；不存在时抛 500 INTERNAL_ERROR（已发布配置的引用断了，与 C08 第 4 节相同）。"""
        ...

    def master_of(self, code: str) -> tuple[str, str] | None:
        """明细实体所属的主表实体和明细中关联主表的字段（主表实体的 `details[].parentKey`）；不是明细时为 None。"""
        ...


class MappingEntityDirectory:
    def __init__(self, entities: Mapping[str, EntityConfig]) -> None:
        self._entities = dict(entities)
        self._masters = {d.entity: (code, d.parent_key) for code, e in self._entities.items() for d in e.details}

    def entity(self, code: str) -> EntityConfig:
        if code not in self._entities:
            raise PlatformError(ErrorCode.INTERNAL_ERROR, f"已发布的配置中没有实体 {code}")
        return self._entities[code]

    def master_of(self, code: str) -> tuple[str, str] | None:
        return self._masters.get(code)
