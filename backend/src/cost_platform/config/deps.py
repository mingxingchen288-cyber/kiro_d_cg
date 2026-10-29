"""config 校验要用的两项检查（缺口见 `.reports/modules/config/contract-gaps.md`）。

- 部门是否存在（C06 第 10 节：审批节点的 `department` 是已有部门）：部门归 identity，`DirectoryDepartments` 用 C08 第 3 节
  `DirectoryReader.department` 实现（插件用它）。
- 序列是否存在（C06 第 10 节、CF-14：`<表名>_SEQ` 必须已经存在）：`SchemaInspector` 没有这一项，Oracle 实现在这里，
  经调用方的 UnitOfWork 查 USER_SEQUENCES。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from sqlalchemy import text

from cost_platform.contracts.ports import DirectoryReader, UnitOfWork


class DepartmentLookup(Protocol):
    def exists(self, department_id: str) -> bool: ...


class DirectoryDepartments:
    """按 identity 的部门判断：`DirectoryReader.department` 不为 None 即存在。"""

    def __init__(self, directory: DirectoryReader) -> None:
        self._directory = directory

    def exists(self, department_id: str) -> bool:
        return self._directory.department(department_id) is not None


class SequenceChecker(Protocol):
    def exists(self, uow: UnitOfWork, name: str) -> bool: ...


class StaticDepartments:
    """部门编号的固定集合：模拟验证用，也可以由 assembly 用 identity 的部门列表创建。"""

    def __init__(self, ids: Iterable[str]) -> None:
        self._ids = frozenset(ids)

    def exists(self, department_id: str) -> bool:
        return department_id in self._ids


class StaticSequences:
    """序列名的固定集合：模拟验证用（内存 SQLite 没有序列）。"""

    def __init__(self, names: Iterable[str] = ()) -> None:
        self.names = set(names)

    def exists(self, uow: UnitOfWork, name: str) -> bool:
        return name in self.names


_SEQUENCE = text("SELECT COUNT(*) FROM user_sequences WHERE sequence_name = :b_name")


class OracleSequences:
    """查当前用户（d_cg）的序列。"""

    def exists(self, uow: UnitOfWork, name: str) -> bool:
        return int(uow.connection.execute(_SEQUENCE, {"b_name": name}).scalar_one()) > 0
