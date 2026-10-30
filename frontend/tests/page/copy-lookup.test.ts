/**
 * T-FP-5 复制（FP-13，E09）、T-FP-6 默认值、Lookup 扩展与对比显示（FP-15，E28、E29），以及高级查询（E30 的请求）。模拟验证。
 */
import { describe, expect, it } from 'vitest';
import { DocumentPatch } from '../../src/contracts/command';
import { array } from '../../src/contracts/schema';
import { buildAdvanced, emptyCondition } from '../../src/modules/page/advanced-search';
import { COMPARE_DOWN_COLOR, COMPARE_UP_COLOR, compareDisplay, fieldOf } from '../../src/modules/page/fields';
import { MASTER, MATERIAL, costView, openCostPage, selectRecord } from './support';

describe('复制（FP-13）', () => {
  it('E09：复制有 3 条原辅料明细的成本单 2550，只勾选其中 2 条并去掉备注：新单据 2 条明细，备注为空，其余与源单据相同，主键是新的', async () => {
    const ctx = await openCostPage();
    const { runtime, master } = ctx;
    master.select('2550');
    runtime.onSelection(MASTER, ['2550']);
    // 源单据有未保存的修改：复制带上修改后的值
    await runtime.activate('2550');
    runtime.edit(MATERIAL, '206324', 'PRICE', '72');
    await runtime.openCopy(MASTER);
    const copy = runtime.ui.copy.value!;
    expect(copy.selection.fields).toEqual(['GOODSNAME', 'MEMO', 'QTY', 'TOTAL_COST', 'CREATE_BY', 'STATUS']);
    expect(copy.selection.details![MATERIAL].rows).toEqual(['206323', '206324', '206325']);
    await runtime.confirmCopy({
      fields: copy.selection.fields.filter(f => f !== 'MEMO'),
      details: {
        [MATERIAL]: {
          rows: ['206323', '206324'],
          fields: copy.selection.details![MATERIAL].fields.filter(f => f !== 'MEMO')
        }
      }
    });
    // 新主表行放在源行下方
    const newId = master.ids[master.ids.indexOf('2550') + 1];
    expect(newId).toMatch(/^tmp-/);
    const values = runtime.gridRow(MASTER, newId);
    expect(values).toMatchObject({
      DOCID: null,
      MEMO: null,
      GOODSNAME: '250mg乙酰唑胺片',
      QTY: '10',
      TOTAL_COST: '13.0065'
    });
    const details = runtime.model.detailIds(MATERIAL, newId).map(id => runtime.gridRow(MATERIAL, id));
    expect(details.map(d => [d.GOODSID, d.GOODSNAME, d.PRICE, d.MEMO, d.DTLID])).toEqual([
      ['25', '聚维酮K30', '75', null, null],
      ['115', '硬脂酸镁', '72', null, null]
    ]);
    const [document] = runtime.model.buffer.documents().filter(d => d.master.op === 'add');
    expect(array(DocumentPatch).parse([document])).toEqual([document]);
    // 没勾的备注写成 null：复制出的行后端不补默认值（WP-16），保存后为空
    expect(document.master).toEqual({
      op: 'add',
      clientRowId: newId,
      values: { MEMO: null, QTY: '10', STATUS: '评估中' }
    });
    expect(document.details.map(d => (d.op === 'add' ? d.values : null))).toEqual([
      { GOODSID: '25', PRICE: '75', USAGE: '10', MEMO: null },
      { GOODSID: '115', PRICE: '72', USAGE: '10', MEMO: null }
    ]);
    // 撤销一次撤回整个复制（源单据的改价还在）
    runtime.undo();
    expect(master.ids).not.toContain(newId);
    expect(runtime.model.buffer.documents().every(d => d.master.op !== 'add')).toBe(true);
    expect(runtime.model.buffer.isChanged(MATERIAL, '206324', 'PRICE')).toBe(true);
  });

  it('明细区复制：默认复制选中的行，放在最后一个选中行的下方', async () => {
    const ctx = await openCostPage();
    const { runtime, material } = ctx;
    await selectRecord(ctx, '2550');
    material.selected = ['206323', '206324'];
    runtime.onSelection(MATERIAL, material.selected);
    await runtime.openCopy(MATERIAL);
    const copy = runtime.ui.copy.value!;
    expect(copy.rows).toEqual(['206323', '206324']);
    await runtime.confirmCopy(copy.selection, copy.rows);
    expect(material.ids.slice(0, 2)).toEqual(['206323', '206324']);
    expect(material.ids.slice(2, 4).every(id => id.startsWith('tmp-'))).toBe(true);
    expect(material.ids[4]).toBe('206325');
    expect(runtime.gridRow(MATERIAL, material.ids[3]).GOODSNAME).toBe('硬脂酸镁');
  });
});

describe('默认值（FP-15，E28）', () => {
  it('张三新增一行：CREATE_BY 默认为当前用户、不可编辑，STATUS 默认为下拉第一个值；命令中不带 CREATE_BY', async () => {
    const { runtime, master } = await openCostPage();
    await runtime.addRow(MASTER);
    const id = master.ids[0];
    expect(runtime.gridRow(MASTER, id)).toMatchObject({ CREATE_BY: '张三', STATUS: '草稿', QTY: '0', MEMO: null });
    expect(runtime.cellEditable(MASTER, id, 'CREATE_BY')).toBe(false);
    const view = runtime.view.value!;
    expect(fieldOf(view, MASTER, 'STATUS')?.default).toEqual({ type: 'options', value: ['草稿', '评估中'] });
    const [document] = runtime.model.buffer.documents();
    expect(document.master).toEqual({ op: 'add', clientRowId: id, values: { QTY: '0', STATUS: '草稿' } });
  });
});

describe('Lookup（FP-15）', () => {
  it('打开时先用空关键字查询；选中后按回填映射写入，一个撤销步骤', async () => {
    const ctx = await openCostPage();
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    fake.http.on('POST', '/api/lookups/:lookupCode/search', {
      rows: [{ values: { GOODSID: '13165', NAME: '微晶纤维素', ZX_PRICE: '40' } }],
      total: 1,
      keywordSearch: true
    });
    await runtime.openLookup(MATERIAL, '206325', 'GOODSID');
    const [search] = fake.http.callsTo('POST', '/api/lookups/:lookupCode/search');
    expect(search.params.lookupCode).toBe('GOODS');
    expect(search.body).toEqual({ keyword: '', startRow: 0, endRow: 500 });
    runtime.confirmLookup(runtime.ui.lookup.value!.rows);
    expect(runtime.gridRow(MATERIAL, '206325')).toMatchObject({
      GOODSID: '13165',
      GOODSNAME: '微晶纤维素',
      PRICE: '40'
    });
    // GOODSNAME 不可编辑，只显示，不进命令
    expect(runtime.model.buffer.documents()[0].details[0]).toEqual({
      entity: MATERIAL,
      op: 'modify',
      rowKey: '206325',
      changes: { GOODSID: '13165', PRICE: '40' }
    });
    runtime.undo();
    expect(runtime.gridRow(MATERIAL, '206325')).toMatchObject({ GOODSID: '116', GOODSNAME: '玉米淀粉', PRICE: '38' });
  });

  it('多选回填为逗号连接的值；按单元格值过滤时请求带 filter；keywordSearch 为 false 时不显示搜索框', async () => {
    const view = costView();
    const memo = view.details[0].fields.find(f => f.name === 'MEMO')!;
    memo.lookup = { code: 'TAGS', fill: { MEMO: 'TAG' }, multiple: true, filter: { column: 'TAG', from: 'cell' } };
    const ctx = await openCostPage(view);
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206323', 'MEMO', '甲');
    fake.http.on('POST', '/api/lookups/:lookupCode/search', {
      rows: [{ values: { TAG: '甲' } }, { values: { TAG: '乙' } }],
      total: 2,
      keywordSearch: false
    });
    await runtime.openLookup(MATERIAL, '206323', 'MEMO');
    const [search] = fake.http.callsTo('POST', '/api/lookups/:lookupCode/search');
    expect(search.body).toEqual({ keyword: '', filter: { column: 'TAG', value: '甲' }, startRow: 0, endRow: 500 });
    expect(runtime.ui.lookup.value!.keywordSearch).toBe(false);
    runtime.confirmLookup(runtime.ui.lookup.value!.rows);
    expect(runtime.gridRow(MATERIAL, '206323').MEMO).toBe('甲,乙');
  });

  it('fillBack 为 false 时只读的单元格也能打开，不改数据', async () => {
    const view = costView();
    const name = view.details[0].fields.find(f => f.name === 'GOODSNAME')!;
    name.lookup = { code: 'GOODS', fill: { GOODSNAME: 'NAME' }, fillBack: false };
    const ctx = await openCostPage(view);
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    await runtime.openLookup(MATERIAL, '206323', 'GOODSNAME');
    expect(runtime.ui.lookup.value?.fillBack).toBe(false);
    expect(fake.http.callsTo('POST', '/api/lookups/:lookupCode/search')).toHaveLength(1);
    runtime.confirmLookup([{ NAME: '别的物料' }]);
    expect(runtime.gridRow(MATERIAL, '206323').GOODSNAME).toBe('聚维酮K30');
    expect(runtime.model.buffer.size).toBe(0);
  });
});

describe('对比显示（FP-15，E29）', () => {
  const price = costView().details[0].fields.find(f => f.name === 'PRICE')!;

  it('当前 3.80、历史 3.50：差值 0.30、百分比 8.57%，向上箭头，红色（与旧系统相同）', () => {
    expect(compareDisplay(price, { value: '3.50', diff: '0.30', percent: '8.57' })).toEqual({
      arrow: '↑',
      color: COMPARE_UP_COLOR,
      text: '0.30 (8.57%)'
    });
    expect(COMPARE_UP_COLOR).toBe('#e53935');
  });

  it('历史为 0 时只显示差值；下降为绿色向下箭头', () => {
    expect(compareDisplay(price, { value: '0', diff: '3.80', percent: null })).toEqual({
      arrow: '↑',
      color: '#e53935',
      text: '3.80'
    });
    expect(compareDisplay(price, { value: '4.00', diff: '-0.20', percent: '-5.00' })).toEqual({
      arrow: '↓',
      color: COMPARE_DOWN_COLOR,
      text: '0.20 (5.00%)'
    });
    expect(COMPARE_DOWN_COLOR).toBe('#43a047');
  });
});

describe('高级查询', () => {
  it('E30：原辅料明细的物料为 115 且价格大于 3：两个条件在同一组，请求带 advanced', async () => {
    const view = costView();
    const first = { ...emptyCondition(view, MATERIAL), field: 'GOODSID', operator: 'eq', value: '115' };
    const second = { ...emptyCondition(view, MATERIAL), field: 'PRICE', operator: 'gt', value: '3' };
    const advanced = buildAdvanced(view, [first, second], 'and');
    expect(advanced).toEqual({
      op: 'and',
      conditions: [
        { entity: MATERIAL, group: 'g1', field: 'GOODSID', operator: 'eq', value: '115' },
        { entity: MATERIAL, group: 'g1', logic: 'and', field: 'PRICE', operator: 'gt', value: '3' }
      ]
    });
    const { runtime, fake, master } = await openCostPage(view);
    runtime.applyAdvanced(advanced);
    expect(master.reloads).toEqual([true]);
    await runtime.fetchMasterRows({ startRow: 0, endRow: 100, sortModel: [], filterModel: {} });
    expect(fake.http.callsTo('POST', '/api/pages/:pageCode/rows').at(-1)!.body).toMatchObject({ advanced });
  });
});
