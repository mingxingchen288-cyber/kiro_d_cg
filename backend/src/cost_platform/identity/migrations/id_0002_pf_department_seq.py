"""部门编号的序列 PF_DEPARTMENT_SEQ：管理员新建部门时取号（旧系统部门管理页的新增，见 contract-gaps.md）。

id_0001 已在 d_cg 上执行，表结构不改，只加序列。本迁移由合并后统一执行，子代理不执行。
"""

from alembic import op

revision = "id_0002"
down_revision = "id_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE pf_department_seq START WITH 1 NOCACHE")


def downgrade() -> None:
    op.execute("DROP SEQUENCE pf_department_seq")
