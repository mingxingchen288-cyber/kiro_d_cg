"""个人列配置表 PF_PERSONAL_CONFIG（queries-export 第 2 节、QE-07）：按（用户、页面、表格）一行。"""

import sqlalchemy as sa
from alembic import op

revision = "qe_0001"
down_revision = None
branch_labels = ("queries",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pf_personal_config",
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("page_code", sa.String(64), nullable=False),
        sa.Column("grid_key", sa.String(64), nullable=False),  # master、明细实体，或页面级的 #page
        sa.Column("columns_json", sa.Text),  # PersonalGrid 的 JSON；#page 行为空
        sa.Column("detail_mode", sa.String(16)),  # 只在 #page 行：tabs 或 stack
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "page_code", "grid_key", name="pk_pf_personal_config"),
    )


def downgrade() -> None:
    op.drop_table("pf_personal_config")
