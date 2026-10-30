/**
 * 汇总行（C06 第 3 节 `aggregate`，同旧系统 cost-pinggu 列配置的"求和"）：主表区为列表接口的汇总加上还没保存的修改，
 * 保存后按同样的查询条件重新取汇总；明细区为当前单据的明细行之和，标为删除的行不计入。显示格式同这一列。
 * 用 contracts 的 C09 模拟实现和 FakeGrid（support.ts）。
 */
import { describe, expect, it } from 'vitest';
import type { CommandResult } from '../../src/contracts/command';
import type { EvaluationResult } from '../../src/contracts/rules';
import type { PageView } from '../../src/contracts/page-view';
import { buildColumns } from '../../src/modules/page/grid-adapter/columns';
import { SUMMARY_ROW_ID } from '../../src/modules/page/summary';
import { MASTER, MATERIAL, costView, masterRow, openCostPage, selectRecord } from './support';

/** 成本核算页：主表的数量、总成本，原辅料的金额求和 */
function summedView(): PageView {
  const view = costView();
  for (const f of view.master.fields) if (f.name === 'QTY' || f.name === 'TOTAL_COST') f.aggregate = 'sum';
  for (const f of view.details[0].fields) if (f.name === 'AMOUNT') f.aggregate = 'sum';
  return view;
}

const FILTER = { GOODSNAME: { filterType: 'text', type: 'contains', filter: '片' } };

/** 产品名称含"片"的成本单共 5 张，第一页只显示 2550、2551；汇总是 5 张的和 */
async function openSummed() {
  const ctx = await openCostPage(summedView());
  ctx.fake.http.on('POST', '/api/pages/:pageCode/rows', {
    rows: [masterRow('2550', null), masterRow('2551', '原备注')],
    total: 5,
    aggregates: { QTY: '50', TOTAL_COST: '65.0325' }
  });
  await ctx.runtime.fetchMasterRows({ startRow: 0, endRow: 100, filterModel: FILTER });
  // 预览：2550 的聚维酮K30 单价改成 80 后，金额 800，主表总成本 13.0507
  ctx.fake.calc.respond(
    (): EvaluationResult => ({
      ok: true,
      rows: [
        {
          entity: MASTER,
          rowKey: '2550',
          computed: { TOTAL_COST: '13.0507' },
          fields: {},
          style: { row: null, cells: {} }
        },
        { entity: MATERIAL, rowKey: '206323', computed: { AMOUNT: '800' }, fields: {}, style: { row: null, cells: {} } }
      ],
      effects: []
    })
  );
  return ctx;
}

describe('汇总行', () => {
  it('成本核算主表：后端的汇总加上还没保存的修改；保存后按同样的筛选重新取汇总', async () => {
    const ctx = await openSummed();
    const { runtime, fake } = ctx;
    expect(runtime.summaryRow(MASTER)).toEqual({ QTY: '50', TOTAL_COST: '65.0325', __id: SUMMARY_ROW_ID });

    // 2550 的数量 10 改成 12；原辅料聚维酮K30 单价改成 80，预览算出 2550 的总成本 13.0065 → 13.0507
    runtime.edit(MASTER, '2550', 'QTY', '12');
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206323', 'PRICE', '80');
    await runtime.settled();
    expect(runtime.summaryRow(MASTER)).toEqual({ QTY: '52', TOTAL_COST: '65.0767', __id: SUMMARY_ROW_ID });

    // 显示格式同这一列：总成本 2 位小数；汇总行不能编辑，没有表单按钮
    const columns = buildColumns(runtime, runtime.view.value!.master, true);
    const total = columns.find(c => c.colId === 'TOTAL_COST')!;
    const row = runtime.summaryRow(MASTER)!;
    expect((total.valueFormatter as (p: unknown) => string)({ value: row.TOTAL_COST })).toBe('65.08');
    expect((total.editable as (p: unknown) => boolean)({ data: row })).toBe(false);
    expect((columns[0].cellRenderer as (p: unknown) => unknown)({ data: row, node: { rowPinned: 'bottom' } })).toBe('');

    // 新增一张成本单，数量填 5：计入汇总
    await runtime.addRow(MASTER);
    const added = runtime.model.newMasterRows()[0].id;
    runtime.edit(MASTER, added, 'QTY', '5');
    expect(runtime.summaryRow(MASTER)?.QTY).toBe('57');
    runtime.undo();
    runtime.undo();
    expect(runtime.summaryRow(MASTER)?.QTY).toBe('52');

    // 保存：保存后正式数据变了，按同样的筛选只取总数和汇总
    const row2550 = masterRow('2550', null);
    const saved: CommandResult = {
      requestKey: 'k',
      outcome: 'saved',
      rows: [{ ...row2550, entity: MASTER, values: { ...row2550.values, QTY: '12', TOTAL_COST: '13.0507' } }],
      idMap: {},
      prompts: [],
      skipped: [],
      approvals: []
    };
    fake.http.on('POST', '/api/commands', saved);
    fake.http.on('POST', '/api/pages/:pageCode/rows', {
      rows: [],
      total: 5,
      aggregates: { QTY: '52', TOTAL_COST: '65.0767' }
    });
    await runtime.save();
    const last = fake.http.callsTo('POST', '/api/pages/:pageCode/rows').at(-1)!;
    expect(last.body).toEqual({ startRow: 0, endRow: 0, filterModel: FILTER });
    expect(runtime.state.dirtyCount).toBe(0);
    expect(runtime.summaryRow(MASTER)).toEqual({ QTY: '52', TOTAL_COST: '65.0767', __id: SUMMARY_ROW_ID });
  });

  it('成本单 2550 的原辅料：金额为三行之和；改价后按预览的金额，标为删除的玉米淀粉不计入，新增行计入', async () => {
    const ctx = await openSummed();
    const { runtime, material } = ctx;
    expect(runtime.summaryRow(MATERIAL)).toBeNull();
    await selectRecord(ctx, '2550');
    // 聚维酮K30 750、硬脂酸镁 700、玉米淀粉 380
    expect(runtime.summaryRow(MATERIAL)).toEqual({ AMOUNT: '1830', __id: SUMMARY_ROW_ID });

    runtime.edit(MATERIAL, '206323', 'PRICE', '80');
    await runtime.settled();
    expect(runtime.summaryRow(MATERIAL)?.AMOUNT).toBe('1880');

    material.selected = ['206325'];
    runtime.deleteSelected(MATERIAL);
    expect(runtime.summaryRow(MATERIAL)?.AMOUNT).toBe('1500');

    await runtime.addRow(MATERIAL);
    const [added] = runtime.model.buffer.newRows(MATERIAL, '2550');
    runtime.model.buffer.set(MATERIAL, added.id, 'USAGE', '1');
    runtime.model.setPreview([
      {
        entity: MATERIAL,
        clientRowId: added.id,
        computed: { AMOUNT: '12.5' },
        fields: {},
        style: { row: null, cells: {} }
      }
    ]);
    expect(runtime.summaryRow(MATERIAL)?.AMOUNT).toBe('1512.5');
  });

  it('汇总行的布尔列（原辅料的"客户指定"）不画复选框；普通行照常用 AG Grid 的复选框', async () => {
    const view = summedView();
    view.details[0].fields.push({
      ...view.details[0].fields[0],
      name: 'CUSTOMER_SPECIFIED',
      label: '客户指定',
      type: 'boolean'
    });
    const { runtime } = await openCostPage(view);
    const columns = buildColumns(runtime, runtime.view.value!.details[0], false);
    const specified = columns.find(c => c.colId === 'CUSTOMER_SPECIFIED')!;
    expect(specified.cellDataType).toBe('boolean');
    const select = specified.cellRendererSelector as (p: unknown) => { component: () => string } | undefined;
    const pinned = select({ node: { rowPinned: 'bottom' }, data: { __id: SUMMARY_ROW_ID } });
    expect(pinned?.component()).toBe('');
    expect(select({ node: { rowPinned: undefined }, data: { __id: '206323' } })).toBeUndefined();
    // 其他列不受影响
    expect(columns.find(c => c.colId === 'AMOUNT')!.cellRendererSelector).toBeUndefined();
  });
});
