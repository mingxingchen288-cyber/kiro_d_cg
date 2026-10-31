/**
 * 菜单（C09 第 2 节 `/api/me` 的 `menus`，C11 的表）：把菜单项换成外壳的菜单，算出每项打开的路径。
 *
 * - `page` 项打开 `/page/<pageCode>`（frontend-page）；
 * - `config`、`admin` 项打开对应模块的页面。C09 的菜单项没有路径（缺口见 contract-gaps.md 第 2 条），外壳按顺序找：
 *   该模块中名称等于菜单 key 的路由 → 路径为 `/<kind>/<key>` 的路由 → `/<kind>`；都没有（模块没有注册）时不显示这一项；
 * - `group` 项是分组，子项都不显示时分组也不显示；
 * - 外壳的固定入口"待办"打开 frontend-approval 的 `/approval`（C11），该模块注册了才显示。
 */
import type { RouteRecordRaw } from 'vue-router';
import type { MenuItem } from '../../contracts/http';
import type { FrontendModule } from '../../contracts/shell';

export interface ShellMenu {
  key: string;
  title: string;
  /** 打开的路径；分组为 null */
  path: string | null;
  /** Iconify 图标名，取自菜单项的 `icon`（C09 v15、C06 v26，FS-08）；为空时用默认图标 VITE_MENU_ICON */
  icon?: string;
  children?: ShellMenu[];
}

type ModuleRoutes = Pick<FrontendModule, 'name' | 'routes'>;

interface FlatRoute {
  name: string | null;
  path: string;
}

function join(parent: string, path: string) {
  if (path.startsWith('/')) return path;
  if (!path) return parent;
  return `${parent.replace(/\/$/, '')}/${path}`;
}

function flatten(routes: RouteRecordRaw[], parent = ''): FlatRoute[] {
  return routes.flatMap(route => {
    const path = join(parent, route.path);
    const self: FlatRoute = { name: typeof route.name === 'string' ? route.name : null, path };
    return [self, ...flatten(route.children ?? [], path)];
  });
}

/** 模块中不带参数的路由路径 */
function staticPaths(module: ModuleRoutes | undefined): FlatRoute[] {
  return module ? flatten(module.routes).filter(route => !route.path.includes(':')) : [];
}

/** 菜单项打开的路径；对应的模块没有注册时为 null */
export function menuPath(item: MenuItem, modules: readonly ModuleRoutes[]): string | null {
  if (item.kind === 'group') return null;
  if (item.kind === 'page') return item.pageCode ? `/page/${encodeURIComponent(item.pageCode)}` : null;
  const routes = staticPaths(modules.find(module => module.name === item.kind));
  const byName = routes.find(route => route.name === item.key);
  if (byName) return byName.path;
  const byPath = routes.find(route => route.path === `/${item.kind}/${item.key}`);
  if (byPath) return byPath.path;
  return routes.some(route => route.path === `/${item.kind}`) ? `/${item.kind}` : null;
}

/** 菜单项的图标（FS-08）：配置了才带，同旧系统 `T_COST_RESOURCE.ICON` */
const iconOf = (item: MenuItem) => (item.icon ? { icon: item.icon } : {});

/** `/api/me` 的菜单换成外壳的菜单；`page` 项要有 frontend-page 注册才显示 */
export function buildMenus(items: MenuItem[], modules: readonly ModuleRoutes[]): ShellMenu[] {
  const hasPage = modules.some(module => module.name === 'page');
  return items.flatMap((item): ShellMenu[] => {
    if (item.kind === 'group') {
      const children = buildMenus(item.children ?? [], modules);
      return children.length ? [{ key: item.key, title: item.title, path: null, ...iconOf(item), children }] : [];
    }
    if (item.kind === 'page' && !hasPage) return [];
    const path = menuPath(item, modules);
    return path ? [{ key: item.key, title: item.title, path, ...iconOf(item) }] : [];
  });
}

/** 外壳的固定入口"待办"（C11）：frontend-approval 注册了且有 `/approval` 路由时出现 */
export function todoMenu(modules: readonly ModuleRoutes[]): ShellMenu | null {
  const routes = staticPaths(modules.find(module => module.name === 'approval'));
  return routes.some(route => route.path === '/approval')
    ? { key: 'shell-approval-todo', title: '待办', path: '/approval', icon: 'mdi:clipboard-check-outline' }
    : null;
}

function walk(menus: ShellMenu[]): ShellMenu[] {
  return menus.flatMap(menu => [menu, ...walk(menu.children ?? [])]);
}

/** 当前路径对应的菜单：路径相同的优先，否则取路径前缀最长的一项（例如 `/approval/203` 对应"待办"） */
export function menuOfPath(menus: ShellMenu[], path: string): ShellMenu | null {
  const leaves = walk(menus).filter(menu => menu.path);
  const exact = leaves.find(menu => menu.path === path);
  if (exact) return exact;
  const prefixed = leaves.filter(menu => path.startsWith(`${menu.path!.replace(/\/$/, '')}/`));
  prefixed.sort((a, b) => b.path!.length - a.path!.length);
  return prefixed[0] ?? null;
}

/** 按 key 找菜单 */
export function menuOfKey(menus: ShellMenu[], key: string): ShellMenu | null {
  return walk(menus).find(menu => menu.key === key) ?? null;
}
