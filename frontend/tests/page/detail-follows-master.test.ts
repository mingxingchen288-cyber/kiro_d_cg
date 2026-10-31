/**
 * 明细跟着主表（用户 2026-10-31："查询一条不存在的数据，从表依然存在……从表必须跟随主表出现"）。模拟验证。
 *
 * 旧系统分屏模式（cost-web/src/v3/components/MasterDetailLayoutV3.vue 的 onSelectionChanged）：主表没有选中行时
 * setActiveMasterContext(null)，明细区显示"请选择主表记录"。新平台：主表按新的条件（列头筛选、高级查询）查询后，
 * 明细区显示的单据不在结果中时，主表取消选中、明细清空；主表没有选中行时明细清空。
 * 数据取自成本核算页（support.ts）：成本单 2550 的原辅料为聚维酮K30、硬脂酸镁、玉米淀粉；2551 为聚维酮K30。
 */
import { describe, expect, it } from 'vitest';
import { MASTER, RECORDS, openCostPage, selectRecord } from './support';

const EMPTY = { rows: [], total: 0, aggregates: {} };
const ONLY_2551 = { rows: [RECORDS['2551'].master], total: 1, aggregates: {} };

describe('明细跟着主表', () => {
  it('列头筛选单据号 999999 查不到：主表取消选中，明细清空', async () => {
    const ctx = await openCostPage();
    await selectRecord(ctx, '2550');
    expect([ctx.runtime.state.activeRecord, ctx.material.ids.length]).toEqual(['2550', 3]);

    ctx.fake.http.on('POST', '/api/pages/:pageCode/rows', EMPTY);
    const page = await ctx.runtime.fetchMasterRows({
      startRow: 0,
      endRow: 100,
      filterModel: { DOCID: { filterType: 'number', type: 'equals', filter: 999999 } }
    });
    expect([page.rows.length, ctx.runtime.state.activeRecord, ctx.material.ids, ctx.master.selected]).toEqual([
      0,
      null,
      [],
      []
    ]);
  });

  it('高级查询只查到 2551：明细区原来显示的 2550 不在结果中，明细清空；再选中 2551 显示它的明细', async () => {
    const ctx = await openCostPage();
    await selectRecord(ctx, '2550');

    ctx.fake.http.on('POST', '/api/pages/:pageCode/rows', ONLY_2551);
    ctx.runtime.applyAdvanced({ op: 'and', conditions: [{ field: 'MEMO', operator: 'like', value: '原备注' }] });
    await ctx.runtime.fetchMasterRows({ startRow: 0, endRow: 100, sortModel: [], filterModel: {} });
    expect([ctx.runtime.state.activeRecord, ctx.material.ids]).toEqual([null, []]);

    await selectRecord(ctx, '2551');
    expect(ctx.material.ids).toEqual(['206400']);
  });

  it('新条件的结果里还有 2550：明细照常显示 2550', async () => {
    const ctx = await openCostPage();
    await selectRecord(ctx, '2550');
    await ctx.runtime.fetchMasterRows({
      startRow: 0,
      endRow: 100,
      filterModel: { GOODSNAME: { filterType: 'text', type: 'contains', filter: '乙酰唑胺' } }
    });
    expect([ctx.runtime.state.activeRecord, ctx.material.ids.length, ctx.master.selected]).toEqual([
      '2550',
      3,
      ['2550']
    ]);
  });

  it('主表取消选中（没有选中的行）：明细清空', async () => {
    const ctx = await openCostPage();
    await selectRecord(ctx, '2550');
    ctx.master.selected = [];
    ctx.runtime.onSelection(MASTER, []);
    expect([ctx.runtime.state.activeRecord, ctx.material.ids]).toEqual([null, []]);
  });
});
