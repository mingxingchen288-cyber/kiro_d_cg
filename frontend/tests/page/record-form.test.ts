/**
 * T-FP-21 通用的行表单（FP-03）：主表区和每个明细区用同一套。模拟验证（contracts 的 C09 模拟实现和 FakeGrid，support.ts）。
 *
 * 用户 2026-11-01："表单和表格可以公用一个元数据，表单唯一的区别仅仅是可以调整每个表单列的位置和带线（大小）"。
 * 旧系统没有行表单（主表、明细都没有），这是新平台的能力。
 * 数据取自成本核算页：成本单 2550 的原料/辅料为聚维酮K30（206323）、硬脂酸镁（206324）、玉米淀粉（206325）；2551 为聚维酮K30（206400）。
 */
import { describe, expect, it } from 'vitest';
import type { CommandResult } from '../../src/contracts/command';
import type { PageRuntime } from '../../src/modules/page/page-runtime';
import { formView } from '../../src/modules/page/record-form';
import { MASTER, MATERIAL, costView, materialRow, openCostPage, selectRecord } from './support';

const UUID = '7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f';

/** 2550 的聚维酮K30 备注改为"表单测试"时命令中的这张单据 */
const MEMO_PATCH = {
  entity: MASTER,
  master: { op: 'none', rowKey: '2550' },
  details: [{ entity: MATERIAL, op: 'modify', rowKey: '206323', changes: { MEMO: '表单测试' } }]
};

/** 表单中的字段：名称、位置和大小、显示的文字、能否编辑 */
function layoutOf(runtime: PageRuntime, entity: string) {
  return formView(runtime, entity)!.items.map(({ field, cell: { x, y, w, h }, text, editable }) => ({
    field: field.name,
    x,
    y,
    w,
    h,
    text,
    editable
  }));
}

describe('明细的行表单（FP-03）', () => {
  it('2550 原料/辅料点聚维酮K30 的 ⊞：明细区显示这一行的表单，按明细的 formLayout 排；主表的表单同时开着', async () => {
    const view = costView();
    // 配置页给"明细 · 原料/辅料"保存的布局：备注占满一行、两行高，物料名称和单价各占半行
    view.details[0].formLayout = [
      { field: 'MEMO', x: 0, y: 0, w: 24, h: 2 },
      { field: 'GOODSNAME', x: 0, y: 2, w: 12, h: 1 },
      { field: 'PRICE', x: 12, y: 2, w: 12, h: 1 }
    ];
    const ctx = await openCostPage(view);
    const { runtime, material } = ctx;
    await selectRecord(ctx, '2550');
    runtime.openForm(MASTER, '2550');
    runtime.openForm(MATERIAL, '206323');

    expect(runtime.state.forms).toEqual({ [MASTER]: '2550', [MATERIAL]: '206323' });
    // 明细表格中选中这一行（表格只设为不可见，选中行保留）
    expect(material.selected).toEqual(['206323']);
    expect(formView(runtime, MATERIAL)!.title).toBe('原料/辅料 聚维酮K30');
    expect(layoutOf(runtime, MATERIAL)).toEqual([
      { field: 'MEMO', x: 0, y: 0, w: 24, h: 2, text: '', editable: true },
      { field: 'GOODSNAME', x: 0, y: 2, w: 12, h: 1, text: '聚维酮K30', editable: false },
      { field: 'PRICE', x: 12, y: 2, w: 12, h: 1, text: '75.0000', editable: true }
    ]);
    // 主表的表单按主表的 formLayout，不受明细影响
    expect(formView(runtime, MASTER)!.title).toBe('单据 2550');
    expect(layoutOf(runtime, MASTER)).toEqual([{ field: 'MEMO', x: 0, y: 0, w: 12, h: 1, text: '', editable: true }]);
  });

  it('明细没有配置布局：可见字段按顺序每行 3 个（同主表），不可见的单据号不在表单中', async () => {
    const ctx = await openCostPage();
    await selectRecord(ctx, '2550');
    ctx.runtime.openForm(MATERIAL, '206324');

    expect(layoutOf(ctx.runtime, MATERIAL).map(({ field, x, y, w, h }) => [field, x, y, w, h])).toEqual([
      ['DTLID', 0, 0, 8, 1],
      ['GOODSID', 8, 0, 8, 1],
      ['GOODSNAME', 16, 0, 8, 1],
      ['PRICE', 0, 1, 8, 1],
      ['USAGE', 8, 1, 8, 1],
      ['AMOUNT', 16, 1, 8, 1],
      ['MEMO', 0, 2, 8, 1]
    ]);
    expect(formView(ctx.runtime, MATERIAL)!.items.find(i => i.field.name === 'GOODSNAME')!.text).toBe('硬脂酸镁');
  });

  it('在表单里把聚维酮K30 的备注改为"表单测试"：进编辑缓冲，表格同一行同步、标为改过；撤销恢复；保存同表格', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, material } = ctx;
    await selectRecord(ctx, '2550');
    runtime.openForm(MATERIAL, '206323');
    const memo = () => formView(runtime, MATERIAL)!.items.find(i => i.field.name === 'MEMO')!;

    expect(runtime.editForm(MATERIAL, 'MEMO', '表单测试')).toBe(true);
    expect(runtime.gridRow(MATERIAL, '206323').MEMO).toBe('表单测试');
    expect(material.updatedIds).toContain('206323');
    expect(runtime.state.dirtyCount).toBe(1);
    expect([memo().value, memo().marks]).toEqual(['表单测试', ['cell-user-changed']]);
    expect(runtime.model.buffer.documents()).toEqual([MEMO_PATCH]);

    // 撤销、重做和表格共用一个历史
    runtime.undo();
    expect([runtime.gridRow(MATERIAL, '206323').MEMO, memo().value, memo().marks]).toEqual([null, null, []]);
    runtime.redo();
    expect(memo().value).toBe('表单测试');

    const saved = { ...materialRow('206323', '2550', '25', '聚维酮K30', '75'), entity: MATERIAL };
    saved.values = { ...saved.values, MEMO: '表单测试' };
    const result: CommandResult = {
      requestKey: UUID,
      outcome: 'saved',
      rows: [saved],
      idMap: {},
      prompts: [],
      skipped: [],
      approvals: []
    };
    fake.http.on('POST', '/api/commands', result);
    fake.http.on('POST', '/api/pages/:pageCode/rows/by-keys', { rows: [saved] });
    await runtime.save();
    await runtime.settled();

    const [command] = fake.http.callsTo('POST', '/api/commands');
    expect((command.body as { documents: unknown }).documents).toEqual([MEMO_PATCH]);
    expect(fake.messages).toContainEqual({ kind: 'success', text: '已保存' });
    // 保存后表单照旧开着，显示保存后的值，没有改动标记
    expect(runtime.state.forms[MATERIAL]).toBe('206323');
    expect([memo().value, memo().marks, runtime.state.dirtyCount]).toEqual(['表单测试', [], 0]);
  });

  it('上一条、下一条：按明细表格显示的先后，含新增的行；主表的表单按主表表格', async () => {
    const ctx = await openCostPage();
    const { runtime, material } = ctx;
    await selectRecord(ctx, '2550');
    runtime.openForm(MATERIAL, '206323');

    runtime.stepForm(MATERIAL, 1);
    expect([runtime.state.forms[MATERIAL], material.selected]).toEqual(['206324', ['206324']]);
    runtime.stepForm(MATERIAL, 1);
    expect(formView(runtime, MATERIAL)!.title).toBe('原料/辅料 玉米淀粉');
    // 明细新增一行：排在最后，下一条到它
    await runtime.addRow(MATERIAL);
    const added = material.ids.at(-1)!;
    expect(added).toMatch(/^tmp-/);
    runtime.stepForm(MATERIAL, 1);
    expect(runtime.state.forms[MATERIAL]).toBe(added);
    expect(formView(runtime, MATERIAL)!.title).toBe('原料/辅料 新增的一行（未保存）');
    runtime.stepForm(MATERIAL, -1);
    expect(runtime.state.forms[MATERIAL]).toBe('206325');

    runtime.openForm(MASTER, '2550');
    runtime.stepForm(MASTER, 1);
    expect(runtime.state.forms[MASTER]).toBe('2551');
  });

  it('换单据时明细的表单关上：主表选了 2551，或主表没有选中行明细清空；主表的表单不动', async () => {
    const ctx = await openCostPage();
    const { runtime } = ctx;
    await selectRecord(ctx, '2550');
    runtime.openForm(MASTER, '2550');
    runtime.openForm(MATERIAL, '206323');

    await selectRecord(ctx, '2551');
    expect(runtime.state.forms).toEqual({ [MASTER]: '2550', [MATERIAL]: null });
    expect(formView(runtime, MATERIAL)).toBeNull();

    runtime.openForm(MATERIAL, '206400');
    expect(formView(runtime, MATERIAL)!.title).toBe('原料/辅料 聚维酮K30');
    runtime.onSelection(MASTER, []);
    expect([runtime.state.activeRecord, runtime.state.forms[MATERIAL]]).toEqual([null, null]);
    expect(runtime.state.forms[MASTER]).toBe('2550');
  });
});
