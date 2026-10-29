/**
 * 页面目录：一个页面的表格（主表实体和明细实体）、字段，以及审批流、权限配置要选的角色、部门、人员。
 * 全部从真实接口读：页面和实体经 `GET /api/config/items/{type}/{key}`，角色经配置项列表，部门和人员经
 * `/api/admin/departments`、`/api/admin/accounts`（C09 第 2、3 节）。
 */
import type { PlatformApi } from '../../../contracts/api';
import type { ConfigStore } from './store';
import type { EntityContent, EntityField, PageContent } from './types';

export interface PageTable {
  /** 实体编码 */
  entity: string;
  /** 页面中的表格标题：主表取页面标题，明细取 `details[].title` */
  title: string;
  isMaster: boolean;
  table: string;
  readView: string | null;
  primaryKey: string;
  fields: EntityField[];
  content: EntityContent | null;
}

export interface PageCatalog {
  pageCode: string;
  page: PageContent;
  tables: PageTable[];
}

export async function loadPageCatalog(store: ConfigStore, pageCode: string): Promise<PageCatalog> {
  const page = (await store.load('page', pageCode)).content;
  const areas = [
    { entity: page.master.entity, title: page.title, isMaster: true },
    ...(page.details ?? []).map(d => ({ entity: d.entity, title: d.title, isMaster: false }))
  ];
  const tables = await Promise.all(
    areas.map(async area => {
      const entity = area.entity ? await store.tryLoad('entity', area.entity) : null;
      const content = entity?.content ?? null;
      return {
        ...area,
        table: content?.table ?? '',
        readView: content?.readView ?? null,
        primaryKey: content?.primaryKey ?? '',
        fields: content?.fields ?? [],
        content
      } satisfies PageTable;
    })
  );
  return { pageCode, page, tables };
}

export function tableTitle(catalog: PageCatalog | null, entity: string) {
  return catalog?.tables.find(t => t.entity === entity)?.title ?? entity;
}

export type Option = {
  label: string;
  value: string;
};

export interface Directory {
  roles: Option[];
  departments: Option[];
  users: Option[];
}

/** 角色、部门、人员；某一项读取失败时为空，并在 `errors` 中给出原因 */
export async function loadDirectory(api: PlatformApi, store: ConfigStore): Promise<Directory & { errors: string[] }> {
  const errors: string[] = [];
  const [roles, departments, users] = await Promise.all([
    store.list('role').then(
      items => items.map(r => ({ label: `${r.name} (${r.key})`, value: r.key })),
      (e: Error) => (errors.push(`角色读取失败：${e.message}`), [] as Option[])
    ),
    api.departments().then(
      d => d.items.map(x => ({ label: `${x.name} (${x.departmentId})`, value: x.departmentId })),
      (e: Error) => (errors.push(`部门读取失败：${e.message}`), [] as Option[])
    ),
    loadAllAccounts(api).then(
      rows => rows.map(x => ({ label: `${x.displayName} (${x.userId})`, value: x.userId })),
      (e: Error) => (errors.push(`人员读取失败：${e.message}`), [] as Option[])
    )
  ]);
  return { roles, departments, users, errors };
}

/** 账号列表按页读完（每页 500 个，直到 `total`） */
async function loadAllAccounts(api: PlatformApi) {
  const rows: Array<{ userId: string; displayName: string }> = [];
  for (;;) {
    const page = await api.listAccounts({ startRow: rows.length, endRow: rows.length + 500 });
    rows.push(...page.rows);
    if (page.rows.length === 0 || rows.length >= page.total) return rows;
  }
}
