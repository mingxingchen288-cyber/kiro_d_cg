/**
 * 页面运行时测试用的页面视图、数据和表格替代实现（GridPort）。
 *
 * 页面视图按 C05 的写法，内容取自成本核算页：成本单 2550、2551（250mg乙酰唑胺片），原辅料明细中的聚维酮K30（物料 25）、
 * 硬脂酸镁（115）、玉米淀粉（116）；审批 203 为 C09 第 6 节的样例。
 */
import type { DataRow, PersonalColumn, RecordResponse } from '../../src/contracts/http';
import type { PageView, ViewField } from '../../src/contracts/page-view';
import { createPlatformApi } from '../../src/contracts/api';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import { type GridPort, PageRuntime } from '../../src/modules/page/page-runtime';

export const MASTER = 'COST_PINGGU';
export const MATERIAL = 'COST_MATERIAL';

const field = (name: string, label: string, extra: Partial<ViewField> = {}): ViewField => ({
  name,
  label,
  type: 'text',
  scale: null,
  source: 'own',
  calculated: false,
  visible: true,
  editable: true,
  required: false,
  width: 120,
  pinned: null,
  dictType: null,
  lookup: null,
  ...extra
});

export function costView(): PageView {
  return {
    pageCode: MASTER,
    title: '成本核算',
    version: 13,
    layout: 'masterDetail',
    detailMode: 'tabs',
    audit: true,
    saveOperation: 'COST_PINGGU.save',
    rulesPack: { packId: MASTER, version: 7 },
    master: {
      entity: MASTER,
      primaryKey: 'DOCID',
      fields: [
        field('DOCID', '单据号', { type: 'number', scale: 0, editable: false, pinned: 'left' }),
        field('GOODSNAME', '产品名称', { source: 'erp', editable: false, width: 200 }),
        field('MEMO', '备注'),
        field('QTY', '数量', { type: 'number', scale: 2 }),
        field('TOTAL_COST', '总成本', { type: 'number', scale: 2, calculated: true, editable: false }),
        field('CREATE_BY', '创建人', { editable: false, default: { type: 'builtin', value: 'currentUserName' } }),
        field('STATUS', '状态', { default: { type: 'options', value: ['草稿', '评估中'] } }),
        field('FORM', '剂型', { visible: false, editable: false })
      ],
      buttons: [
        { key: 'master:addRow', action: 'addRow', label: '新增', operation: null, requiresSelection: false },
        { key: 'master:copyRow', action: 'copyRow', label: '复制', operation: null, requiresSelection: true },
        { key: 'master:deleteRow', action: 'deleteRow', label: '删除', operation: null, requiresSelection: true },
        {
          key: 'master:syncPrice',
          action: 'syncPrice',
          label: '同步价格',
          operation: 'COST_PINGGU.syncPrice',
          requiresSelection: true
        },
        {
          key: 'master:saveGridConfig',
          action: 'saveGridConfig',
          label: '保存列配置',
          operation: null,
          requiresSelection: false
        }
      ],
      grid: { sideBar: true, cellSelection: true, groupBy: [] },
      formLayout: [{ field: 'MEMO', x: 0, y: 0, w: 12, h: 1 }]
    },
    details: [
      {
        entity: MATERIAL,
        title: '原料/辅料',
        primaryKey: 'DTLID',
        parentKey: 'DOCID',
        fields: [
          field('DTLID', '明细号', { type: 'number', scale: 0, editable: false }),
          field('DOCID', '单据号', { type: 'number', scale: 0, editable: false, visible: false }),
          field('GOODSID', '物料', {
            type: 'number',
            scale: 0,
            lookup: { code: 'GOODS', fill: { GOODSID: 'GOODSID', GOODSNAME: 'NAME', PRICE: 'ZX_PRICE' } }
          }),
          field('GOODSNAME', '物料名称', { editable: false }),
          field('PRICE', '单价', { type: 'number', scale: 4, compare: { format: 'both' } }),
          field('USAGE', '用量', { type: 'number', scale: 4 }),
          field('AMOUNT', '金额', { type: 'number', scale: 2, calculated: true, editable: false }),
          field('MEMO', '备注')
        ],
        buttons: [
          { key: 'COST_MATERIAL:addRow', action: 'addRow', label: '新增', operation: null, requiresSelection: false },
          { key: 'COST_MATERIAL:copyRow', action: 'copyRow', label: '复制', operation: null, requiresSelection: true },
          {
            key: 'COST_MATERIAL:deleteRow',
            action: 'deleteRow',
            label: '删除',
            operation: null,
            requiresSelection: true
          }
        ],
        grid: { sideBar: true, cellSelection: true, groupBy: [] },
        formLayout: []
      }
    ],
    systemButtons: ['save', 'addRow', 'deleteRow', 'advancedSearch']
  };
}

export const masterRow = (docid: string, memo: string | null, frozen: string | null = null): DataRow => ({
  rowKey: docid,
  values: {
    DOCID: docid,
    GOODSNAME: '250mg乙酰唑胺片',
    MEMO: memo,
    QTY: '10',
    TOTAL_COST: '13.0065',
    CREATE_BY: '杨娜',
    STATUS: '评估中',
    FORM: '片剂'
  },
  frozen: frozen ? { approvalId: frozen } : null
});

export const materialRow = (dtlid: string, docid: string, goodsid: string, name: string, price: string): DataRow => ({
  rowKey: dtlid,
  values: {
    DTLID: dtlid,
    DOCID: docid,
    GOODSID: goodsid,
    GOODSNAME: name,
    PRICE: price,
    USAGE: '10',
    AMOUNT: String(Number(price) * 10),
    MEMO: null
  },
  frozen: null
});

export const RECORDS: Record<string, RecordResponse> = {
  '2550': {
    master: masterRow('2550', null),
    details: {
      [MATERIAL]: [
        materialRow('206323', '2550', '25', '聚维酮K30', '75'),
        materialRow('206324', '2550', '115', '硬脂酸镁', '70'),
        materialRow('206325', '2550', '116', '玉米淀粉', '38')
      ]
    }
  },
  '2551': {
    master: masterRow('2551', '原备注'),
    details: { [MATERIAL]: [materialRow('206400', '2551', '25', '聚维酮K30', '75')] }
  }
};

/** 表格的替代实现：记录行和调用 */
export class FakeGrid implements GridPort {
  ids: string[] = [];
  selected: string[] = [];
  readonly updated: string[][] = [];
  refreshed = 0;
  reloads: boolean[] = [];
  applied: PersonalColumn[] | null = null;
  state: PersonalColumn[] = [];

  updateRows(ids: string[]) {
    this.updated.push(ids);
  }
  insertRows(rows: Array<{ id: string; after: string | null }>) {
    for (const row of rows) {
      const index = row.after === null ? -1 : this.ids.indexOf(row.after);
      this.ids.splice(index + 1, 0, row.id);
    }
  }
  removeRows(ids: string[]) {
    this.ids = this.ids.filter(id => !ids.includes(id));
  }
  hasRow(id: string) {
    return this.ids.includes(id);
  }
  setRows(ids: string[]) {
    this.ids = [...ids];
  }
  reload(purge = false) {
    this.reloads.push(purge);
  }
  selectedIds() {
    return [...this.selected];
  }
  select(id: string) {
    this.selected = [id];
  }
  refreshAll() {
    this.refreshed += 1;
  }
  columnState() {
    return this.state;
  }
  applyColumnState(columns: PersonalColumn[]) {
    this.applied = columns;
  }
  stopEditing() {}
  neighbor(id: string, offset: -1 | 1) {
    return this.ids[this.ids.indexOf(id) + offset] ?? null;
  }
  /** 所有 updateRows 调用中出现过的行 */
  get updatedIds() {
    return this.updated.flat();
  }
}

/** 打开成本核算页：主表第一页是 2550、2551，单据加载按 RECORDS */
export async function openCostPage(view: PageView = costView(), setup?: (fake: ReturnType<typeof createFakeShell>) => void) {
  const fake = createFakeShell({
    user: { userId: '1', username: 'zhangsan', displayName: '张三', departmentId: '10' },
    role: { code: 'COST_ACCOUNTANT', name: '成本会计', admin: false }
  });
  setup?.(fake);
  fake.http.on('GET', '/api/pages/:pageCode/view', view);
  fake.http.on('GET', '/api/pages/:pageCode/personal', {});
  fake.http.on('POST', '/api/pages/:pageCode/rows', {
    rows: [RECORDS['2550'].master, RECORDS['2551'].master],
    total: 2,
    aggregates: {}
  });
  fake.http.on('GET', '/api/pages/:pageCode/records/:recordKey', (call: { params: Record<string, string> }) =>
    structuredClone(RECORDS[call.params.recordKey])
  );
  const runtime = new PageRuntime(MASTER, {
    api: createPlatformApi(fake.http),
    calc: fake.calc,
    realtime: fake.realtime,
    session: fake.shell.session,
    message: fake.shell.message,
    tabs: fake.shell.tabs,
    path: `/page/${MASTER}`,
    previewDelay: 0,
    now: () => new Date(2026, 9, 29, 9, 30, 0)
  });
  await runtime.load();
  const master = new FakeGrid();
  const material = new FakeGrid();
  runtime.attach(MASTER, master);
  runtime.attach(MATERIAL, material);
  const first = await runtime.fetchMasterRows({ startRow: 0, endRow: 100 });
  master.setRows(first.rows.map(r => r.__id));
  return { runtime, fake, master, material };
}

/** 选中主表的一行并等明细加载 */
export async function selectRecord(ctx: Awaited<ReturnType<typeof openCostPage>>, recordId: string) {
  ctx.master.select(recordId);
  ctx.runtime.onSelection(MASTER, [recordId]);
  await ctx.runtime.activate(recordId);
}
