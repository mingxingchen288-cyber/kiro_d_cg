/**
 * frontend-admin 测试用的后端替代：在 contracts 的 FakeHttp 上按 C09 第 2、7、7a 节和 identity 的 C09 之外接口
 * 保存账号、部门、投递记录、命令审查的状态，这样新建、修改之后重新读取的列表就是用户操作的结果。
 *
 * 数据取自 cmx（`.reports/modules/frontend-admin/01-人员部门角色样例.out.txt`）：部门 175 采购部、581 市场部、
 * 1069 技术中心；人员 241 程苏慧（ADMIN）、343 汪春龙（008 采购）、381 朱文俊、383 韩群（技术中心）。
 * 投递记录和命令审查用 C09 第 7、7a 节的样例格式，编号为说明用的假设值。
 */
import type { CommandReviewList, DeliveryList } from '../../src/contracts/http';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import type { FakeCall } from '../../src/contracts/fakes/http';
import { type Account, type ConfirmOptions, type Department, createAdminDeps } from '../../src/modules/admin/shared';

type Delivery = DeliveryList['rows'][number];
type CommandLog = CommandReviewList['rows'][number];

export const ADMIN_ROLE = { code: 'ADMIN', name: '系统管理员', admin: true };

export const ROLES = [
  { code: 'ADMIN', name: '系统管理员' },
  { code: '技术中心', name: '技术中心' },
  { code: '008', name: '采购' }
];

const account = (userId: string, username: string, displayName: string, departmentId: string, roleCodes: string[]): Account => ({
  userId,
  username,
  displayName,
  departmentId,
  enabled: true,
  roleCodes
});

const query = (call: FakeCall) => call.options?.query ?? {};
const num = (value: unknown, fallback: number) => (value === undefined || value === null ? fallback : Number(value));

export class FakeAdminBackend {
  accounts: Account[] = [
    account('241', 'HY260404', '程苏慧', '581', ['ADMIN']),
    account('343', 'HY090702', '汪春龙', '175', ['008']),
    account('381', 'HY190510', '朱文俊', '1069', ['技术中心']),
    account('383', 'HY221020', '韩群', '1069', ['技术中心'])
  ];

  departments: Department[] = [
    { departmentId: '175', name: '采购部', parentId: null },
    { departmentId: '581', name: '市场部', parentId: null },
    { departmentId: '1069', name: '技术中心', parentId: null }
  ];

  passwords = new Map<string, string>();

  /** 角色配置项；测试中可以加一个，模拟在配置的角色权限里新建了角色 */
  roles = ROLES.map(r => ({ ...r }));

  deliveries: Delivery[] = [
    {
      deliveryId: '3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c',
      recipient: '343',
      status: 'abandoned',
      attempts: 5,
      nextRetryAt: null,
      lastError: '连接被拒绝'
    },
    {
      deliveryId: '7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f',
      recipient: '241',
      status: 'sent',
      attempts: 1,
      nextRetryAt: null,
      lastError: null
    }
  ];

  reviewEnabled = true;
  logs: CommandLog[] = [];

  private nextUser = 400;
  private nextDepartment = 1100;

  constructor(readonly fake: ReturnType<typeof createFakeShell>) {
    const http = fake.http;
    http.on('GET', '/api/admin/accounts', (call: FakeCall) => {
      const q = query(call);
      const word = String(q.keyword ?? '').toLowerCase();
      const role = q.roleCode ? String(q.roleCode) : null;
      const rows = this.accounts.filter(
        a =>
          (!word || a.username.toLowerCase().includes(word) || a.displayName.toLowerCase().includes(word)) &&
          (!role || a.roleCodes.includes(role))
      );
      return structuredClone({ rows: rows.slice(num(q.startRow, 0), num(q.endRow, 50)), total: rows.length });
    });
    http.on('POST', '/api/admin/accounts', (call: FakeCall) => {
      const body = call.body as Account & { password: string };
      this.nextUser += 1;
      const created: Account = {
        userId: String(this.nextUser),
        username: body.username,
        displayName: body.displayName,
        departmentId: body.departmentId,
        enabled: true,
        roleCodes: [...body.roleCodes]
      };
      this.accounts.push(created);
      this.passwords.set(created.userId, body.password);
      return structuredClone(created);
    });
    http.on('PUT', '/api/admin/accounts/:userId', (call: FakeCall) => {
      const body = call.body as Omit<Account, 'userId' | 'username'>;
      const found = this.accounts.find(a => a.userId === call.params.userId)!;
      Object.assign(found, {
        displayName: body.displayName,
        departmentId: body.departmentId,
        enabled: body.enabled,
        roleCodes: [...body.roleCodes]
      });
      return structuredClone(found);
    });
    http.on('POST', '/api/admin/accounts/:userId/password', (call: FakeCall) => {
      this.passwords.set(call.params.userId, (call.body as { password: string }).password);
    });
    http.on('GET', '/api/admin/departments', () => structuredClone({ items: this.departments }));
    http.on('POST', '/api/admin/departments', (call: FakeCall) => {
      const body = call.body as { name: string; parentId: string | null };
      this.nextDepartment += 1;
      const created = { departmentId: String(this.nextDepartment), name: body.name, parentId: body.parentId };
      this.departments.push(created);
      return structuredClone(created);
    });
    http.on('PUT', '/api/admin/departments/:departmentId', (call: FakeCall) => {
      const body = call.body as { name: string; parentId: string | null };
      const found = this.departments.find(d => d.departmentId === call.params.departmentId)!;
      Object.assign(found, body);
      return structuredClone(found);
    });
    http.on('DELETE', '/api/admin/departments/:departmentId', (call: FakeCall) => {
      this.departments = this.departments.filter(d => d.departmentId !== call.params.departmentId);
    });
    http.on('GET', '/api/config/items', (call: FakeCall) => {
      const type = query(call).type;
      const items = this.roles.map(r => ({
        type: 'role',
        key: r.code,
        name: r.name,
        version: 13,
        updatedBy: '1',
        updatedAt: '2026-10-24T10:00:00'
      }));
      return { items: type === 'role' ? items : [] };
    });
    http.on('GET', '/api/admin/deliveries', (call: FakeCall) => {
      const q = query(call);
      const rows = this.deliveries.filter(d => !q.status || d.status === q.status);
      return structuredClone({ rows: rows.slice(num(q.startRow, 0), num(q.endRow, 50)), total: rows.length });
    });
    http.on('POST', '/api/admin/deliveries/:deliveryId/requeue', (call: FakeCall) => {
      const found = this.deliveries.find(d => d.deliveryId === call.params.deliveryId)!;
      Object.assign(found, { status: 'pending', nextRetryAt: '2026-10-29T10:01:00' });
    });
    http.on('GET', '/api/admin/command-review', (call: FakeCall) => {
      const q = query(call);
      const rows = this.logs.filter(l => (!q.user || l.user === q.user) && (!q.result || l.result === q.result));
      return structuredClone({
        enabled: this.reviewEnabled,
        rows: rows.slice(num(q.startRow, 0), num(q.endRow, 50)),
        total: rows.length
      });
    });
    http.on('PUT', '/api/admin/command-review', (call: FakeCall) => {
      this.reviewEnabled = (call.body as { enabled: boolean }).enabled;
      if (!this.reviewEnabled) this.logs = [];
    });
  }
}

/** 管理员（ADMIN 角色）打开管理功能：后端替代、依赖、确认框的记录 */
export function openAdmin() {
  const fake = createFakeShell({
    user: { userId: '241', username: 'HY260404', displayName: '程苏慧', departmentId: '581' },
    role: ADMIN_ROLE
  });
  const backend = new FakeAdminBackend(fake);
  const confirms: ConfirmOptions[] = [];
  const answers = { next: true };
  const deps = createAdminDeps(fake.shell, async options => {
    confirms.push(options);
    return answers.next;
  });
  return { fake, http: fake.http, backend, deps, confirms, answers, messages: fake.messages };
}
