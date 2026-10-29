"""组装根：创建各模块的实现，通过构造参数注入端口（架构 6.1）。不写业务规则。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cost_platform.approval.migrations as approval_migrations
import cost_platform.config.migrations as config_migrations
import cost_platform.delivery.migrations as delivery_migrations
import cost_platform.identity.migrations as identity_migrations
import cost_platform.pipeline.migrations as pipeline_migrations
import cost_platform.queries.migrations as queries_migrations
from cost_platform.authz.checker import RolePermissionChecker
from cost_platform.config.files import FileConfigSnapshotReader
from cost_platform.contracts.types import RoleRef
from cost_platform.db_core.engine import OracleUnitOfWorkFactory, create_oracle_engine
from cost_platform.identity.service import IdentityService, MemorySessions, OracleAccounts
from cost_platform.orchestration.commands import CommandRunner, SaveFlow
from cost_platform.pipeline.command_log import OracleCommandRecorder
from cost_platform.pipeline.document_store import OracleDocumentStore
from cost_platform.pipeline.merge import PatchMerger
from cost_platform.queries.lists import PageQueries
from sqlalchemy import Engine

from .settings import Settings

MIGRATION_DIRS = [Path(m.__file__).parent for m in (pipeline_migrations, identity_migrations, config_migrations,
                                                    queries_migrations, approval_migrations, delivery_migrations)]


class SystemClock:
    """AS-08：服务器本地时间，不带时区（C01 第 4 节）。"""

    def now(self) -> datetime:
        return datetime.now()


class UuidGenerator:
    def uuid(self) -> str:
        return str(uuid.uuid4())


@dataclass
class Container:
    settings: Settings
    engine: Engine
    config: FileConfigSnapshotReader
    accounts: OracleAccounts
    identity: IdentityService
    queries: PageQueries
    executor: CommandRunner
    clock: SystemClock
    ids: UuidGenerator


def build(settings: Settings) -> Container:
    engine = create_oracle_engine(settings.db_user, settings.db_password, settings.db_dsn)
    uow = OracleUnitOfWorkFactory(engine)
    clock, ids = SystemClock(), UuidGenerator()
    config = FileConfigSnapshotReader(settings.config_dir)
    permission = RolePermissionChecker()
    log = OracleCommandRecorder()
    flows = {"save": SaveFlow(OracleDocumentStore(settings.lock_wait_seconds), PatchMerger(), permission, log)}

    def describe_role(code: str) -> RoleRef:
        role = config.role(code)
        return RoleRef(code=code, name=role.name, admin=role.admin)

    accounts = OracleAccounts(uow)
    identity = IdentityService(accounts, MemorySessions(), clock, settings.session_idle_minutes, describe_role)
    return Container(settings=settings, engine=engine, config=config, accounts=accounts, identity=identity,
                     queries=PageQueries(uow, permission), executor=CommandRunner(uow, log, permission, flows),
                     clock=clock, ids=ids)
