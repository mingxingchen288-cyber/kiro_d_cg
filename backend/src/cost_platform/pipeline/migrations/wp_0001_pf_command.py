"""命令记录表 PF_COMMAND（write-pipeline 第 2 节、WP-01）。"""

import sqlalchemy as sa
from alembic import op

revision = "wp_0001"
down_revision = None
branch_labels = ("pipeline",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pf_command",
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("page", sa.String(64)),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.Text),
        sa.Column("audit_diff", sa.Text),  # AUDIT 是 Oracle 保留字
        sa.Column("created_at", sa.TIMESTAMP, nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP),
        sa.PrimaryKeyConstraint("user_id", "request_key", name="pk_pf_command"),
    )


def downgrade() -> None:
    op.drop_table("pf_command")
