/**
 * 新建配置项时的预填（FC-02）：C06 第 1.1 节要求必须写出的字段（page 的 `audit`、`detailMode`，operation 的
 * `propagation`，rule 的 `order`，approvalFlow 的 `order`、`operations`，role 的 `admin`，lookup 的 `keywordColumns` 等），
 * 由编辑界面预填，管理员可以修改；保存时总是带上（`withRequired`）。预填值与旧系统新建时的默认值相同：
 * 审计开启、明细多 Tab、操作 continue、规则顺序 10、审批流启用。
 */
import { plain } from './store';
import type { ConfigType, ContentByType, GridOptions } from './types';

export const DEFAULT_GRID: GridOptions = { sideBar: true, cellSelection: true, groupBy: [] };

/** 新建页面时的默认按钮：与后端向导、旧系统相同（主表区新增、删除、保存列配置） */
export const DEFAULT_MASTER_BUTTONS = [
  { action: 'addRow', label: '新增' },
  { action: 'deleteRow', label: '删除' },
  { action: 'saveGridConfig', label: '保存列配置' }
];
export const DEFAULT_DETAIL_BUTTONS = [
  { action: 'addRow', label: '明细新增' },
  { action: 'deleteRow', label: '明细删除' },
  { action: 'saveGridConfig', label: '保存列配置' }
];

export function newContent<T extends ConfigType>(type: T, key: string, name: string): ContentByType[T] {
  const contents: { [K in ConfigType]: () => ContentByType[K] } = {
    entity: () => ({ table: '', primaryKey: '', freezable: true, fields: [] }),
    page: () => ({
      title: name,
      layout: 'single',
      detailMode: 'tabs',
      audit: true,
      saveOperation: `${key}.save`,
      master: { entity: '', buttons: structuredClone(DEFAULT_MASTER_BUTTONS), grid: structuredClone(DEFAULT_GRID) }
    }),
    operation: () => ({ label: name, kind: 'action', actions: [], rowNotFound: 'skip', propagation: 'continue' }),
    rule: () => ({ layer: 'entity', target: '', category: 'calc', field: null, order: 10 }),
    approvalFlow: () => ({
      page: '',
      order: 1,
      enabled: true,
      operations: {},
      levels: [],
      freeze: [],
      display: [],
      propagation: 'end',
      notify: []
    }),
    role: () => ({ name, admin: false, pages: {} }),
    menu: () => ({ items: [] }),
    dict: () => ({ items: [] }),
    lookup: () => ({ table: '', columns: [], keywordColumns: [] }),
    export: () => ({
      page: '',
      name,
      fileName: name,
      font: 'Calibri',
      detailLayout: 'perMaster',
      master: { sheet: name, sql: '', keyColumn: '', columns: [] },
      details: []
    })
  };
  return contents[type]() as ContentByType[T];
}

/** 保存前补齐必须写出的字段：已有值不变，没有值时写预填值（管理员没有改动时就是预填值） */
export function withRequired<T extends ConfigType>(type: T, content: ContentByType[T]): ContentByType[T] {
  const c = plain(content) as unknown as ContentByType[ConfigType];
  switch (type) {
    case 'page': {
      const page = c as ContentByType['page'];
      page.audit ??= true;
      page.detailMode ??= 'tabs';
      break;
    }
    case 'operation':
      (c as ContentByType['operation']).propagation ??= 'continue';
      break;
    case 'rule':
      (c as ContentByType['rule']).order ??= 10;
      break;
    case 'approvalFlow': {
      const flow = c as ContentByType['approvalFlow'];
      flow.order ??= 1;
      flow.operations ??= {};
      for (const param of flow.params ?? []) param.required ??= false;
      break;
    }
    case 'role':
      (c as ContentByType['role']).admin ??= false;
      break;
    case 'dict':
      (c as ContentByType['dict']).items.forEach((item, i) => (item.order ??= i + 1));
      break;
    case 'lookup':
      (c as ContentByType['lookup']).keywordColumns ??= [];
      break;
    default:
      break;
  }
  return c as unknown as ContentByType[T];
}
