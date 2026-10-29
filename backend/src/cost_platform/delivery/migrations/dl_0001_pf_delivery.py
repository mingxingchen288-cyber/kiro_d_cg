"""投递记录 PF_DELIVERY、站内通知 PF_INBOX（delivery 第 2 节，DL-01–DL-05）。"""

import sqlalchemy as sa
from alembic import op

revision = "dl_0001"
down_revision = None
branch_labels = ("delivery",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pf_delivery",
        sa.Column("delivery_id", sa.String(36), primary_key=True),
        sa.Column("command_user", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("recipient", sa.String(64), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("link", sa.String(500)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("next_retry_at", sa.TIMESTAMP),
        sa.Column("last_error", sa.String(2000)),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False),
        sa.Column("sent_at", sa.TIMESTAMP),
    )
    # 后台重试任务按（状态、下次重试时间）找到期的记录；管理接口按状态筛选
    op.create_index("ix_pf_delivery_due", "pf_delivery", ["status", "next_retry_at"])
    op.create_table(
        "pf_inbox",
        sa.Column("delivery_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("link", sa.String(500)),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False),
        sa.Column("read_at", sa.TIMESTAMP),
    )
    op.create_index("ix_pf_inbox_user", "pf_inbox", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_pf_inbox_user", table_name="pf_inbox")
    op.drop_table("pf_inbox")
    op.drop_index("ix_pf_delivery_due", table_name="pf_delivery")
    op.drop_table("pf_delivery")
