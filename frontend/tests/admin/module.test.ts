/**
 * C11 契约测试（frontend-admin 部分）和 FM-01：用 ShellApi 的模拟实现装载模块，路由 `/admin` 注册成功，
 * install 只依赖 ShellApi；只有管理员角色能使用管理功能。
 */
import { describe, expect, it } from 'vitest';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import {
  ADMIN_SECTIONS,
  adminModule,
  adminSection,
  canUseAdmin,
  isAdminModuleInstalled,
  useAdminShell
} from '../../src/modules/admin';
import { ADMIN_ROLE } from './support';

describe('frontend-admin 模块装载（C11）', () => {
  it('导出 FrontendModule：名称 admin，/admin 显示全部功能，每个功能一条不带参数的路由 /admin/<key>', () => {
    expect(adminModule.name).toBe('admin');
    expect(adminModule.routes.map(r => [r.path, r.name])).toEqual([
      ['/admin', 'admin'],
      ['/admin/accounts', 'admin-accounts'],
      ['/admin/departments', 'admin-departments'],
      ['/admin/role-members', 'admin-role-members'],
      ['/admin/deliveries', 'admin-deliveries'],
      ['/admin/command-review', 'admin-command-review']
    ]);
    expect(adminModule.routes.every(r => typeof r.component === 'function')).toBe(true);
    expect(ADMIN_SECTIONS.map(s => s.title)).toEqual(['人员管理', '部门管理', '角色人员', '投递记录', '命令审查']);
    expect(adminSection('accounts')).toBe('accounts');
    expect(adminSection(undefined)).toBeNull();
  });

  it('install 只接收 ShellApi，之后各功能经它调用接口', () => {
    const { shell } = createFakeShell({ role: ADMIN_ROLE });
    expect(isAdminModuleInstalled()).toBe(false);
    adminModule.install(shell);
    expect(isAdminModuleInstalled()).toBe(true);
    expect(useAdminShell()).toBe(shell);
  });
});

describe('FM-01：只对管理员角色显示', () => {
  it('系统管理员可以使用，成本会计（C09 /api/me 样例的角色）不能', () => {
    const admin = createFakeShell({ role: ADMIN_ROLE });
    const accountant = createFakeShell();
    expect(canUseAdmin(admin.shell.session.role.value)).toBe(true);
    expect(accountant.shell.session.role.value).toEqual({ code: 'COST_ACCOUNTANT', name: '成本会计', admin: false });
    expect(canUseAdmin(accountant.shell.session.role.value)).toBe(false);
    expect(canUseAdmin(null)).toBe(false);
  });
});
