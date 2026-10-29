"""通知意图（AP-17）：按各审批流的 `notify` 生成，由 delivery 登记和发送。

- 进入第 1 级为 `submitted`，进入之后的级别为 `levelEntered`，审批结束为 `passed`、`rejected` 或 `withdrawn`；
- `levelApprovers` 指该审批流本级节点的审批人（角色为它的全部启用账号），`applicant` 为发起人；
- 同一事件中同一接收人只收一条；标题固定为"您有来自于{页面标题}页面，业务单据为{来源单据号}的审批"，`passed`、`rejected`、
  `withdrawn` 在末尾分别加"已通过""已驳回""已撤回"；正文为空；链接为 `/approval/{审批编号}`（frontend-approval FA-05）。
"""

from __future__ import annotations

from cost_platform.contracts.types import NotificationIntent, NotifyRole, NotifyUsers

from .approvers import Directory
from .model import ApprovalRecord

EVENTS = {"submitted": "approvalSubmitted", "levelEntered": "approvalLevelEntered", "passed": "approvalPassed",
          "rejected": "approvalRejected", "withdrawn": "approvalWithdrawn"}
_SUFFIX = {"passed": "已通过", "rejected": "已驳回", "withdrawn": "已撤回"}


def title(page_title: str, record_key: str, event: str) -> str:
    return f"您有来自于{page_title}页面，业务单据为{record_key}的审批{_SUFFIX.get(event, '')}"


def intents(record: ApprovalRecord, event: str, directory: Directory) -> list[NotificationIntent]:
    """这个事件的通知：`levelApprovers` 取各审批流当前级别节点的审批人。"""
    recipients: dict[str, None] = {}
    for flow in record.flows:
        for rule in flow.config.notify:
            if rule.event != event:
                continue
            to = rule.to
            if to == "levelApprovers":
                nodes = [n for n in record.progress.nodes if n.flow == flow.code and n.level == record.progress.level]
                found = directory.recipients(m for n in nodes for m in n.members)
            elif to == "applicant":
                found = [record.applicant_id]
            elif isinstance(to, NotifyUsers):
                found = list(to.users)
            elif isinstance(to, NotifyRole):
                found = sorted(directory.role_users(to.role))
            else:
                found = []
            for user_id in found:
                recipients[user_id] = None
    if not recipients:
        return []
    return [NotificationIntent(event=EVENTS[event], recipients=tuple(recipients),
                               title=title(record.page_title, record.source.record_key, event), body="",
                               link=f"/approval/{record.approval_id}")]
