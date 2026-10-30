"""approval 拥有的表（模块说明第 2 节），供审批存储用 SQLAlchemy Core 生成 SQL。

表结构以迁移为准（`migrations/ap_0001_pf_approval.py`、`ap_0002_final_view.py`），这里描述同样的列。用表对象而不是手写 SQL 文本，是为了同一份
查询既能在 d_cg（Oracle）上执行，也能在 contracts 的 `FakeUnitOfWorkFactory`（内存 SQLite）上做模拟验证。

- `pf_approval`：审批实例；提交时命中的审批流定义、触发行、待审修改、进度、参数、执行结果、结束时的修改内容放在 CLOB
  列中（JSON）。
- `pf_approval_affected`：受影响单据的行和勾选。
- `pf_approval_record`：处理记录。
- `pf_approval_freeze`：冻结记录，（根表、主键）为主键：同一份数据同一时间只属于一个未结束的审批，两个命令同时冻结
  同一份数据时，后写入的因主键冲突失败（AP-06）。审批结束时删除。
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

pf_approval = sa.Table(
    "pf_approval",
    metadata,
    sa.Column("approval_id", sa.Numeric(19, 0), primary_key=True, autoincrement=False),
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
    sa.Column("final_view", sa.Text),  # 迁移 ap_0002：结束那一刻的修改内容（ApprovalView 的 JSON），待审时为空
)

pf_approval_affected = sa.Table(
    "pf_approval_affected",
    metadata,
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

pf_approval_record = sa.Table(
    "pf_approval_record",
    metadata,
    sa.Column("approval_id", sa.Numeric(19, 0), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("level_no", sa.Integer, nullable=False),  # LEVEL 是 Oracle 保留字
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("user_name", sa.String(128), nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("acted_at", sa.DateTime, nullable=False),
    sa.Column("remark", sa.String(2000)),  # COMMENT 是 Oracle 保留字
    sa.Column("checked", sa.Text, nullable=False),
    sa.Column("params", sa.Text, nullable=False),
    sa.PrimaryKeyConstraint("approval_id", "seq", name="pk_pf_approval_record"),
)

pf_approval_freeze = sa.Table(
    "pf_approval_freeze",
    metadata,
    sa.Column("root_table", sa.String(64), nullable=False),
    sa.Column("record_key", sa.String(64), nullable=False),
    sa.Column("approval_id", sa.Numeric(19, 0), nullable=False),
    sa.PrimaryKeyConstraint("root_table", "record_key", name="pk_pf_approval_freeze"),
)

sa.Index("ix_pf_approval_status", pf_approval.c.status)
sa.Index("ix_pf_approval_applicant", pf_approval.c.applicant_id)
sa.Index("ix_pf_approval_freeze_owner", pf_approval_freeze.c.approval_id)

APPROVAL_SEQUENCE = "pf_approval_seq"
