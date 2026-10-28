"""账号、账号与角色、部门（identity 第 2 节）。"""

import sqlalchemy as sa
from alembic import op

revision = "id_0001"
down_revision = None
branch_labels = ("identity",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pf_department",
        sa.Column("department_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("parent_id", sa.String(64)),
    )
    op.create_table(
        "pf_user",
        sa.Column("user_id", sa.Numeric(19, 0), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("department_id", sa.String(64)),
        sa.Column("enabled", sa.Numeric(1, 0), nullable=False),
        sa.Column("password_hash", sa.String(256)),
        sa.Column("version", sa.Numeric(19, 0), nullable=False),
    )
    op.create_table(
        "pf_user_role",
        sa.Column("user_id", sa.Numeric(19, 0), nullable=False),
        sa.Column("role_code", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_code", name="pk_pf_user_role"),
    )
    op.execute("CREATE SEQUENCE pf_user_seq START WITH 1 NOCACHE")


def downgrade() -> None:
    op.execute("DROP SEQUENCE pf_user_seq")
    op.drop_table("pf_user_role")
    op.drop_table("pf_user")
    op.drop_table("pf_department")
