/**
 * 第 7 批页面显示（模拟验证，contracts 的 C09 模拟实现和 FakeGrid）：
 * - 千分位（C05 v6 `grouping`，同旧系统 useMetaColumns.ts 的 applyThousandsGrouping）：表格、汇总行加千分位，编辑和保存用原值；
 *   从表格复制出来的带千分位的数值能粘贴回数值列。
 * - Lookup 对话框的列（C05 v6 `lookup.columns`，同旧系统 LookupDialog.vue）：表头为配置的标题，配了宽度的列固定宽度。
 * - 成本核算主表"分类"（C05 v6 `dictFreeText`，同旧系统 TagSelectCellEditor.vue"下拉（可填写）"）：字典下拉、可以填写，存单个文本。
 */
import { describe, expect, it } from 'vitest';
import type { ColDef } from 'ag-grid-community';
import type { PageView, ViewField } from '../../src/contracts/page-view';
import { displayText, formatNumber, groupThousands, parseInput } from '../../src/modules/page/fields';
import { DICT_FREE_TEXT_EDITOR, buildColumns } from '../../src/modules/page/grid-adapter/columns';
import { lookupColumnDefs } from '../../src/modules/page/grid-adapter/lookup-columns';
import { MASTER, MATERIAL, costView, masterRow, openCostPage, selectRecord } from './support';

const format = (column: ColDef, value: string | null) => (column.valueFormatter as (p: unknown) => string)({ value });
const setValue = (column: ColDef, data: Record<string, unknown>, newValue: unknown) =>
  (column.valueSetter as (p: unknown) => boolean)({ data, newValue });

/** 成本核算主表：数量（成本单 2555 的批量 3500000 这类整数）、总成本带千分位并求和；"状态"按字典 pingguClass 可填写 */
function displayView(): PageView {
  const view = costView();
  for (const f of view.master.fields) {
    if (f.name === 'QTY') Object.assign(f, { scale: null, grouping: true, aggregate: 'sum' });
    if (f.name === 'TOTAL_COST') Object.assign(f, { grouping: true, aggregate: 'sum' });
    if (f.name === 'MEMO') Object.assign(f, { dictType: 'pingguClass', dictFreeText: true });
  }
  return view;
}

const CLASSES = ['委托研发', '委托转移', '自主立项', '平台业务'];

describe('千分位（C05 grouping）', () => {
  it('整数部分每三位加逗号，按小数位取舍之后再加；负数、小于一千的数不变形', () => {
    const batch = { scale: null, grouping: true };
    expect(formatNumber(batch, '3500000')).toBe('3,500,000');
    expect(formatNumber({ scale: 2, grouping: true }, '1234567.891')).toBe('1,234,567.89');
    expect(formatNumber({ scale: 2, grouping: true }, '-1234.5')).toBe('-1,234.50');
    expect(formatNumber({ scale: 4, grouping: true }, '999.12345')).toBe('999.1235');
    expect(formatNumber({ scale: null, grouping: false }, '3500000')).toBe('3500000');
    expect(groupThousands('不是数')).toBe('不是数');
  });

  it('成本单 2555 的批量 3500000：表格显示 3,500,000；编辑框给出的值、粘贴的 3,500,000 都按 3500000 写入', async () => {
    const ctx = await openCostPage(displayView());
    const { runtime } = ctx;
    const columns = buildColumns(runtime, runtime.view.value!.master);
    const qty = columns.find(c => c.colId === 'QTY')!;
    expect(format(qty, '3500000')).toBe('3,500,000');
    // 数值列用 AG Grid 默认的编辑框，取单元格原值（不经 valueFormatter），这里只配了显示格式
    expect(qty.cellEditor).toBeUndefined();

    const field = runtime.view.value!.master.fields.find(f => f.name === 'QTY')!;
    expect(parseInput(field, '3,500,000')).toBe('3500000');
    expect(parseInput(field, '3500000')).toBe('3500000');
    const data = { ...runtime.gridRow(MASTER, '2550') };
    expect(setValue(qty, data, '3,600,000')).toBe(true);
    expect(runtime.model.buffer.documents()[0].master).toEqual({
      op: 'modify',
      rowKey: '2550',
      changes: { QTY: '3600000' }
    });
  });

  it('汇总行同这一列显示千分位：数量 3,510,000、总成本 1,234,567.89', async () => {
    const ctx = await openCostPage(displayView());
    const { runtime, fake } = ctx;
    fake.http.on('POST', '/api/pages/:pageCode/rows', {
      rows: [masterRow('2550', null)],
      total: 2,
      aggregates: { QTY: '3510000', TOTAL_COST: '1234567.891' }
    });
    await runtime.fetchMasterRows({ startRow: 0, endRow: 100 });
    const row = runtime.summaryRow(MASTER)!;
    const columns = buildColumns(runtime, runtime.view.value!.master);
    expect(format(columns.find(c => c.colId === 'QTY')!, row.QTY as string)).toBe('3,510,000');
    expect(format(columns.find(c => c.colId === 'TOTAL_COST')!, row.TOTAL_COST as string)).toBe('1,234,567.89');
  });
});

describe('Lookup 对话框的列标题和宽度（C05 lookup.columns）', () => {
  it('打开物料 Lookup：对话框的列按配置的顺序，表头是中文标题，配了宽度的列固定宽度，没配的平分', async () => {
    const view = costView();
    const goods = view.details[0].fields.find(f => f.name === 'GOODSID')!;
    goods.lookup = {
      ...goods.lookup!,
      columns: [
        { column: 'GOODSID', label: '物料ID' },
        { column: 'NAME', label: '物料名称', width: 200 },
        { column: 'ZX_PRICE', label: '单价', width: 100 }
      ]
    };
    const ctx = await openCostPage(view);
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    fake.http.on('POST', '/api/lookups/:lookupCode/search', {
      rows: [{ values: { GOODSID: '13165', NAME: '微晶纤维素', ZX_PRICE: '40' } }],
      total: 1,
      keywordSearch: true
    });
    await runtime.openLookup(MATERIAL, '206325', 'GOODSID');
    const lookup = runtime.ui.lookup.value!;
    const defs = lookupColumnDefs(lookup.columns, lookup.rows);
    expect(defs.map(d => [d.field, d.headerName, d.width ?? null, d.flex ?? null])).toEqual([
      ['GOODSID', '物料ID', null, 1],
      ['NAME', '物料名称', 200, null],
      ['ZX_PRICE', '单价', 100, null]
    ]);
  });

  it('页面视图没带显示列时按返回的列名作表头', () => {
    const defs = lookupColumnDefs([], [{ GOODSID: '13165', NAME: '微晶纤维素' }]);
    expect(defs.map(d => [d.field, d.headerName])).toEqual([
      ['GOODSID', 'GOODSID'],
      ['NAME', 'NAME']
    ]);
  });
});

describe('字典下拉可填写（C05 dictFreeText，成本核算主表"分类"）', () => {
  async function openClassPage() {
    return openCostPage(displayView(), fake =>
      fake.http.on('GET', '/api/dicts/:dictType', { items: CLASSES.map(v => ({ value: v, label: v })) })
    );
  }

  it('用可填写的字典下拉编辑器，选项为字典的四项；选"委托研发"后命令写这个文本', async () => {
    const ctx = await openClassPage();
    const { runtime } = ctx;
    const columns = buildColumns(runtime, runtime.view.value!.master);
    const memo = columns.find(c => c.colId === 'MEMO')!;
    expect(memo.cellEditor).toBe(DICT_FREE_TEXT_EDITOR);
    expect(memo.cellEditorPopup).toBe(true);
    expect(memo.cellEditorParams).toEqual({ options: CLASSES.map(v => ({ value: v, label: v })) });

    expect(setValue(memo, { ...runtime.gridRow(MASTER, '2550') }, '委托研发')).toBe(true);
    expect(runtime.model.buffer.documents()[0].master).toEqual({
      op: 'modify',
      rowKey: '2550',
      changes: { MEMO: '委托研发' }
    });
  });

  it('填写字典以外的值"外部合作"：照样写这个文本，显示也是它', async () => {
    const ctx = await openClassPage();
    const { runtime } = ctx;
    const columns = buildColumns(runtime, runtime.view.value!.master);
    const memo = columns.find(c => c.colId === 'MEMO')!;
    expect(setValue(memo, { ...runtime.gridRow(MASTER, '2550') }, '外部合作')).toBe(true);
    expect(runtime.model.buffer.documents()[0].master).toEqual({
      op: 'modify',
      rowKey: '2550',
      changes: { MEMO: '外部合作' }
    });
    const field = runtime.view.value!.master.fields.find(f => f.name === 'MEMO') as ViewField;
    expect(displayText(field, '外部合作', runtime.dicts.get('pingguClass'))).toBe('外部合作');
  });

  it('没有勾"可填写"的字典字段仍用只能选字典值的下拉', async () => {
    const view = displayView();
    const memo = view.master.fields.find(f => f.name === 'MEMO')!;
    delete memo.dictFreeText;
    const ctx = await openCostPage(view, fake =>
      fake.http.on('GET', '/api/dicts/:dictType', { items: CLASSES.map(v => ({ value: v, label: v })) })
    );
    const column = buildColumns(ctx.runtime, ctx.runtime.view.value!.master).find(c => c.colId === 'MEMO')!;
    expect(column.cellEditor).toBe('agSelectCellEditor');
  });
});
