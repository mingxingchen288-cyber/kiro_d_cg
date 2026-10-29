"""identity 拥有的表（模块说明第 2 节），供账号存储用 SQLAlchemy Core 生成 SQL。

表结构以迁移为准（`migrations/id_0001_pf_user.py`、`id_0002_pf_department_seq.py`），这里只描述查询要用的列。
用表对象而不是手写 SQL 文本，是为了同一份查询既能在 d_cg（Oracle）上执行，也能在 contracts 的
`FakeUnitOfWorkFactory`（内存 SQLite）上做模拟验证；分页等方言差异由 SQLAlchemy 编译。
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

pf_department = sa.Table(
    "pf_department",
    metadata,
    sa.Column("department_id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(128), nullable=False),
    sa.Column("parent_id", sa.String(64)),
)

pf_user = sa.Table(
    "pf_user",
    metadata,
    sa.Column("user_id", sa.BigInteger, primary_key=True, autoincrement=False),
    sa.Column("username", sa.String(64), nullable=False, unique=True),
    sa.Column("display_name", sa.String(128), nullable=False),
    sa.Column("department_id", sa.String(64)),
    sa.Column("enabled", sa.Integer, nullable=False),
    sa.Column("password_hash", sa.String(256)),
    sa.Column("version", sa.BigInteger, nullable=False),
)

pf_user_role = sa.Table(
    "pf_user_role",
    metadata,
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("role_code", sa.String(64), nullable=False),
    sa.PrimaryKeyConstraint("user_id", "role_code", name="pk_pf_user_role"),
)

USER_SEQUENCE = "pf_user_seq"
DEPARTMENT_SEQUENCE = "pf_department_seq"
