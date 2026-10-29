"""账号、角色分配和部门的存储（PF_USER、PF_USER_ROLE、PF_DEPARTMENT），以及 `DirectoryReader`（C08 第 3 节）。

每个方法一个事务，经 db-core 的 `UnitOfWorkFactory` 执行。SQL 由 `tables.py` 的表对象生成，在 d_cg 上和
contracts 的 `FakeUnitOfWorkFactory`（内存 SQLite）上都能执行；只有取主键用 Oracle 序列，测试时由 `next_id` 换掉。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, func, insert, or_, select, text, update
from sqlalchemy.engine import Connection

from cost_platform.contracts.ports import UnitOfWorkFactory
from cost_platform.contracts.types import AccountRef, Department, ErrorCode, ErrorDetail, PlatformError

from .passwords import Passwords
from .sessions import AccountState
from .tables import DEPARTMENT_SEQUENCE, USER_SEQUENCE, pf_department, pf_user, pf_user_role

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123.."
ADMIN_DISPLAY_NAME = "系统管理员"
ADMIN_ROLE = "ADMIN"

NextId = Callable[[Connection, str], int]
"""取新主键：参数为本事务的连接和序列名。"""


def oracle_sequence(connection: Connection, sequence: str) -> int:
    """Oracle 序列取号；sequence 只取 tables.py 中的常量，不来自外部输入。"""
    return int(connection.execute(text(f"SELECT {sequence}.NEXTVAL FROM dual")).scalar_one())


@dataclass(frozen=True)
class AccountRecord:
    user_id: str
    username: str
    display_name: str
    department_id: str | None
    enabled: bool
    password_hash: str | None = field(repr=False)
    role_codes: tuple[str, ...]
    version: int

    def state(self) -> AccountState:
        return AccountState(user_id=self.user_id, version=self.version, enabled=self.enabled, role_codes=self.role_codes,
                            username=self.username, display_name=self.display_name, department_id=self.department_id)

    def ref(self) -> AccountRef:
        return AccountRef(user_id=self.user_id, username=self.username, display_name=self.display_name,
                          department_id=self.department_id, enabled=self.enabled)


@dataclass(frozen=True)
class DepartmentRecord:
    department_id: str
    name: str
    parent_id: str | None


def _uid(user_id: str) -> int | None:
    """账号编号是十进制文本（C01）；不是数字的编号对应不到任何账号。"""
    return int(user_id) if user_id.isdigit() else None


def _account(row: object, roles: Sequence[str]) -> AccountRecord:
    return AccountRecord(user_id=str(row.user_id), username=row.username, display_name=row.display_name,  # type: ignore[attr-defined]
                         department_id=row.department_id, enabled=bool(row.enabled),  # type: ignore[attr-defined]
                         password_hash=row.password_hash, role_codes=tuple(roles), version=int(row.version))  # type: ignore[attr-defined]


def _roles_of(connection: Connection, user_ids: Iterable[int]) -> dict[int, list[str]]:
    ids = list(user_ids)
    found: dict[int, list[str]] = {uid: [] for uid in ids}
    if not ids:
        return found
    rows = connection.execute(select(pf_user_role.c.user_id, pf_user_role.c.role_code)
                              .where(pf_user_role.c.user_id.in_(ids))
                              .order_by(pf_user_role.c.user_id, pf_user_role.c.role_code))
    for uid, code in rows:
        found[int(uid)].append(code)
    return found


def _load(connection: Connection, condition: object, *, lock: bool = False) -> AccountRecord | None:
    query = select(pf_user).where(condition)  # type: ignore[arg-type]
    row = connection.execute(query.with_for_update() if lock else query).one_or_none()
    if row is None:
        return None
    return _account(row, _roles_of(connection, [int(row.user_id)])[int(row.user_id)])


def _duplicate_username(username: str) -> PlatformError:
    return PlatformError(ErrorCode.VALIDATION_FAILED, f"账号名 {username} 已存在",
                         [ErrorDetail(message=f"账号名 {username} 已存在", field="username")])


class OracleAccounts:
    """账号存储，同时是 `DirectoryReader`。

    `next_id` 默认取 Oracle 序列（PF_USER_SEQ、PF_DEPARTMENT_SEQ）；模拟验证在 SQLite 上运行时由测试换成计数器。
    """

    def __init__(self, uow_factory: UnitOfWorkFactory, next_id: NextId = oracle_sequence,
                 passwords: Passwords | None = None) -> None:
        self._uow = uow_factory
        self._next_id = next_id
        self._passwords = passwords or Passwords()

    # ------------------------------------------------------------ 读取

    def find(self, username: str) -> AccountRecord | None:
        with self._uow.begin() as uow:
            return _load(uow.connection, pf_user.c.username == username)

    def get(self, user_id: str) -> AccountRecord | None:
        uid = _uid(user_id)
        if uid is None:
            return None
        with self._uow.begin() as uow:
            return _load(uow.connection, pf_user.c.user_id == uid)

    def list_accounts(self, keyword: str, start: int, end: int, role_code: str | None = None) -> tuple[list[AccountRecord], int]:
        """账号列表（C09 第 2 节）：`keyword` 匹配账号名或姓名（不分大小写）；`role_code` 只列分配了该角色的账号。
        按账号编号排列，`start` 包含、`end` 不包含（C09 第 1 节）。"""
        conditions = []
        word = keyword.strip().lower()
        if word:
            pattern = f"%{word}%"
            conditions.append(or_(func.lower(pf_user.c.username).like(pattern), func.lower(pf_user.c.display_name).like(pattern)))
        if role_code:
            conditions.append(pf_user.c.user_id.in_(select(pf_user_role.c.user_id).where(pf_user_role.c.role_code == role_code)))
        with self._uow.begin() as uow:
            conn = uow.connection
            total = int(conn.execute(select(func.count()).select_from(pf_user).where(*conditions)).scalar_one())
            rows = conn.execute(select(pf_user).where(*conditions).order_by(pf_user.c.user_id)
                                .offset(start).limit(max(end - start, 0))).all()
            roles = _roles_of(conn, [int(r.user_id) for r in rows])
        return [_account(r, roles[int(r.user_id)]) for r in rows], total

    def departments(self) -> list[DepartmentRecord]:
        with self._uow.begin() as uow:
            rows = uow.connection.execute(select(pf_department).order_by(pf_department.c.department_id)).all()
        return [DepartmentRecord(r.department_id, r.name, r.parent_id) for r in rows]

    # ------------------------------------------------------------ DirectoryReader（C08 第 3 节）

    def enabled_accounts_with_role(self, role_code: str) -> list[AccountRef]:
        with self._uow.begin() as uow:
            rows = uow.connection.execute(
                select(pf_user.c.user_id, pf_user.c.username, pf_user.c.display_name, pf_user.c.department_id)
                .join(pf_user_role, pf_user_role.c.user_id == pf_user.c.user_id)
                .where(pf_user_role.c.role_code == role_code, pf_user.c.enabled == 1)
                .order_by(pf_user.c.user_id)).all()
        return [AccountRef(user_id=str(r.user_id), username=r.username, display_name=r.display_name,
                           department_id=r.department_id, enabled=True) for r in rows]

    def account(self, user_id: str) -> AccountRef | None:
        found = self.get(user_id)
        return None if found is None else found.ref()

    def department(self, department_id: str) -> Department | None:
        """部门；不存在时为 None（config 校验审批节点的 `department`，C06 第 10 节）。"""
        with self._uow.begin() as uow:
            row = uow.connection.execute(
                select(pf_department).where(pf_department.c.department_id == department_id)).one_or_none()
        return None if row is None else Department(department_id=row.department_id, name=row.name, parent_id=row.parent_id)

    # ------------------------------------------------------------ 写入

    def ensure_admin(self) -> bool:
        """ID-06：没有 admin 时创建 admin / admin123..，启用，分配 ADMIN 角色；已存在时不改任何内容。返回是否新建。"""
        with self._uow.begin() as uow:
            conn = uow.connection
            if conn.execute(select(func.count()).select_from(pf_user).where(pf_user.c.username == ADMIN_USERNAME)).scalar_one():
                return False
            self._insert(conn, ADMIN_USERNAME, ADMIN_DISPLAY_NAME, None, self._passwords.hash(ADMIN_PASSWORD), [ADMIN_ROLE], True)
            uow.commit()
            return True

    def create_account(self, username: str, display_name: str, department_id: str | None, password_hash: str,
                       role_codes: Sequence[str], enabled: bool = True) -> AccountRecord:
        """新建账号；账号名已存在时抛 422 VALIDATION_FAILED（ID-07）。"""
        with self._uow.begin() as uow:
            conn = uow.connection
            if conn.execute(select(func.count()).select_from(pf_user).where(pf_user.c.username == username)).scalar_one():
                raise _duplicate_username(username)
            uid = self._insert(conn, username, display_name, department_id, password_hash, role_codes, enabled)
            created = _load(conn, pf_user.c.user_id == uid)
            uow.commit()
        assert created is not None
        return created

    def update_account(self, user_id: str, display_name: str, department_id: str | None, role_codes: Sequence[str],
                       enabled: bool) -> tuple[AccountRecord, AccountRecord] | None:
        """修改姓名、部门、角色和启用状态，在一个事务内完成，账号版本加一（ID-05）。返回（修改前，修改后）；账号不存在时为 None。"""
        uid = _uid(user_id)
        if uid is None:
            return None
        with self._uow.begin() as uow:
            conn = uow.connection
            before = _load(conn, pf_user.c.user_id == uid, lock=True)
            if before is None:
                return None
            conn.execute(update(pf_user).where(pf_user.c.user_id == uid).values(
                display_name=display_name, department_id=department_id, enabled=1 if enabled else 0,
                version=pf_user.c.version + 1))
            wanted = list(dict.fromkeys(role_codes))
            removed = [c for c in before.role_codes if c not in wanted]
            added = [c for c in wanted if c not in before.role_codes]
            if removed:
                conn.execute(delete(pf_user_role).where(pf_user_role.c.user_id == uid, pf_user_role.c.role_code.in_(removed)))
            if added:
                conn.execute(insert(pf_user_role), [{"user_id": uid, "role_code": c} for c in added])
            after = _load(conn, pf_user.c.user_id == uid)
            uow.commit()
        assert after is not None
        return before, after

    def set_password_hash(self, user_id: str, password_hash: str) -> bool:
        """改写密码哈希（管理员改密码、自己改密码、BCrypt 升级为 Argon2）；账号不存在时返回 False。"""
        uid = _uid(user_id)
        if uid is None:
            return False
        with self._uow.begin() as uow:
            changed = uow.connection.execute(update(pf_user).where(pf_user.c.user_id == uid)
                                             .values(password_hash=password_hash)).rowcount
            uow.commit()
        return bool(changed)

    def create_department(self, name: str, parent_id: str | None) -> DepartmentRecord:
        with self._uow.begin() as uow:
            department_id = str(self._next_id(uow.connection, DEPARTMENT_SEQUENCE))
            uow.connection.execute(insert(pf_department).values(department_id=department_id, name=name, parent_id=parent_id))
            uow.commit()
        return DepartmentRecord(department_id, name, parent_id)

    def update_department(self, department_id: str, name: str, parent_id: str | None) -> DepartmentRecord | None:
        with self._uow.begin() as uow:
            changed = uow.connection.execute(update(pf_department).where(pf_department.c.department_id == department_id)
                                             .values(name=name, parent_id=parent_id)).rowcount
            uow.commit()
        return DepartmentRecord(department_id, name, parent_id) if changed else None

    def delete_department(self, department_id: str) -> bool:
        """删除部门。账号上记的部门编号不改（旧系统删除部门时也不改人员的部门）。"""
        with self._uow.begin() as uow:
            changed = uow.connection.execute(delete(pf_department).where(pf_department.c.department_id == department_id)).rowcount
            uow.commit()
        return bool(changed)

    def _insert(self, conn: Connection, username: str, display_name: str, department_id: str | None, password_hash: str,
                role_codes: Sequence[str], enabled: bool) -> int:
        uid = self._next_id(conn, USER_SEQUENCE)
        conn.execute(insert(pf_user).values(user_id=uid, username=username, display_name=display_name,
                                            department_id=department_id, enabled=1 if enabled else 0,
                                            password_hash=password_hash, version=1))
        codes = list(dict.fromkeys(role_codes))
        if codes:
            conn.execute(insert(pf_user_role), [{"user_id": uid, "role_code": c} for c in codes])
        return uid
