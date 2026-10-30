/**
 * 成本核算主表的产品 Lookup（FP-15，C05 v5 `fillWritable`）：新增、复制的成本单带上产品。模拟验证。
 *
 * 旧系统（cost-web useLookupDialog.ts:79-98、LookupDialog.vue、useWorkingSetStore.ts:834-876，cost-server
 * DynamicDataService.java:274-327）：产品ID 列 EDITABLE=0 但配了产品 Lookup，点开即选，按 mapping 回填产品名称、规格等
 * 不可编辑的列；新增、复制的行保存时提交行中全部字段，后端照样写库。新平台：产品ID 可编辑并配 Lookup；回填目标不能直接
 * 填写，页面视图标 `fillWritable`，命令中带上它们。
 *
 * 数据取自 d_cg：产品 392（500mg对乙酰氨基酚片，cmx 的 V_COST_GOODS_LOOKUP）、成本单 200721
 * （.reports/batch3-20261030/h3-new-doc/q06-Lookup数据源核对.out.txt）。
 */
import { describe, expect, it } from 'vitest';
import type { DataRow, RecordResponse } from '../../src/contracts/http';
import type { PageView, ViewField } from '../../src/contracts/page-view';
import { MASTER, MATERIAL, costView, openCostPage } from './support';

const PRODUCT_FILL = {
  GOODSID: 'GOODSID',
  GOODSNAME: 'GOODSNAME',
  STRENGTH: 'STRENGTH',
  MA_NO: 'MA_NO',
  APEX_PL: 'APEX_PL',
  MAH: 'MAH',
  CUSTOMID: 'CUSTOMID',
  CUSTOMNAME: 'CUSTOMNAME'
};

const field = (name: string, label: string, extra: Partial<ViewField> = {}): ViewField => ({
  name,
  label,
  type: 'text',
  scale: null,
  source: 'own',
  calculated: false,
  visible: true,
  editable: false,
  required: false,
  width: 120,
  pinned: null,
  dictType: null,
  lookup: null,
  ...extra
});

/** seed 的成本核算主表（删减）：产品ID 配产品 Lookup；回填目标中只有批量可编辑，其余 fillWritable；项目号两者都不是 */
function productView(): PageView {
  const view = costView();
  view.master.fields = [
    field('DOCID', 'ID', { type: 'number', scale: 0, pinned: 'left' }),
    field('GOODSID', '产品ID', { type: 'number', editable: true, lookup: { code: 'costGoods', fill: PRODUCT_FILL } }),
    field('GOODSNAME', '产品名称', { fillWritable: true }),
    field('STRENGTH', '规格', { fillWritable: true }),
    field('MA_NO', '注册证号', { fillWritable: true }),
    field('APEX_PL', '批量', { type: 'number', editable: true }),
    field('MAH', '注册持有人', { fillWritable: true }),
    field('CUSTOMID', '客户ID', { type: 'number', editable: true }),
    field('CUSTOMNAME', '客户名称', { fillWritable: true }),
    field('PROJECTNO', '项目号'),
    field('MEMO', '备注', { editable: true })
  ];
  return view;
}

const PRODUCT_392 = {
  GOODSID: '392',
  GOODSNAME: '500mg对乙酰氨基酚片',
  STRENGTH: '500mg',
  MA_NO: 'PL 33414/0126',
  APEX_PL: '2400000',
  MAH: 'Chelonia',
  CUSTOMID: '737',
  CUSTOMNAME: 'Genesis Pharmaceuticals Limited'
};

const doc200721: DataRow = {
  rowKey: '200721',
  values: {
    DOCID: '200721',
    GOODSID: '392',
    GOODSNAME: '500mg对乙酰氨基酚片',
    STRENGTH: '500mg',
    MA_NO: 'PL 334140126',
    APEX_PL: '2400000',
    MAH: 'Chelonia',
    CUSTOMID: '1210180',
    CUSTOMNAME: '邹总-古巴',
    PROJECTNO: 'P-01',
    MEMO: null
  },
  frozen: null
};

const RECORDS: Record<string, RecordResponse> = { '200721': { master: doc200721, details: { [MATERIAL]: [] } } };

function answerLookup(fake: Awaited<ReturnType<typeof openCostPage>>['fake']) {
  fake.http.on('POST', '/api/lookups/:lookupCode/search', {
    rows: [{ values: { ...PRODUCT_392, MEMO: 'ERP已搭建BOM', LIVERY: 'Genesis', GOODSNAME_EN: null } }],
    total: 1,
    keywordSearch: true
  });
}

describe('成本核算主表的产品 Lookup（C05 fillWritable）', () => {
  it('新增一张成本单，用产品 Lookup 选产品 392：带出回填字段，命令中带上产品ID 和不可编辑的回填目标', async () => {
    const ctx = await openCostPage(productView(), undefined, RECORDS);
    const { runtime, fake, master } = ctx;
    answerLookup(fake);
    await runtime.addRow(MASTER);
    const id = master.ids[0];
    expect(id).toMatch(/^tmp-/);
    // 与旧系统相同：产品ID 不能直接输入，只能经 Lookup 选（单元格可编辑，Lookup 才能打开）；产品名称等不能直接填写
    expect(runtime.cellEditable(MASTER, id, 'GOODSID')).toBe(false);
    expect(runtime.model.cellEditable(MASTER, id, 'GOODSID')).toBe(true);
    expect(runtime.cellEditable(MASTER, id, 'GOODSNAME')).toBe(false);
    expect(runtime.model.cellEditable(MASTER, id, 'GOODSNAME')).toBe(false);
    await runtime.openLookup(MASTER, id, 'GOODSID');
    const [search] = fake.http.callsTo('POST', '/api/lookups/:lookupCode/search');
    expect(search.params.lookupCode).toBe('costGoods');
    runtime.confirmLookup(runtime.ui.lookup.value!.rows);
    expect(runtime.gridRow(MASTER, id)).toMatchObject(PRODUCT_392);
    expect(runtime.cellEditable(MASTER, id, 'GOODSNAME')).toBe(false);
    const [document] = runtime.model.buffer.documents();
    expect(document.master).toEqual({ op: 'add', clientRowId: id, values: { ...PRODUCT_392 } });
  });

  it('复制 200721 只复制主表：新单据的命令带 copyOf、产品ID 392 和产品名称等；不可编辑的项目号也写（后端取源行的值）', async () => {
    const ctx = await openCostPage(productView(), undefined, RECORDS);
    const { runtime, master } = ctx;
    master.select('200721');
    runtime.onSelection(MASTER, ['200721']);
    await runtime.openCopy(MASTER);
    const copy = runtime.ui.copy.value!;
    await runtime.confirmCopy({ fields: copy.selection.fields, details: { [MATERIAL]: { rows: [], fields: [] } } });
    const newId = master.ids[master.ids.indexOf('200721') + 1];
    expect(runtime.gridRow(MASTER, newId)).toMatchObject({
      GOODSID: '392',
      GOODSNAME: '500mg对乙酰氨基酚片',
      PROJECTNO: 'P-01'
    });
    const [document] = runtime.model.buffer.documents();
    expect(document).toEqual({
      entity: MASTER,
      master: {
        op: 'add',
        clientRowId: newId,
        // 同旧系统复制源行全部字段（copy-row-fields.ts）：不可编辑、也不是回填目标的项目号也写进命令（C02 copyOf，WP-21）
        copyOf: '200721',
        values: {
          GOODSID: '392',
          GOODSNAME: '500mg对乙酰氨基酚片',
          STRENGTH: '500mg',
          MA_NO: 'PL 334140126',
          APEX_PL: '2400000',
          MAH: 'Chelonia',
          CUSTOMID: '1210180',
          CUSTOMNAME: '邹总-古巴',
          PROJECTNO: 'P-01',
          MEMO: null
        }
      },
      details: []
    });
  });

  it('已保存的成本单 200721 重新选产品 392：修改中带变了的回填字段（含不可编辑的注册证号、客户名称），没变的不带', async () => {
    const ctx = await openCostPage(productView(), undefined, RECORDS);
    const { runtime, fake } = ctx;
    answerLookup(fake);
    await runtime.openLookup(MASTER, '200721', 'GOODSID');
    runtime.confirmLookup(runtime.ui.lookup.value!.rows);
    const [document] = runtime.model.buffer.documents();
    expect(document.master).toEqual({
      op: 'modify',
      rowKey: '200721',
      changes: { MA_NO: 'PL 33414/0126', CUSTOMID: '737', CUSTOMNAME: 'Genesis Pharmaceuticals Limited' }
    });
  });

  it('明细的物料名称不是 fillWritable（只在视图中）：换物料时照旧只带物料ID 和单价', async () => {
    const view = productView();
    const ctx = await openCostPage(view);
    const { runtime, fake } = ctx;
    ctx.master.select('2550');
    runtime.onSelection(MASTER, ['2550']);
    await runtime.activate('2550');
    fake.http.on('POST', '/api/lookups/:lookupCode/search', {
      rows: [{ values: { GOODSID: '13165', NAME: '微晶纤维素', ZX_PRICE: '40' } }],
      total: 1,
      keywordSearch: true
    });
    await runtime.openLookup(MATERIAL, '206325', 'GOODSID');
    runtime.confirmLookup(runtime.ui.lookup.value!.rows);
    expect(runtime.model.buffer.documents()[0].details[0]).toEqual({
      entity: MATERIAL,
      op: 'modify',
      rowKey: '206325',
      changes: { GOODSID: '13165', PRICE: '40' }
    });
  });
});
