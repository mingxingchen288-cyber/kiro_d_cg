"""真实验证（d_cg、Redis）共用的准备。只被标了 `oracle`、`redis` 的测试使用。

- 连接信息从仓库根目录的 `.env` 读取（assembly 的 Settings），不打印。
- `OracleSchema` 是测试里临时用的 `SchemaInspector`（查 USER_TAB_COLUMNS、USER_OBJECTS、USER_CONSTRAINTS）：db-core 还没有交付
  真实的 `SchemaInspector`（T-DB-2），交付后这里改用它。
- 测试写入 d_cg 的 PF_CONFIG_ITEM 时，配置项编码都以 `CT_ORA_` 开头，测试结束时删除；配置代号会因此增加。
- 前提：已执行 `platform db upgrade`，并且 assembly 把 `cost_platform.config.migrations` 加进了迁移目录（PF_CONFIG_* 两张表）。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any, Literal

import pytest
from sqlalchemy import Engine, text

from cost_platform.config.deps import OracleSequences, StaticDepartments
from cost_platform.config.records import BASE_TYPES
from cost_platform.config.service import ConfigService
from cost_platform.config.snapshot import ConfigReader
from cost_platform.config.validation import Validator
from cost_platform.contracts.fakes import FakeClock, FakeIdGenerator, FakeRealtimePublisher, FakeRulesEngine
from cost_platform.contracts.types import ColumnInfo
from cost_platform.db_core.schema import OracleSchemaInspector

from .support import ROOT


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return {**values, **os.environ}


def oracle_engine() -> Engine:
    from cost_platform.assembly.settings import Settings
    from cost_platform.db_core.engine import create_oracle_engine

    s = Settings.load()
    return create_oracle_engine(s.db_user, s.db_password, s.db_dsn)


def oracle_uow(engine: Engine) -> Any:
    from cost_platform.db_core.engine import OracleUnitOfWorkFactory

    return OracleUnitOfWorkFactory(engine)


def redis_client() -> Any:
    import redis

    return redis.Redis.from_url(env_values().get("PLATFORM_REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True,
                                socket_timeout=5)


def fresh_namespace() -> str:
    """每次运行一个单独的命名空间，不碰平台正在用的 `{ns}:cfg:*`。"""
    return f"{env_values().get('PLATFORM_REDIS_NAMESPACE', 'cost-platform')}-test-{uuid.uuid4().hex[:8]}"


def drop_namespace(client: Any, namespace: str) -> None:
    keys = list(client.scan_iter(f"{namespace}:*"))
    if keys:
        client.delete(*keys)


class OracleSchema:
    """测试用的 `SchemaInspector`（见文件开头）。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def columns(self, table: str) -> dict[str, ColumnInfo] | None:
        sql = text("SELECT column_name, data_type, nullable, char_length, data_precision, data_scale FROM user_tab_columns "
                   "WHERE table_name = :t ORDER BY column_id")
        with self._engine.connect() as c:
            rows = c.execute(sql, {"t": table}).all()
        if not rows:
            return None
        return {r[0]: ColumnInfo(name=r[0], data_type=r[1], nullable=r[2] == "Y", length=int(r[3]) if r[3] else None,
                                 precision=None if r[4] is None else int(r[4]), scale=None if r[5] is None else int(r[5]))
                for r in rows}

    def object_type(self, name: str) -> Literal["table", "view"] | None:
        sql = text("SELECT object_type FROM user_objects WHERE object_name = :n AND object_type IN ('TABLE', 'VIEW')")
        with self._engine.connect() as c:
            found = c.execute(sql, {"n": name}).scalar()
        return None if found is None else ("table" if found == "TABLE" else "view")

    def primary_key(self, table: str) -> str | None:
        sql = text("SELECT cc.column_name FROM user_constraints c JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name "
                   "WHERE c.constraint_type = 'P' AND c.table_name = :t")
        with self._engine.connect() as c:
            rows = c.execute(sql, {"t": table}).all()
        return rows[0][0] if len(rows) == 1 else None


class OracleEnv:
    """d_cg 上的 config：真实的 PF_ 表和 SQL 解析，Redis 由调用方给出（内存或真实）。"""

    def __init__(self, engine: Engine, cache: Any, rules: Any | None = None) -> None:
        self.engine = engine
        self.uow = oracle_uow(engine)
        self.schema = OracleSchemaInspector(engine)
        self.cache = cache
        self.publisher = FakeRealtimePublisher()
        self.clock = FakeClock()
        self.ids = FakeIdGenerator()
        self.rules = rules or FakeRulesEngine()
        # 1069：C06 7.9 样例中旧系统技术中心的编号；18：d_cg 中技术中心的部门编号（seed 的审批流 TECH_CUSTOMER_MATERIAL 引用它，同 support.py）
        self.validator = Validator(self.schema, OracleSequences(), StaticDepartments(["1069", "18"]), self.rules)
        self.hook: Any = None
        self.service = ConfigService(self.uow, self.validator, cache, self.publisher, self.clock, self.ids,
                                     step_hook=lambda step: self.hook(step) if self.hook else None)
        self.reader = self.new_reader()

    def new_reader(self) -> ConfigReader:
        return ConfigReader(self.uow, self.cache, self.rules, self.publisher, self.ids)

    def generation(self) -> int:
        with self.engine.connect() as c:
            return int(c.execute(text("SELECT generation FROM pf_config_generation WHERE id = 1")).scalar_one())

    def stored_keys(self, prefix: str = "CT_") -> list[tuple[str, str]]:
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT config_type, config_key FROM pf_config_item WHERE config_key LIKE :p"),
                             {"p": f"{prefix}%"}).all()
        return [(r[0], r[1]) for r in rows]

    def cleanup(self, prefix: str = "CT_") -> None:
        """按引用的先后删除测试写入的配置项（审批流、角色、菜单、页面、操作、规则、实体）。"""
        order = ["approvalFlow", "role", "menu", "export", "rule", "page", "operation", "lookup", "dict", "entity"]
        keys = [k for k in self.stored_keys(prefix) if k[0] in BASE_TYPES]
        for config_type in order:
            for t, k in keys:
                if t == config_type:
                    self.service.delete(t, k, "1")


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    found = oracle_engine()
    yield found
    found.dispose()
