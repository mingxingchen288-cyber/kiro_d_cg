/**
 * frontend-page 模块（C11）：导出 `FrontendModule`，路由 `/page/:pageCode`。
 * 由 assembly 注册到外壳；注册前（T-AS-3 之前）由 `src/views/page/[pageCode].vue` 用过渡的 ShellApi 调用 install。
 */
import type { FrontendModule, ShellApi } from '../../contracts/shell';

let installed: ShellApi | null = null;

export const pageModule: FrontendModule = {
  name: 'page',
  routes: [
    {
      path: '/page/:pageCode',
      name: 'page',
      component: () => import('./renderers/PageRoute.vue'),
      props: true
    }
  ],
  install(shell: ShellApi) {
    installed = shell;
  }
};

export function isPageModuleInstalled() {
  return installed !== null;
}

/** 已注册的 ShellApi；没有注册时报错 */
export function usePageShell(): ShellApi {
  if (!installed) throw new Error('页面模块还没有注册到外壳（C11 FrontendModule.install）');
  return installed;
}
