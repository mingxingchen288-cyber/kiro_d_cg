/**
 * C11 契约测试（外壳部分）：用 ShellApi 的模拟实现装载每个模块，install 只调用一次、只拿到 ShellApi；
 * 模块的路由挂在外壳的主布局下，`/page/COST_PINGGU`、`/approval/203` 能打开。
 * frontend-config、frontend-approval、frontend-admin 由别的任务开发，这里用按 C11 写的替代模块。
 */
import { createMemoryHistory, createRouter } from 'vue-router';
import { describe, expect, it } from 'vitest';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import type { FrontendModule, ShellApi } from '../../src/contracts/shell';
import { pageModule, usePageShell } from '../../src/modules/page';
import { ModuleRegistry, pickModules } from '../../src/modules/shell/registry';

const Layout = { name: 'BaseLayout', render: () => null };
const View = { render: () => null };

function stubModule(name: FrontendModule['name'], routes: FrontendModule['routes']) {
  const received: ShellApi[] = [];
  const module: FrontendModule = { name, routes, install: shell => received.push(shell) };
  return { module, received };
}

describe('前端模块的注册和挂载（C11）', () => {
  it('每个模块 install 一次，拿到的就是外壳的 ShellApi；frontend-page 之后经它调用接口', () => {
    const { shell } = createFakeShell();
    const approval = stubModule('approval', [{ path: '/approval', name: 'approval-todo', component: View }]);
    const registry = new ModuleRegistry();

    registry.register([pageModule, approval.module], shell);

    expect(usePageShell()).toBe(shell);
    expect(approval.received).toEqual([shell]);
    expect(registry.has('page')).toBe(true);
    expect(registry.has('admin')).toBe(false);
    expect(registry.routeNames()).toEqual(['page', 'approval-todo']);
  });

  it('模块路由挂在主布局下：/page/COST_PINGGU 打开通用页面，页面编码来自路由参数；/approval/203 打开审批详情', () => {
    const { shell } = createFakeShell();
    const approval = stubModule('approval', [
      { path: '/approval', name: 'approval-todo', component: View },
      { path: '/approval/:approvalId', name: 'approval-detail', component: View, props: true }
    ]);
    const registry = new ModuleRegistry();
    registry.register([pageModule, approval.module], shell);
    const router = createRouter({ history: createMemoryHistory(), routes: registry.layoutRoutes(Layout) });

    const page = router.resolve('/page/COST_PINGGU');
    expect(page.name).toBe('page');
    expect(page.params).toEqual({ pageCode: 'COST_PINGGU' });
    expect(page.matched.map(record => record.components?.default)).toEqual([
      Layout,
      (pageModule.routes[0] as { component: unknown }).component
    ]);
    expect(page.matched[1].props.default).toBe(true);

    const detail = router.resolve('/approval/203');
    expect(detail.name).toBe('approval-detail');
    expect(detail.params).toEqual({ approvalId: '203' });
    expect(detail.matched[0].components?.default).toBe(Layout);
  });

  it('模块路由没写名称时外壳补上（页签按路由名称挂载组件），嵌套的子路由照常打开', () => {
    const { shell } = createFakeShell();
    const config = stubModule('config', [
      { path: '/config', component: View, children: [{ path: 'items/:type', component: View, props: true }] }
    ]);
    const registry = new ModuleRegistry();
    registry.register([config.module], shell);
    const router = createRouter({ history: createMemoryHistory(), routes: registry.layoutRoutes(Layout) });

    const items = router.resolve('/config/items/page');
    expect(items.name).toBe('config:/config/items/:type');
    expect(items.params).toEqual({ type: 'page' });
    expect(router.resolve('/config').name).toBe('config:/config');
  });

  it('从 src/modules/<模块>/index.ts 的导出中挑出 FrontendModule，按 C11 表的顺序排列', () => {
    const admin = stubModule('admin', []).module;
    const approval = stubModule('approval', []).module;

    const found = pickModules({
      '../admin/index.ts': { adminModule: admin, helper: () => 1 },
      '../page/index.ts': { pageModule, usePageShell },
      '../approval/index.ts': { default: approval }
    });

    expect(found.map(module => module.name)).toEqual(['page', 'approval', 'admin']);
  });
});
