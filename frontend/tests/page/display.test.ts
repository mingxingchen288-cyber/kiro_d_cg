/**
 * FP-18（模拟验证）：页面一显示就带界面规则的效果（C07 v6 第 3.1 节显示求值，对应旧系统 GRID_STYLE 在渲染行时按行数据
 * 算样式、usePageRules.ts 的 buildRowStyleCallback）。计算 Worker 用 contracts 的模拟实现，按下面假设的界面规则给出结果，
 * 与 rules-core 的显示求值相同：不计算（computed 为空）、不校验（effects 为空）。
 *
 * 假设的规则：主表 MEMO 为"ERP未搭建BOM"整行红底（d_cg 已发布的 R_MASTER_NO_BOM_RED）；原辅料硬脂酸镁的单价不可编辑、
 * 字体变灰，备注必填。
 */
import { describe, expect, it } from 'vitest';
import type { CommandResult } from '../../src/contracts/command';
import type { EvalRowResult, EvaluationRequest, EvaluationResult } from '../../src/contracts/rules';
import { MASTER, MATERIAL, costView, masterRow, openCostPage, selectRecord } from './support';

const RED = { backgroundColor: '#ffcccc' };

function uiRules(request: EvaluationRequest): EvaluationResult {
  const master = request.document.master;
  const rows: EvalRowResult[] = [
    {
      entity: MASTER,
      rowKey: master.rowKey,
      computed: {},
      fields: {},
      style: { row: master.values.MEMO === 'ERP未搭建BOM' ? RED : null, cells: {} }
    }
  ];
  for (const row of request.document.details[MATERIAL] ?? []) {
    const stearate = row.values.GOODSNAME === '硬脂酸镁';
    rows.push({
      entity: MATERIAL,
      rowKey: row.rowKey,
      computed: {},
      fields: stearate ? { PRICE: { editable: false }, MEMO: { required: true } } : {},
      style: { row: null, cells: stearate ? { PRICE: { color: '#999999' } } : {} }
    });
  }
  return { ok: true, rows, effects: [] };
}

const displays = (requests: EvaluationRequest[], recordId: string) =>
  requests.filter(r => r.purpose === 'display' && r.document.master.rowKey === recordId);

describe('页面一显示就带界面规则的效果（FP-18）', () => {
  it('主表一块数据取到后不编辑，MEMO 为 ERP未搭建BOM 的单据就是红底；显示的仍是加载来的值，没有规则提示', async () => {
    const ctx = await openCostPage(costView(), fake => fake.calc.respond(uiRules));
    const { runtime, fake } = ctx;
    fake.http.on('POST', '/api/pages/:pageCode/rows', {
      rows: [masterRow('2550', null), masterRow('2919', 'ERP未搭建BOM')],
      total: 2,
      aggregates: {}
    });

    const page = await runtime.fetchMasterRows({ startRow: 0, endRow: 100 });

    expect(runtime.model.ruleView(MASTER, '2919')?.style.row).toEqual(RED);
    expect(runtime.model.ruleView(MASTER, '2550')?.style.row).toBeNull();
    expect(page.rows.find(r => r.__id === '2919')).toMatchObject({ TOTAL_COST: '13.0065', MEMO: 'ERP未搭建BOM' });
    expect(runtime.dirty).toBe(false);
    expect(runtime.ui.effects.value).toEqual([]);
    const [request] = displays(fake.calc.requests, '2919');
    // 主表列表没有加载明细：只给主表行，不带修改
    expect(request).toMatchObject({ phase: 'preview', page: MASTER, changed: [], data: {} });
    expect(request.document.details).toEqual({});
    expect(request.document.master).toEqual({ rowKey: '2919', values: masterRow('2919', 'ERP未搭建BOM').values });
    expect(fake.calc.requests.filter(r => r.purpose === 'operation')).toEqual([]);
  });

  it('选中单据后明细一显示就按界面规则：硬脂酸镁的单价不可编辑、字体变灰，备注必填；其他行不受影响', async () => {
    const ctx = await openCostPage(costView(), fake => fake.calc.respond(uiRules));
    const { runtime, fake } = ctx;

    await selectRecord(ctx, '2550');

    expect(runtime.cellEditable(MATERIAL, '206324', 'PRICE')).toBe(false);
    expect(runtime.model.ruleView(MATERIAL, '206324')?.style.cells.PRICE).toEqual({ color: '#999999' });
    expect(runtime.model.cellRequired(MATERIAL, '206324', 'MEMO')).toBe(true);
    expect(runtime.cellEditable(MATERIAL, '206323', 'PRICE')).toBe(true);
    expect(runtime.model.cellRequired(MATERIAL, '206323', 'MEMO')).toBe(false);
    expect(runtime.gridRow(MATERIAL, '206324').PRICE).toBe('70');
    expect(runtime.ui.effects.value).toEqual([]);
    const request = displays(fake.calc.requests, '2550').at(-1)!;
    expect(request.document.details[MATERIAL].map(r => r.rowKey)).toEqual(['206323', '206324', '206325']);
    expect(request.changed).toEqual([]);
  });

  it('备注改成 ERP未搭建BOM：编辑后按预览变红；保存后按保存的值重新做显示求值，仍是红底', async () => {
    const ctx = await openCostPage(costView(), fake => fake.calc.respond(uiRules));
    const { runtime, fake } = ctx;
    expect(runtime.model.ruleView(MASTER, '2550')?.style.row).toBeNull();

    runtime.edit(MASTER, '2550', 'MEMO', 'ERP未搭建BOM');
    await runtime.settled();
    expect(runtime.model.previewOf(MASTER, '2550')?.style.row).toEqual(RED);
    expect(runtime.model.ruleView(MASTER, '2550')?.style.row).toEqual(RED);

    const result: CommandResult = {
      requestKey: '7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f',
      outcome: 'saved',
      rows: [{ ...masterRow('2550', 'ERP未搭建BOM'), entity: MASTER }],
      idMap: {},
      prompts: [],
      skipped: [],
      approvals: []
    };
    fake.http.on('POST', '/api/commands', result);
    await runtime.save();
    await runtime.settled();

    expect(runtime.model.previewOf(MASTER, '2550')).toBeUndefined();
    expect(runtime.model.ruleView(MASTER, '2550')?.style.row).toEqual(RED);
    expect(displays(fake.calc.requests, '2550').at(-1)?.document.master.values.MEMO).toBe('ERP未搭建BOM');
  });
});
