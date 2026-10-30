/**
 * 高级查询（FP-20，C05 v7 `searchable`）：对话框一打开就列出预置条件，填值即勾上，有 Lookup 的字段用 Lookup 选值。模拟验证。
 *
 * 旧系统（cost-web/src/v3）：`composables/meta-v3/useAdvancedSearch.ts` 第 248 行只把可见且勾了"查询"的列列为条件，
 * 主表在前、明细按页签顺序；默认运算符第 301–309 行（Lookup、下拉为等于，文本为包含）；`components/AdvancedSearchDialog.vue`
 * 第 233 行 markEnabled（填值即勾上）、第 258 行 hideCondition、第 70、366–390 行 openLookup（IN、NOT IN 时多选，
 * 选中的值追加并去重，第 345 行 appendLookupValues）。
 * 数据取自成本核算页（support.ts 的 costView）：主表加客户ID（客户 Lookup costCustomer，同 seed），客户 13、27。
 */
import { describe, expect, it } from 'vitest';
import type { FieldValues } from '../../src/contracts/command';
import type { PageView, ViewField } from '../../src/contracts/page-view';
import {
  buildAdvanced,
  enabledCount,
  hideCondition,
  pickLookup,
  presetConditions,
  resetConditions,
  setOperator,
  setValue,
  syncConditions
} from '../../src/modules/page/advanced-search';
import { MASTER, MATERIAL, costView, openCostPage } from './support';

const CUSTOMER: ViewField = {
  name: 'CUSTOMID',
  label: '客户ID',
  type: 'number',
  scale: 0,
  source: 'own',
  calculated: false,
  visible: true,
  editable: true,
  required: false,
  width: 120,
  pinned: null,
  dictType: null,
  lookup: { code: 'costCustomer', fill: { CUSTOMID: 'CUSTOMID', CUSTOMNAME: 'CUSTOMNAME' } }
};

/** 成本核算页：主表的单据号、产品名称、客户ID、总成本和原辅料的物料、单价勾了"查询"；剂型 FORM 不可见，勾了也不列 */
function searchView(): PageView {
  const view = costView();
  view.master.fields.splice(2, 0, { ...CUSTOMER });
  for (const f of view.master.fields)
    if (['DOCID', 'GOODSNAME', 'CUSTOMID', 'TOTAL_COST', 'FORM'].includes(f.name)) f.searchable = true;
  for (const f of view.details[0].fields) if (['GOODSID', 'PRICE'].includes(f.name)) f.searchable = true;
  return view;
}

const keys = (view: PageView) => presetConditions(view).map(d => d.key);

describe('预置条件（字段的"查询"标记）', () => {
  it('列出勾了"查询"的可见字段：先主表再明细，按字段顺序；不可见的剂型不列；默认运算符文本为包含，Lookup 和数值为等于', () => {
    const view = searchView();
    const presets = presetConditions(view);
    expect(presets.map(d => [d.key, d.entity, d.operator, d.enabled])).toEqual([
      ['master:DOCID', null, 'eq', false],
      ['master:GOODSNAME', null, 'like', false],
      ['master:CUSTOMID', null, 'eq', false],
      ['master:TOTAL_COST', null, 'eq', false],
      [`${MATERIAL}:GOODSID`, MATERIAL, 'eq', false],
      [`${MATERIAL}:PRICE`, MATERIAL, 'eq', false]
    ]);
    // 个人列配置中隐藏了的列不列（旧系统列配置叠加个人配置后隐藏的列不进条件）
    const personal = {
      grids: { master: { columns: [{ field: 'TOTAL_COST', width: 120, pinned: null, hide: true }] } }
    };
    expect(presetConditions(view, personal).map(d => d.key)).not.toContain('master:TOTAL_COST');
    expect(keys(costView())).toEqual([]);
  });

  it('产品名称填"片"即勾上：只带这一条查询，与列头筛选"产品名称含片"同为 like；没填的预置条件不带；请求带 advanced', async () => {
    const view = searchView();
    const drafts = presetConditions(view);
    const name = drafts.find(d => d.field === 'GOODSNAME')!;
    setValue(name, '片');
    expect(name.enabled).toBe(true);
    expect(enabledCount(view, drafts)).toBe(1);
    const advanced = buildAdvanced(view, drafts, 'and');
    expect(advanced).toEqual({ op: 'and', conditions: [{ field: 'GOODSNAME', operator: 'like', value: '片' }] });

    const { runtime, fake, master } = await openCostPage(view);
    runtime.applyAdvanced(advanced);
    expect(master.reloads).toEqual([true]);
    await runtime.fetchMasterRows({ startRow: 0, endRow: 100, sortModel: [], filterModel: {} });
    expect(fake.http.callsTo('POST', '/api/pages/:pageCode/rows').at(-1)!.body).toMatchObject({ advanced });

    // 清空值即取消勾选，不再带
    setValue(name, '');
    expect([name.enabled, buildAdvanced(view, drafts, 'and')]).toEqual([false, null]);
  });

  it('原辅料的物料为 115、单价大于 3：两条预置的明细条件在组 g1、且，由同一条明细行满足（同旧系统一个 EXISTS）', () => {
    const view = searchView();
    const drafts = presetConditions(view);
    setValue(drafts.find(d => d.key === `${MATERIAL}:GOODSID`)!, '115');
    const price = drafts.find(d => d.key === `${MATERIAL}:PRICE`)!;
    setOperator(price, 'gt');
    setValue(price, '3');
    expect(buildAdvanced(view, drafts, 'and')).toEqual({
      op: 'and',
      conditions: [
        { entity: MATERIAL, group: 'g1', field: 'GOODSID', operator: 'eq', value: '115' },
        { entity: MATERIAL, group: 'g1', logic: 'and', field: 'PRICE', operator: 'gt', value: '3' }
      ]
    });
  });

  it('隐藏单据号后它的值清空、不带；重新打开时上次的值和隐藏保留；重置清空值和勾选，隐藏的仍隐藏', () => {
    const view = searchView();
    let drafts = presetConditions(view);
    const docid = drafts.find(d => d.field === 'DOCID')!;
    setValue(docid, '2550');
    hideCondition(docid);
    setValue(drafts.find(d => d.field === 'GOODSNAME')!, '片');
    expect(buildAdvanced(view, drafts, 'and')!.conditions.map(c => c.field)).toEqual(['GOODSNAME']);

    drafts = syncConditions(view, {}, drafts);
    expect(drafts.find(d => d.field === 'DOCID')).toMatchObject({ visible: false, value: '', enabled: false });
    expect(drafts.find(d => d.field === 'GOODSNAME')).toMatchObject({ value: '片', enabled: true });

    drafts = resetConditions(drafts);
    expect(buildAdvanced(view, drafts, 'and')).toBeNull();
    expect(drafts.find(d => d.field === 'DOCID')!.visible).toBe(false);
  });
});

describe('值用 Lookup 选', () => {
  it('客户ID 选 IN，用客户 Lookup 先后选 13、27 和 13：值为"13, 27"，查询带 in [13, 27]；Lookup 不按行过滤、不回填到行', async () => {
    const view = searchView();
    const { runtime, fake } = await openCostPage(view);
    fake.http.on('POST', '/api/lookups/:lookupCode/search', {
      rows: [
        { values: { CUSTOMID: '13', CUSTOMNAME: 'Chelonia' } },
        { values: { CUSTOMID: '27', CUSTOMNAME: 'Genesis' } }
      ],
      total: 2,
      keywordSearch: true
    });
    const drafts = presetConditions(view);
    const customer = drafts.find(d => d.field === 'CUSTOMID')!;
    setOperator(customer, 'in');

    const select = (rows: FieldValues[]) => pickLookup(customer, CUSTOMER, rows);
    await runtime.openSearchLookup(MASTER, 'CUSTOMID', { multiple: true, select });
    const [search] = fake.http.callsTo('POST', '/api/lookups/:lookupCode/search');
    expect(search.params.lookupCode).toBe('costCustomer');
    expect(search.body).toEqual({ keyword: '', startRow: 0, endRow: 500 });
    expect(runtime.ui.lookup.value).toMatchObject({ title: '客户ID', multiple: true, fillBack: true, total: 2 });
    runtime.confirmLookup([runtime.ui.lookup.value!.rows[0]]);
    expect(runtime.ui.lookup.value).toBeNull();
    expect([customer.value, customer.enabled]).toEqual(['13', true]);

    await runtime.openSearchLookup(MASTER, 'CUSTOMID', { multiple: true, select });
    runtime.confirmLookup(runtime.ui.lookup.value!.rows);
    expect(customer.value).toBe('13, 27');
    expect(runtime.model.buffer.documents()).toEqual([]);
    expect(buildAdvanced(view, drafts, 'and')).toEqual({
      op: 'and',
      conditions: [{ field: 'CUSTOMID', operator: 'in', value: ['13', '27'] }]
    });

    // 换回等于时只留第一个值；等于时 Lookup 单选，替换已有的值
    setOperator(customer, 'eq', true);
    expect(customer.value).toBe('13');
    pickLookup(customer, CUSTOMER, [{ CUSTOMID: '27', CUSTOMNAME: 'Genesis' }]);
    expect(buildAdvanced(view, drafts, 'and')!.conditions).toEqual([
      { field: 'CUSTOMID', operator: 'eq', value: '27' }
    ]);
  });
});
