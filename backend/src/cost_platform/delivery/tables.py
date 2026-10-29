"""delivery 拥有的表（模块说明第 2 节）：投递记录 PF_DELIVERY、站内通知 PF_INBOX。

表结构以迁移为准（`migrations/dl_0001_pf_delivery.py`），这里只描述查询要用的列。用 SQLAlchemy Core 的表对象
生成 SQL，同一份查询既能在 d_cg（Oracle）上执行，也能在 contracts 的 `FakeUnitOfWorkFactory`（内存 SQLite）上
做模拟验证：`FOR UPDATE SKIP LOCKED` 和分页由方言编译，SQLite 没有行锁，`with_for_update` 在 SQLite 上自动省略。
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

pf_delivery = sa.Table(
    "pf_delivery",
    metadata,
    sa.Column("delivery_id", sa.String(36), primary_key=True),
    sa.Column("command_user", sa.String(64), nullable=False),   # 所属命令：（用户、请求键），与 PF_COMMAND 的主键相同
    sa.Column("request_key", sa.String(36), nullable=False),
    sa.Column("event", sa.String(64), nullable=False),          # NotificationIntent.event，例如 approvalSubmitted
    sa.Column("recipient", sa.String(64), nullable=False),      # 接收人的用户编号
    sa.Column("title", sa.String(1000), nullable=False),
    sa.Column("body", sa.Text),                                 # Oracle 把空串存为 NULL，读出时还原为空串
    sa.Column("link", sa.String(500)),
    sa.Column("status", sa.String(16), nullable=False),         # pending、sent、failed、abandoned
    sa.Column("attempts", sa.Integer, nullable=False),          # 已经做过的发送次数（含首次）
    sa.Column("next_retry_at", sa.DateTime),                    # sent、abandoned 时为空
    sa.Column("last_error", sa.String(2000)),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("sent_at", sa.DateTime),
)

pf_inbox = sa.Table(
    "pf_inbox",
    metadata,
    sa.Column("delivery_id", sa.String(36), primary_key=True),  # 按投递编号去重：一条投递记录只有一条站内通知
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("title", sa.String(1000), nullable=False),
    sa.Column("body", sa.Text),
    sa.Column("link", sa.String(500)),
    sa.Column("created_at", sa.DateTime, nullable=False),       # 写入站内通知的时间
    sa.Column("read_at", sa.DateTime),                          # 为空表示未读
)
