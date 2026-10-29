/**
 * frontend-config 模块（C11）：导出 `FrontendModule`，路由 `/config`，由 assembly / frontend-shell 注册到外壳。
 * 页面内的分区用查询参数 `tab` 切换（同旧系统 meta-config 的 `?tab=`）：unified 一体化配置（菜单树 + 页面配置）、
 * lookup、permission 角色权限、dict 字典、items 全部配置项。
 *
 * FC-01：只对管理员角色显示。菜单由后端按角色给出（C11：类型为 config 的项只对管理员出现）；
 * 路由组件再按 `session.role.admin` 判断，非管理员只显示提示，不发配置接口请求。
 */
import type { FrontendModule, ShellApi } from '../../contracts/shell';

let installed: ShellApi | null = null;

export const CONFIG_PATH = '/config';

export const configModule: FrontendModule = {
  name: 'config',
  routes: [
    {
      path: CONFIG_PATH,
      name: 'config',
      component: () => import('./views/ConfigHome.vue')
    }
  ],
  install(shell: ShellApi) {
    installed = shell;
  }
};

export function isConfigModuleInstalled() {
  return installed !== null;
}

/** 已注册的 ShellApi；没有注册时报错 */
export function useConfigShell(): ShellApi {
  if (!installed) throw new Error('配置模块还没有注册到外壳（C11 FrontendModule.install）');
  return installed;
}

/** FC-01：当前角色是不是管理员 */
export function canConfigure(session: ShellApi['session']) {
  return session.role.value?.admin === true;
}
