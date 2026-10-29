/**
 * frontend-approval 模块（C11）：导出 `FrontendModule`，路由 `/approval`（待办）和 `/approval/:approvalId`（审批详情）。
 * 审批详情由待办列表、站内通知的链接 `/approval/{approvalId}`（FA-05）和通用页面的审批进度弹窗按路由打开。
 * 由 assembly / frontend-shell 注册到外壳。
 */
import type { FrontendModule, ShellApi } from '../../contracts/shell';

let installed: ShellApi | null = null;

export const approvalModule: FrontendModule = {
  name: 'approval',
  routes: [
    {
      path: '/approval',
      name: 'approval',
      component: () => import('./renderers/TodoRoute.vue'),
      meta: { title: '待办' }
    },
    {
      path: '/approval/:approvalId',
      name: 'approval-detail',
      component: () => import('./renderers/DetailRoute.vue'),
      props: true,
      meta: { title: '审批详情' }
    }
  ],
  install(shell: ShellApi) {
    installed = shell;
  }
};

export function isApprovalModuleInstalled() {
  return installed !== null;
}

/** 已注册的 ShellApi；没有注册时报错 */
export function useApprovalShell(): ShellApi {
  if (!installed) throw new Error('审批模块还没有注册到外壳（C11 FrontendModule.install）');
  return installed;
}
