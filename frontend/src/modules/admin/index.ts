/**
 * frontend-admin 模块（C11）：导出 `FrontendModule`，路由 `/admin`，由 assembly 注册到外壳。
 *
 * - 每个管理功能一条不带参数的路由 `/admin/<key>`（`key` 为下面 `ADMIN_SECTIONS` 的键）；`/admin` 用 Tab 显示全部功能。
 *   外壳（`modules/shell/menus.ts` 的 `menuPath`）把类型为 `admin` 的菜单项按 `/admin/<菜单项 key>` 打开，
 *   只认不带参数的路由，所以不用 `/admin/:section`。C11 没有写这一条，见 contract-gaps.md 第 4 条。
 * - FM-01：只对管理员角色显示。菜单项只对管理员出现（C11）；直接打开路由时，非管理员看到提示，不调用任何接口。
 */
import { defineComponent, h, markRaw } from 'vue';
import type { RouteRecordRaw } from 'vue-router';
import type { RoleRef } from '../../contracts/http';
import type { FrontendModule, ShellApi } from '../../contracts/shell';

export const ADMIN_SECTIONS = [
  { key: 'accounts', title: '人员管理' },
  { key: 'departments', title: '部门管理' },
  { key: 'role-members', title: '角色人员' },
  { key: 'deliveries', title: '投递记录' },
  { key: 'command-review', title: '命令审查' }
] as const;

export type AdminSection = (typeof ADMIN_SECTIONS)[number]['key'];

export function adminSection(key: string | undefined): AdminSection | null {
  return ADMIN_SECTIONS.find(s => s.key === key)?.key ?? null;
}

/** FM-01：当前角色是管理员时才显示管理功能 */
export function canUseAdmin(role: RoleRef | null | undefined) {
  return Boolean(role?.admin);
}

let installed: ShellApi | null = null;

/**
 * 路由组件：AdminRoute 包一层、固定传入功能的键。外壳按页签直接挂载路由组件、不传路由的 props
 * （`layouts/modules/global-content/index.vue`），所以不用 `props: { section }`。
 */
function routeComponent(section: AdminSection | null) {
  return () =>
    import('./renderers/AdminRoute.vue').then(m =>
      markRaw(
        defineComponent({
          name: section ? `AdminRoute-${section}` : 'AdminRoute-all',
          setup: () => () => h(m.default, { section: section ?? undefined })
        })
      )
    );
}

const routes: RouteRecordRaw[] = [
  { path: '/admin', name: 'admin', component: routeComponent(null), meta: { title: '系统管理' } },
  ...ADMIN_SECTIONS.map(
    (section): RouteRecordRaw => ({
      path: `/admin/${section.key}`,
      name: `admin-${section.key}`,
      component: routeComponent(section.key),
      meta: { title: section.title }
    })
  )
];

export const adminModule: FrontendModule = {
  name: 'admin',
  routes,
  install(shell: ShellApi) {
    installed = shell;
  }
};

export function isAdminModuleInstalled() {
  return installed !== null;
}

/** 已注册的 ShellApi；没有注册时报错 */
export function useAdminShell(): ShellApi {
  if (!installed) throw new Error('管理模块还没有注册到外壳（C11 FrontendModule.install）');
  return installed;
}
