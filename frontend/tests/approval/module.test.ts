/**
 * C11 契约测试（frontend-approval 部分）：用 ShellApi 的模拟实现装载模块，路由 `/approval`（待办）和
 * `/approval/:approvalId`（审批详情，通知链接和审批进度弹窗打开它）注册成功，install 只依赖 ShellApi。
 */
import { describe, expect, it } from 'vitest';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import { approvalModule, isApprovalModuleInstalled, useApprovalShell } from '../../src/modules/approval';

describe('frontend-approval 模块装载（C11）', () => {
  it('导出 FrontendModule：名称 approval，路由 /approval 和 /approval/:approvalId', () => {
    expect(approvalModule.name).toBe('approval');
    expect(approvalModule.routes.map(r => [r.path, r.name, r.props ?? false])).toEqual([
      ['/approval', 'approval', false],
      ['/approval/:approvalId', 'approval-detail', true]
    ]);
  });

  it('install 只接收 ShellApi', () => {
    const { shell } = createFakeShell();
    expect(isApprovalModuleInstalled()).toBe(false);
    approvalModule.install(shell);
    expect(isApprovalModuleInstalled()).toBe(true);
    expect(useApprovalShell()).toBe(shell);
  });
});
