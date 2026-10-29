"""按请求的执行上下文取 Lookup、字典、导出配置（C06 第 9 节）和汇总字段（缺口见
`.reports/modules/queries-export/contract-gaps.md`）。

- `QueryCatalog`：本模块用到的配置读取。Lookup、字典、导出配置由 C08 第 4 节 `ConfigSnapshot` 的 `lookup`、`dict_config`、
  `exports` 给出；汇总字段 C05、C06 还没有配置（缺口第 2 条）。服务构造时注入 `CatalogOf`。
- `SnapshotCatalog`、`snapshot_catalog`：按执行上下文中的配置快照实现（插件用它），`sum_fields` 为空。
- `ItemsCatalog`：按给定配置内容的实现，测试用。

实体配置：`RelatedQuery`、`DocumentReader` 用 C08 第 4 节的端口 `EntityDirectory`，其余查询用执行上下文中的配置快照。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from cost_platform.contracts.ports import ConfigSnapshot
from cost_platform.contracts.types import DictConfig, ExecutionContext, ExportConfig, LookupConfig


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


class SnapshotCatalog:
    """按配置快照实现 `QueryCatalog`。汇总字段没有配置（C06 还没有写法，缺口第 2 条），为空：列表的 `aggregates` 为空。"""

    def __init__(self, snapshot: ConfigSnapshot) -> None:
        self._snapshot = snapshot

    def lookup(self, code: str) -> LookupConfig | None:
        return self._snapshot.lookup(code)

    def dict_config(self, dict_type: str) -> DictConfig | None:
        return self._snapshot.dict_config(dict_type)

    def exports(self, page: str) -> Mapping[str, ExportConfig]:
        return self._snapshot.exports(page)

    def sum_fields(self, page: str, area: str) -> Sequence[str]:
        return []


def snapshot_catalog(ctx: ExecutionContext) -> QueryCatalog:
    """`CatalogOf`：本次请求的配置快照。"""
    return SnapshotCatalog(ctx.config)


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
