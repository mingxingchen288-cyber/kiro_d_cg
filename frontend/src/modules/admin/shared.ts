/**
 * frontend-admin 共用：依赖（接口、提示、确认框）、C09 之外的接口调用、错误文字、分批读取全部行。
 *
 * C09 之外的接口按 identity 后端路由（`backend/src/cost_platform/identity/router.py`）写，见
 * `.reports/modules/frontend-admin/contract-gaps.md` 第 1、2 条。
 */
import { type PlatformApi, createPlatformApi } from '../../contracts/api';
import { PlatformError } from '../../contracts/errors';
import type { AccountList, DepartmentList } from '../../contracts/http';
import type { HttpClient, ShellApi } from '../../contracts/shell';

export type Account = AccountList['rows'][number];
export type Department = DepartmentList['items'][number];

export interface ConfirmOptions {
  title: string;
  content: string;
  positiveText?: string;
}

/** 确认框：用户点"确定"时为 true。界面用 naive-ui 的对话框实现（renderers/confirm.ts），测试用替代实现 */
export type Confirm = (options: ConfirmOptions) => Promise<boolean>;

/** 部门的新建、修改请求体（C09 之外，identity 的 `DepartmentDraft`） */
export interface DepartmentDraft {
  name: string;
  parentId: string | null;
}

const e = encodeURIComponent;

/** C09 之外、identity 后端已有的管理接口 */
export function createAdminExtraApi(http: HttpClient) {
  return {
    /** 账号列表按角色筛选：`GET /api/admin/accounts?roleCode=`（旧系统角色管理的"人员列表"） */
    accountsOfRole: (roleCode: string, startRow: number, endRow: number) =>
      http.get<AccountList>('/api/admin/accounts', { query: { roleCode, startRow, endRow } }),
    createDepartment: (body: DepartmentDraft) => http.post<Department>('/api/admin/departments', body),
    updateDepartment: (departmentId: string, body: DepartmentDraft) =>
      http.put<Department>(`/api/admin/departments/${e(departmentId)}`, body),
    deleteDepartment: (departmentId: string) => http.delete<void>(`/api/admin/departments/${e(departmentId)}`)
  };
}

export type AdminExtraApi = ReturnType<typeof createAdminExtraApi>;

export interface AdminDeps {
  api: PlatformApi;
  extra: AdminExtraApi;
  message: ShellApi['message'];
  confirm: Confirm;
}

export function createAdminDeps(shell: ShellApi, confirm: Confirm): AdminDeps {
  return {
    api: createPlatformApi(shell.http),
    extra: createAdminExtraApi(shell.http),
    message: shell.message,
    confirm
  };
}

/** 错误提示：后端的提示加上各项明细（C03） */
export function messageOf(error: unknown): string {
  if (error instanceof PlatformError) {
    const lines = error.details.map(d => d.message).filter((m): m is string => Boolean(m) && m !== error.message);
    return [error.message, ...lines].join('；');
  }
  return error instanceof Error ? error.message : String(error);
}

export interface RoleItem {
  code: string;
  name: string;
}

/** 角色列表：角色是 config 的 `role` 配置项（C06 第 8 节），经 `GET /api/config/items?type=role` 读取 */
export async function loadRoles(api: PlatformApi): Promise<RoleItem[]> {
  const list = await api.configItems('role');
  return list.items.filter(item => item.type === 'role').map(item => ({ code: item.key, name: item.name }));
}

/** 分批读取全部行（账号列表没有一次全取的接口）：每批 `size` 行，读满 `total` 或某批不满时结束 */
export async function loadAll<T>(
  fetch: (startRow: number, endRow: number) => Promise<{ rows: T[]; total: number }>,
  size = 500
): Promise<T[]> {
  const rows: T[] = [];
  for (;;) {
    const page = await fetch(rows.length, rows.length + size);
    rows.push(...page.rows);
    if (page.rows.length < size || rows.length >= page.total) return rows;
  }
}
