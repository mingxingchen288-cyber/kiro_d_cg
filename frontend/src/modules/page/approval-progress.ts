/**
 * 审批进度弹窗（FP-16，`renderers/ApprovalProgressDialog.vue`）的显示文字：节点状态、方式和每个审批人的处理情况。
 * 内容来自 GET /api/approvals/{approvalId}（C09 第 6 节）；文字同旧系统 `ApprovalDetailDialog.vue` 的 `statusText`。
 */
import type { ApprovalDetail } from '../../contracts/http';

export type ProgressStep = ApprovalDetail['steps'][number];

export const STEP_STATUS: Record<string, string> = {
  passed: '已通过',
  pending: '待处理',
  rejected: '已驳回',
  upcoming: '未到',
  withdrawn: '已撤回'
};

// withdrawn：审批撤回或被驳回时还没处理的审批人（旧系统 CANCELED）；skipped：或签节点有人通过后，同一节点其余还没处理的
// 审批人（旧系统 SKIPPED，显示"已跳过"）
export const MEMBER_STATUS: Record<string, string> = {
  passed: '已通过',
  pending: '待处理',
  rejected: '已驳回',
  withdrawn: '已撤回',
  skipped: '已跳过'
};

export const MODE: Record<string, string> = { or: '或签', and: '会签' };

/** 一个节点的审批人："系统管理员（已通过，系统管理员 2026-10-30 10:00:00）；测试审批人（已跳过）" */
export function membersText(step: ProgressStep) {
  return step.members
    .map(m => {
      const by = m.processedBy ? `，${m.processedBy.displayName} ${m.processedAt?.replace('T', ' ') ?? ''}` : '';
      const comment = m.comment ? `，意见：${m.comment}` : '';
      return `${m.name}（${MEMBER_STATUS[m.status] ?? m.status}${by}${comment}）`;
    })
    .join('；');
}
