/**
 * 前端模块的注册和挂载（C11 `FrontendModule`）：每个模块注册时调用一次 `install(shell)`，路由挂在外壳的主布局下。
 *
 * 模块的路由组件由页签直接挂载（layouts/modules/global-content），按路由名称找组件，所以每条有组件的路由都要有名称；
 * 模块没有写名称的，外壳用"模块名 + 路径"补上。
 */
import type { RouteComponent, RouteRecordRaw } from 'vue-router';
import type { FrontendModule, ShellApi } from '../../contracts/shell';

/** C11 的模块名，也是菜单、路由前缀的顺序 */
export const MODULE_NAMES: FrontendModule['name'][] = ['page', 'config', 'approval', 'admin'];

export function isFrontendModule(value: unknown): value is FrontendModule {
  if (!value || typeof value !== 'object') return false;
  const v = value as Partial<FrontendModule>;
  return (
    typeof v.name === 'string' &&
    (MODULE_NAMES as string[]).includes(v.name) &&
    Array.isArray(v.routes) &&
    typeof v.install === 'function'
  );
}

/**
 * 从模块文件的导出中挑出 FrontendModule（C11 没有规定导出名，缺口见 contract-gaps.md 第 1 条），按 C11 表中的顺序排列。
 * `loaded` 的键为文件路径，值为该文件的全部导出。
 */
export function pickModules(loaded: Record<string, Record<string, unknown>>): FrontendModule[] {
  const found = Object.values(loaded).flatMap(exports => Object.values(exports).filter(isFrontendModule));
  return [...new Set(found)].sort((a, b) => MODULE_NAMES.indexOf(a.name) - MODULE_NAMES.indexOf(b.name));
}

function named(route: RouteRecordRaw, module: string, parent: string): RouteRecordRaw {
  const path = route.path.startsWith('/') ? route.path : `${parent.replace(/\/$/, '')}/${route.path}`;
  const children = route.children?.map(child => named(child, module, path));
  const hasComponent = 'component' in route || 'components' in route;
  const name = route.name ?? (hasComponent ? `${module}:${path}` : undefined);
  return { ...route, ...(name === undefined ? {} : { name }), ...(children ? { children } : {}) } as RouteRecordRaw;
}

export class ModuleRegistry {
  private readonly installed: FrontendModule[] = [];

  /** 注册模块：每个模块调用一次 `install(shell)` */
  register(modules: FrontendModule[], shell: ShellApi) {
    for (const module of modules) {
      module.install(shell);
      this.installed.push(module);
    }
  }

  get modules(): readonly FrontendModule[] {
    return this.installed;
  }

  has(name: FrontendModule['name']) {
    return this.installed.some(module => module.name === name);
  }

  /** 各模块路由的名称（同名的 elegant 生成路由由模块的路由代替，例如 `page`） */
  routeNames(): string[] {
    const names: string[] = [];
    const collect = (routes: RouteRecordRaw[]) => {
      for (const route of routes) {
        if (typeof route.name === 'string') names.push(route.name);
        collect(route.children ?? []);
      }
    };
    for (const module of this.installed) collect(module.routes);
    return names;
  }

  /**
   * 挂在布局下的路由：每条顶层路由包一层布局（与 elegant 单级路由的写法相同），原路由成为路径为空的子路由。
   * 需要登录（不是 constant 路由），页签标题由外壳按菜单设置。
   */
  layoutRoutes(layout: RouteComponent): RouteRecordRaw[] {
    return this.installed.flatMap(module =>
      module.routes.map(route => {
        const child = named(route, module.name, '');
        return {
          path: route.path,
          component: layout,
          meta: { title: (route.meta?.title as string | undefined) ?? '' },
          children: [{ ...child, path: '' } as RouteRecordRaw]
        } satisfies RouteRecordRaw;
      })
    );
  }
}
