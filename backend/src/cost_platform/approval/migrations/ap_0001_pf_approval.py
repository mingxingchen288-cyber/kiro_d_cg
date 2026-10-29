"""审批实例、受影响单据的行、处理记录、冻结记录（approval 第 2 节），以及审批编号的序列 PF_APPROVAL_SEQ。

列与 `approval/tables.py` 一致。冻结记录以（根表、主键）为主键，同一份数据同一时间只属于一个未结束的审批（AP-06）。
本迁移由合并后统一执行，子代理不执行。
"""

import sqlalchemy as sa
from alembic import op

revision = "ap_0001"
down_revision = None
branch_labels = ("approval",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pf_approval",
        sa.Column("approval_id", sa.Numeric(19, 0), primary_key=True),
        sa.Column("page", sa.String(64), nullable=False),
        sa.Column("page_title", sa.String(256), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("operation_label", sa.String(128), nullable=False),
        sa.Column("source_entity", sa.String(64), nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("source_label", sa.String(512)),
        sa.Column("applicant_id", sa.String(64), nullable=False),
        sa.Column("applicant_name", sa.String(128), nullable=False),
        sa.Column("applicant_dept", sa.String(64)),
        sa.Column("submitted_at", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_level", sa.Integer, nullable=False),
        sa.Column("flows", sa.Text, nullable=False),
        sa.Column("triggers", sa.Text, nullable=False),
        sa.Column("pending", sa.Text, nullable=False),
        sa.Column("pending_status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Text, nullable=False),
        sa.Column("params", sa.Text, nullable=False),
        sa.Column("result", sa.Text, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_index("ix_pf_approval_status", "pf_approval", ["status"])
    op.create_index("ix_pf_approval_applicant", "pf_approval", ["applicant_id"])
    op.create_table(
        "pf_approval_affected",
        sa.Column("approval_id", sa.Numeric(19, 0), nullable=False),
        sa.Column("flow", sa.String(64), nullable=False),
        sa.Column("block", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("target_table", sa.String(64), nullable=False),
        sa.Column("row_key", sa.String(64)),
        sa.Column("missing", sa.Integer, nullable=False),
        sa.Column("triggers", sa.String(2000), nullable=False),
        sa.Column("checked", sa.Integer, nullable=False),
        sa.Column("row_data", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("approval_id", "flow", "block", "seq", name="pk_pf_approval_affected"),
    )
    op.create_table(
        "pf_approval_record",
        sa.Column("approval_id", sa.Numeric(19, 0), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("level_no", sa.Integer, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("user_name", sa.String(128), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("acted_at", sa.DateTime, nullable=False),
        sa.Column("remark", sa.String(2000)),
        sa.Column("checked", sa.Text, nullable=False),
        sa.Column("params", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("approval_id", "seq", name="pk_pf_approval_record"),
    )
    op.create_table(
        "pf_approval_freeze",
        sa.Column("root_table", sa.String(64), nullable=False),
        sa.Column("record_key", sa.String(64), nullable=False),
        sa.Column("approval_id", sa.Numeric(19, 0), nullable=False),
        sa.PrimaryKeyConstraint("root_table", "record_key", name="pk_pf_approval_freeze"),
    )
    op.create_index("ix_pf_approval_freeze_owner", "pf_approval_freeze", ["approval_id"])
    op.execute("CREATE SEQUENCE pf_approval_seq START WITH 1 NOCACHE")


def downgrade() -> None:
    op.execute("DROP SEQUENCE pf_approval_seq")
    op.drop_table("pf_approval_freeze")
    op.drop_table("pf_approval_record")
    op.drop_table("pf_approval_affected")
    op.drop_table("pf_approval")
