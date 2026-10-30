/**
 * 审批进度弹窗（FP-16）的文字：用户修改被审批锁定的单据时弹出，各级节点的审批人和处理情况（C09 第 6 节）。
 */
import { describe, expect, it } from 'vitest';
import { MEMBER_STATUS, type ProgressStep, membersText } from '../../src/modules/page/approval-progress';

describe('审批进度弹窗的审批人', () => {
  it('或签节点一人通过后，另一人显示已跳过', () => {
    const step: ProgressStep = {
      level: 1,
      flow: 'COST_TO_GOODS',
      flowName: '成本明细改价审批',
      node: '管理员审批',
      mode: 'or',
      status: 'passed',
      members: [
        {
          type: 'user',
          id: '1',
          name: '系统管理员',
          status: 'passed',
          processedBy: { userId: '1', displayName: '系统管理员' },
          processedAt: '2026-10-30T10:00:00',
          comment: null
        },
        {
          type: 'user',
          id: '200',
          name: '第二审批人',
          status: 'skipped',
          processedBy: null,
          processedAt: null,
          comment: null
        }
      ]
    };
    expect(membersText(step)).toBe('系统管理员（已通过，系统管理员 2026-10-30 10:00:00）；第二审批人（已跳过）');
  });

  it('五种审批人状态都有文字', () => {
    expect(['pending', 'passed', 'rejected', 'withdrawn', 'skipped'].map(s => MEMBER_STATUS[s])).toEqual([
      '待处理',
      '已通过',
      '已驳回',
      '已撤回',
      '已跳过'
    ]);
  });
});
