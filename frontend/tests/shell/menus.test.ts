/**
 * 菜单（C09 `/api/me` 的 menus，C11 的表）：page 项打开 /page/<pageCode>，config、admin 项打开对应模块的页面，
 * 外壳的固定入口"待办"打开 /approval；按当前路径找到高亮的菜单。
 */
import type { RouteRecordRaw } from 'vue-router';
import { describe, expect, it } from 'vitest';
import { meResponseSample } from '../../src/contracts/fakes/samples';
import type { MenuItem } from '../../src/contracts/http';
import type { FrontendModule } from '../../src/contracts/shell';
import { buildMenus, menuOfKey, menuOfPath, todoMenu } from '../../src/modules/shell/menus';

const View = { render: () => null };

function module(name: FrontendModule['name'], routes: RouteRecordRaw[]): Pick<FrontendModule, 'name' | 'routes'> {
  return { name, routes };
}

const page = module('page', [{ path: '/page/:pageCode', name: 'page', component: View, props: true }]);
const config = module('config', [{ path: '/config', name: 'config-home', component: View }]);
const admin = module('admin', [
  { path: '/admin/accounts', name: 'accounts', component: View },
  { path: '/admin/deliveries', name: 'admin-deliveries', component: View }
]);
const approval = module('approval', [
  { path: '/approval', name: 'approval-todo', component: View },
  { path: '/approval/:approvalId', name: 'approval-detail', component: View, props: true }
]);

/** 管理员的菜单（假设）：业务页面之外有配置和管理 */
const adminMenus: MenuItem[] = [
  ...meResponseSample.menus,
  {
    key: 'system',
    title: '系统管理',
    kind: 'group',
    children: [
      { key: 'config', title: '页面配置', kind: 'config' },
      { key: 'accounts', title: '人员管理', kind: 'admin' },
      { key: 'deliveries', title: '通知投递', kind: 'admin' }
    ]
  }
];

describe('菜单', () => {
  it('成本会计的菜单：分组"成本"下的"成本核算"打开 /page/COST_PINGGU', () => {
    expect(buildMenus(meResponseSample.menus, [page])).toEqual([
      {
        key: 'cost',
        title: '成本',
        path: null,
        children: [{ key: 'COST_PINGGU', title: '成本核算', path: '/page/COST_PINGGU' }]
      }
    ]);
  });

  it('管理员的配置、管理菜单打开对应模块的页面：按路由名称、按 /<kind>/<key>、否则 /<kind>', () => {
    const menus = buildMenus(adminMenus, [page, config, admin]);
    const system = menus.find(menu => menu.key === 'system')!;

    expect(system.children).toEqual([
      { key: 'config', title: '页面配置', path: '/config' },
      { key: 'accounts', title: '人员管理', path: '/admin/accounts' },
      { key: 'deliveries', title: '通知投递', path: '/admin/deliveries' }
    ]);
    expect(menuOfKey(menus, 'accounts')?.path).toBe('/admin/accounts');
  });

  it('模块还没有注册时，它的菜单项不显示，分组空了也不显示', () => {
    const menus = buildMenus(adminMenus, [page]);

    expect(menus.map(menu => menu.key)).toEqual(['cost']);
  });

  it('frontend-approval 注册后出现固定入口"待办"；打开审批详情 /approval/203 时高亮"待办"', () => {
    const todo = todoMenu([page, approval]);
    expect(todo).toMatchObject({ title: '待办', path: '/approval' });
    expect(todoMenu([page])).toBeNull();

    const menus = [todo!, ...buildMenus(meResponseSample.menus, [page, approval])];
    expect(menuOfPath(menus, '/page/COST_PINGGU')?.title).toBe('成本核算');
    expect(menuOfPath(menus, '/approval/203')?.title).toBe('待办');
    expect(menuOfPath(menus, '/approval')?.title).toBe('待办');
  });
});
