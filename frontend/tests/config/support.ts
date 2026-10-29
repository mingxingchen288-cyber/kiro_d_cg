/**
 * frontend-config 测试用的后端替代实现：在 contracts 的 FakeHttp 上挂一份内存中的配置项，
 * 列表、读取、保存（版本加一）、删除、校验都按 C09 第 3 节的接口走。
 *
 * 页面和实体按成本核算（COST_PINGGU：主表成本单，明细原辅料 COST_MATERIAL、包材 COST_PACKAGE）和
 * 物料清单及成本（GOODS_PRICE_MANAGE：单表 COST_GOODS_PRICE）的真实字段取一部分，审批流样例取 C06 7.8～7.10。
 * `useSeed` 把成本核算换成 `backend/seed/config/` 中的完整配置（表与列的用例用）。
 */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createPlatformApi } from '../../src/contracts/api';
import { type ErrorDetail, PlatformError } from '../../src/contracts/errors';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import { ConfigStore } from '../../src/modules/config/core/store';
import type { EntityField } from '../../src/modules/config/core/types';

export interface StoredItem {
  type: string;
  key: string;
  name: string;
  version: number;
  content: Record<string, unknown>;
}

const field = (name: string, label: string, type: EntityField['type'] = 'text', extra: Partial<EntityField> = {}): EntityField => ({
  name,
  column: name,
  label,
  type,
  source: 'own',
  role: 'input',
  ...extra
});

export const COST_ENTITIES: Record<string, Record<string, unknown>> = {
  COST_PINGGU: {
    table: 'T_COST_PINGGU',
    primaryKey: 'DOCID',
    freezable: true,
    fields: [
      field('DOCID', '单据号', 'number', { role: 'system' }),
      field('GOODSNAME', '产品', 'text', { source: 'erp' }),
      field('USESTATUS', '状态'),
      field('COST_PERBOX', '每盒成本', 'number', { role: 'calculated' }),
      field('JGF_PERQP', '千片加工费', 'number', { role: 'calculated' }),
      field('APEX_PL', '批量', 'number'),
      field('P_PERPACK', '每盒片数', 'number')
    ],
    details: [
      { entity: 'COST_MATERIAL', parentKey: 'DOCID' },
      { entity: 'COST_PACKAGE', parentKey: 'DOCID' }
    ]
  },
  COST_MATERIAL: {
    table: 'T_COST_PINGGU_DTL',
    primaryKey: 'DTLID',
    freezable: true,
    readView: 'V_COST_PINGGU_MATERIAL',
    fields: [
      field('DTLID', '明细号', 'number', { role: 'system' }),
      field('DOCID', '单据号', 'number', { role: 'system' }),
      field('GOODSID', '物料', 'number'),
      field('GOODSNAME', '物料名称'),
      field('PRICE', '单价', 'number'),
      field('COST_BATCH', '金额', 'number', { role: 'calculated' }),
      field('CUSTOMER_SPECIFIED', '客户指定', 'number')
    ]
  },
  COST_PACKAGE: {
    table: 'T_COST_PINGGU_DTL',
    primaryKey: 'DTLID',
    freezable: true,
    readView: 'V_COST_PINGGU_PACKAGE',
    fields: [
      field('DTLID', '明细号', 'number', { role: 'system' }),
      field('DOCID', '单据号', 'number', { role: 'system' }),
      field('GOODSID', '物料', 'number'),
      field('GOODSNAME', '物料名称'),
      field('PRICE', '单价', 'number'),
      field('COST_BATCH', '金额', 'number', { role: 'calculated' }),
      field('CUSTOMER_SPECIFIED', '客户指定', 'number'),
      field('BATCH_QTY', '批量', 'number', { role: 'calculated' }),
      field('PER_HL', '每盒含量', 'number'),
      field('EXADD_MATER', '损耗率', 'number')
    ]
  },
  COST_GOODS_PRICE: {
    table: 'T_COST_GOODS',
    primaryKey: 'GOODSID',
    freezable: true,
    readView: 'T_COST_GOODS_PRICE_V',
    erpRow: { column: 'ISERP', value: '1', localValue: '0' },
    fields: [
      field('GOODSID', '物料ID', 'number', { role: 'system' }),
      field('GOODSNAME', '物料名称', 'text', { source: 'erp' }),
      field('PRICE', '参考价格', 'number', { source: 'erp' }),
      field('ZX_PRICE', '单价', 'number'),
      field('ISERP', 'ERP 物料')
    ]
  }
};

const grid = { sideBar: true, cellSelection: true, groupBy: [] };

export const PAGES: Record<string, Record<string, unknown>> = {
  COST_PINGGU: {
    title: '成本核算',
    layout: 'masterDetail',
    detailMode: 'tabs',
    audit: true,
    saveOperation: 'COST_PINGGU.save',
    master: {
      entity: 'COST_PINGGU',
      buttons: [
        { action: 'addRow', label: '新增' },
        { action: 'copyRow', label: '复制' },
        { action: 'syncPrice', label: '同步价格', operation: 'COST_PINGGU.syncPrice', requiresSelection: true }
      ],
      grid,
      formLayout: []
    },
    details: [
      { entity: 'COST_MATERIAL', title: '原辅料', buttons: [{ action: 'addRow', label: '新增' }], grid, formLayout: [] },
      { entity: 'COST_PACKAGE', title: '包材', buttons: [{ action: 'addRow', label: '新增' }], grid, formLayout: [] }
    ]
  },
  GOODS_PRICE_MANAGE: {
    title: '物料清单及成本',
    layout: 'single',
    detailMode: 'tabs',
    audit: true,
    saveOperation: 'GOODS_PRICE_MANAGE.save',
    master: { entity: 'COST_GOODS_PRICE', buttons: [], grid, formLayout: [] }
  }
};

export function createBackend() {
  const fake = createFakeShell({
    user: { userId: '1', username: 'admin', displayName: '系统管理员', departmentId: '10' },
    role: { code: 'ADMIN', name: '系统管理员', admin: true }
  });
  const items = new Map<string, StoredItem>();
  const id = (type: string, key: string) => `${type}/${key}`;
  const put = (type: string, key: string, name: string, content: Record<string, unknown>, version = 1) =>
    items.set(id(type, key), { type, key, name, version, content: structuredClone(content) });

  for (const [key, content] of Object.entries(COST_ENTITIES)) put('entity', key, key, content);
  for (const [key, content] of Object.entries(PAGES)) put('page', key, String(content.title), content);
  put('role', 'ADMIN', '系统管理员', { name: '系统管理员', admin: true, pages: {} });
  put('role', '007', '生产', { name: '生产', admin: false, pages: {} });
  put('role', '008', '采购', { name: '采购', admin: false, pages: {} });
  put('menu', 'MAIN', '主菜单', {
    items: [{ key: 'cost', title: '成本', kind: 'group', children: [{ key: 'COST_PINGGU', title: '成本核算', kind: 'page', pageCode: 'COST_PINGGU' }] }]
  });

  /** 校验接口下一次返回的错误；为空时校验通过 */
  let validateErrors: ErrorDetail[] = [];
  const http = fake.http;
  http.on('GET', '/api/config/items', (call: { options?: { query?: Record<string, unknown> } }) => {
    const type = call.options?.query?.type;
    return {
      items: [...items.values()]
        .filter(i => !type || i.type === type)
        .map(({ content: _content, ...rest }) => ({ ...rest, updatedBy: '1', updatedAt: '2026-10-29T10:00:00' }))
    };
  });
  http.on('GET', '/api/config/items/:type/:key', (call: { params: Record<string, string> }) => {
    const item = items.get(id(call.params.type, call.params.key));
    if (!item) throw new PlatformError(404, 'NOT_FOUND', '配置项不存在');
    return { ...structuredClone(item), updatedBy: '1', updatedAt: '2026-10-29T10:00:00' };
  });
  http.on('PUT', '/api/config/items/:type/:key', (call: { params: Record<string, string>; body: unknown }) => {
    const { type, key } = call.params;
    const body = call.body as { name: string; content: Record<string, unknown> };
    const version = (items.get(id(type, key))?.version ?? 0) + 1;
    put(type, key, body.name, body.content, version);
    return { type, key, version };
  });
  http.on('DELETE', '/api/config/items/:type/:key', (call: { params: Record<string, string> }) => {
    items.delete(id(call.params.type, call.params.key));
  });
  http.on('POST', '/api/config/validate', () => {
    const errors = validateErrors;
    validateErrors = [];
    return { ok: errors.length === 0, errors };
  });
  http.on('GET', '/api/admin/departments', { items: [{ departmentId: '1069', name: '技术中心', parentId: null }] });
  http.on('GET', '/api/admin/accounts', { rows: [], total: 0 });

  const api = createPlatformApi(http);
  const store = new ConfigStore(api);
  return {
    fake,
    http,
    api,
    store,
    items,
    get: (type: string, key: string) => items.get(id(type, key)),
    failNextValidate(errors: ErrorDetail[]) {
      validateErrors = errors;
    }
  };
}

const SEED = fileURLToPath(new URL('../../../backend/seed/config/', import.meta.url));

/** `backend/seed/config/` 中的实体、页面、操作和 Lookup（链路 0 手写的成本核算配置），按文件读出，版本为 1 */
export function seedItems(): StoredItem[] {
  return readdirSync(SEED)
    .filter(file => /^(entity|page|operation|lookup)\..+\.json$/.test(file))
    .map(file => {
      const item = JSON.parse(readFileSync(`${SEED}${file}`, 'utf-8')) as Omit<StoredItem, 'version'>;
      return { type: item.type, key: item.key, name: item.name, version: 1, content: item.content };
    });
}

/** 模拟后端中的成本核算换成 seed 的配置 */
export function useSeed(backend: ReturnType<typeof createBackend>) {
  for (const item of seedItems()) backend.items.set(`${item.type}/${item.key}`, structuredClone(item));
}

export const detail = (path: string, message: string, configType = 'approvalFlow', configKey: string | null = null): ErrorDetail => ({
  message,
  entity: null,
  rowKey: null,
  clientRowId: null,
  field: null,
  approvalId: null,
  configType,
  configKey,
  path
});

export const notifier = () => {
  const messages: Array<{ kind: 'success' | 'error'; text: string }> = [];
  return {
    messages,
    success: (text: string) => messages.push({ kind: 'success', text }),
    error: (text: string) => messages.push({ kind: 'error', text })
  };
};
