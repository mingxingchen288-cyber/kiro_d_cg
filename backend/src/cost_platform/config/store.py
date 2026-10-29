"""配置项和配置代号的存储：表 PF_CONFIG_ITEM、PF_CONFIG_GENERATION（迁移脚本 `migrations/cf_0001_pf_config.py`）。

所有语句都经调用方的 UnitOfWork 执行，提交和回滚由调用方决定。语句只用 Oracle 和 SQLite 都支持的写法，只有锁代号行的
`FOR UPDATE WAIT` 在 Oracle 上才加：模拟验证用 contracts 的 FakeUnitOfWorkFactory（内存 SQLite），真实验证在 d_cg 上运行。
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, bindparam, text
from sqlalchemy.engine import Row
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import TextualSelect

from cost_platform.contracts.ports import UnitOfWork

from .records import ItemRecord, item_id, split_id

LOCK_WAIT_SECONDS = 20
"""等代号行锁的秒数：保存事务最长 30 秒（CF-04），db-core 每条语句的调用超时为 25 秒。"""

_COLUMNS = "config_type, config_key, name, content, version, generation, updated_by, updated_at"
_TYPED = {
    "config_type": String, "config_key": String, "name": String, "content": Text, "version": Integer,
    "generation": BigInteger, "updated_by": String, "current_generation": BigInteger,
}
"""读出时的类型；`updated_at` 不在这里：Oracle 返回 datetime，SQLite 返回文本，由 `_time` 统一。"""


def _select(where: str, expanding: list[str]) -> TextualSelect:
    """读出配置项，每一行带上当前配置代号：同一条语句读出的代号和内容属于同一时刻（Oracle 语句级读一致性）。"""
    sql = (f"SELECT {_COLUMNS}, (SELECT g.generation FROM pf_config_generation g WHERE g.id = 1) AS current_generation "
           f"FROM pf_config_item {where}")
    clause: TextClause = text(sql)
    if expanding:
        clause = clause.bindparams(*(bindparam(name, expanding=True) for name in expanding))
    return clause.columns(**_TYPED)


_GENERATION = text("SELECT generation FROM pf_config_generation WHERE id = 1")
_SET_GENERATION = text("UPDATE pf_config_generation SET generation = :b_gen, updated_at = :b_time WHERE id = 1").bindparams(
    bindparam("b_time", type_=DateTime))
_UPDATE = text(
    "UPDATE pf_config_item SET name = :b_name, content = :b_content, version = :b_version, generation = :b_gen, "
    "updated_by = :b_by, updated_at = :b_time WHERE config_type = :b_type AND config_key = :b_key"
).bindparams(bindparam("b_content", type_=Text), bindparam("b_time", type_=DateTime))
_INSERT = text(
    f"INSERT INTO pf_config_item ({_COLUMNS}) "
    "VALUES (:b_type, :b_key, :b_name, :b_content, :b_version, :b_gen, :b_by, :b_time)"
).bindparams(bindparam("b_content", type_=Text), bindparam("b_time", type_=DateTime))
_DELETE = text("DELETE FROM pf_config_item WHERE config_type = :b_type AND config_key = :b_key")


def _int(value: int | Decimal | None) -> int:
    return 0 if value is None else int(value)


def _time(value: datetime | str) -> datetime:
    found = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return found.replace(microsecond=0)


def _record(row: Row) -> ItemRecord:
    return ItemRecord(type=row.config_type, key=row.config_key, name=row.name, content_json=row.content,
                      version=_int(row.version), generation=_int(row.generation), updated_by=row.updated_by,
                      updated_at=_time(row.updated_at))


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ConfigStore:
    """PF_CONFIG_ITEM、PF_CONFIG_GENERATION 的读写。"""

    def generation(self, uow: UnitOfWork) -> int:
        """当前配置代号：只读一行（恢复任务每 5 秒调用一次，CF-05）。"""
        return _int(uow.connection.execute(_GENERATION).scalar_one())

    def lock_generation(self, uow: UnitOfWork) -> int:
        """`SELECT … FOR UPDATE` 锁住代号行并读出当前代号；多次保存在这里排队（CF-04 第 2 步）。"""
        sql = "SELECT generation FROM pf_config_generation WHERE id = 1"
        if uow.connection.dialect.name == "oracle":
            sql += f" FOR UPDATE WAIT {LOCK_WAIT_SECONDS}"
        return _int(uow.connection.execute(text(sql)).scalar_one())

    def set_generation(self, uow: UnitOfWork, generation: int, now: datetime) -> None:
        uow.connection.execute(_SET_GENERATION, {"b_gen": generation, "b_time": now})

    def _read(self, uow: UnitOfWork, where: str, binds: dict[str, object]) -> tuple[int, dict[str, ItemRecord]]:
        expanding = [name for name, value in binds.items() if isinstance(value, (list, tuple))]
        rows = uow.connection.execute(_select(where, expanding), binds).all()
        if not rows:
            return self.generation(uow), {}
        return _int(rows[0].current_generation), {rec.id: rec for rec in map(_record, rows)}

    def read_all(self, uow: UnitOfWork, types: Collection[str] | None = None) -> tuple[int, dict[str, ItemRecord]]:
        """一条语句读出（指定类型的）全部配置项和当前配置代号（CF-13 第 1 步）。"""
        if types is None:
            return self._read(uow, "", {})
        return self._read(uow, "WHERE config_type IN :b_types", {"b_types": list(types)})

    def read_for_role(self, uow: UnitOfWork, role_code: str, extra_ids: Collection[str] = ()) -> tuple[int, dict[str, ItemRecord]]:
        """一条语句读出角色的配置快照用到的全部配置项（records.relevant_to_role），以及另外指定的配置项（CF-05）。"""
        where = ("WHERE (NOT (config_type = 'role' AND config_key <> :b_role) "
                 "AND NOT (config_type = 'pageView' AND config_key NOT LIKE :b_suffix ESCAPE '\\'))")
        binds: dict[str, object] = {"b_role": role_code, "b_suffix": f"%|{_like_escape(role_code)}"}
        for i, value in enumerate(sorted(set(extra_ids))):
            config_type, key = split_id(value)
            where += f" OR (config_type = :b_t{i} AND config_key = :b_k{i})"
            binds[f"b_t{i}"], binds[f"b_k{i}"] = config_type, key
        return self._read(uow, where, binds)

    def read_ids(self, uow: UnitOfWork, ids: Collection[str]) -> tuple[int, dict[str, ItemRecord]]:
        """一条语句读出指定的配置项和当前配置代号（按 Oracle 补写待生效登记中的项，CF-05）。"""
        clauses, binds = [], {}
        for i, value in enumerate(sorted(set(ids))):
            config_type, key = split_id(value)
            clauses.append(f"(config_type = :b_t{i} AND config_key = :b_k{i})")
            binds[f"b_t{i}"], binds[f"b_k{i}"] = config_type, key
        if not clauses:
            return self.generation(uow), {}
        return self._read(uow, "WHERE " + " OR ".join(clauses), binds)

    def get(self, uow: UnitOfWork, config_type: str, key: str) -> ItemRecord | None:
        _, found = self._read(uow, "WHERE config_type = :b_type AND config_key = :b_key", {"b_type": config_type, "b_key": key})
        return found.get(item_id(config_type, key))

    def put(self, uow: UnitOfWork, record: ItemRecord) -> None:
        binds = {"b_type": record.type, "b_key": record.key, "b_name": record.name, "b_content": record.content_json,
                 "b_version": record.version, "b_gen": record.generation, "b_by": record.updated_by,
                 "b_time": record.updated_at}
        if uow.connection.execute(_UPDATE, binds).rowcount == 0:
            uow.connection.execute(_INSERT, binds)

    def delete(self, uow: UnitOfWork, config_type: str, key: str) -> None:
        uow.connection.execute(_DELETE, {"b_type": config_type, "b_key": key})
