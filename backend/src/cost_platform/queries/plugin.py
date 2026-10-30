"""queries-export 的两个插件（`.reports/modules/plugin-spec.md` 第 2 节）。

- `queries.readers`：`RelatedQuery`、`DocumentReader`（C08 第 9 节），实体配置取自 `EntityDirectory`。
- `queries`：C09 第 4 节的 HTTP 接口。approval 要用 `DocumentReader`，而这里的列表要用 approval 的 `FreezeReader`，
  放在同一个插件里会成环，所以单列。接口的实体配置、Lookup、字典、导出配置都取自执行上下文中的配置快照
  （`snapshot_catalog`），不用 `EntityDirectory`；列表汇总字段取页面视图中 `aggregate` 为 `sum` 的可见字段。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from cost_platform.contracts.ports import (
    ContextProvider,
    DocumentReader,
    EntityDirectory,
    FreezeReader,
    PermissionChecker,
    RelatedQuery,
    UnitOfWorkFactory,
)
from cost_platform.contracts.registry import PluginView

from . import migrations
from .catalog import snapshot_catalog
from .documents import OracleDocumentReader
from .exports import Exports
from .lists import PageQueries
from .lookups import DictQueries, LookupQueries
from .personal import PersonalConfigs, PersonalConfigStore
from .related import OracleRelatedQuery
from .router import QueryServices, build_router

MIGRATIONS = Path(migrations.__file__).parent
"""PF_PERSONAL_CONFIG 的迁移脚本目录（assembly 的 `platform db` 用）。"""


class QueryReadersPlugin:
    name = "queries.readers"
    provides = (RelatedQuery, DocumentReader)
    requires = (UnitOfWorkFactory, EntityDirectory)

    def setup(self, reg: PluginView) -> None:
        entities = reg.get(EntityDirectory)
        reg.provide(RelatedQuery, OracleRelatedQuery(entities))
        reg.provide(DocumentReader, OracleDocumentReader(reg.get(UnitOfWorkFactory), entities))


class QueriesPlugin:
    name = "queries"
    provides = (APIRouter,)
    requires = (UnitOfWorkFactory, PermissionChecker, FreezeReader, ContextProvider)

    def setup(self, reg: PluginView) -> None:
        uow = reg.get(UnitOfWorkFactory)
        permission = reg.get(PermissionChecker)
        services = QueryServices(
            lists=PageQueries(uow, permission, freeze=reg.get(FreezeReader), catalog=snapshot_catalog),
            lookups=LookupQueries(uow, snapshot_catalog),
            dicts=DictQueries(snapshot_catalog),
            personal=PersonalConfigs(PersonalConfigStore(uow)),
            exports=Exports(uow, permission, snapshot_catalog),
        )
        reg.add(APIRouter, build_router(services, reg.get(ContextProvider).context))
