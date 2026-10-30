/**
 * T-FP-2 的按钮（FP-14）、T-FP-3 的预览（FP-05）、T-FP-4 的配置原地替换（FP-09）和个人列配置（FP-11），模拟验证。
 */
import { describe, expect, it } from 'vitest';
import type { CommandResult } from '../../src/contracts/command';
import { PlatformError } from '../../src/contracts/errors';
import type { EvaluationRequest, EvaluationResult } from '../../src/contracts/rules';
import { serverMessageSamples } from '../../src/contracts/fakes/samples';
import { MASTER, MATERIAL, costView, masterRow, materialRow, openCostPage, selectRecord } from './support';

const UUID = '7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f';

/** 按钮执行后按计算规则重算的主表行：总成本换成 `total` */
const recalculated = (docid: string, memo: string | null, total: string) => {
  const row = masterRow(docid, memo);
  return { ...row, values: { ...row.values, TOTAL_COST: total } };
};

describe('按钮（FP-14）', () => {
  it('只按 systemButtons 和区域 buttons 显示；没有选中行时删除、复制和 requiresSelection 的按钮不可用，新增可用', async () => {
    const ctx = await openCostPage();
    const { runtime } = ctx;
    const view = runtime.view.value!;
    const labels = runtime.regionButtons(view.master).map(b => b.label);
    expect(labels).toEqual(['新增', '复制', '删除', '同步价格', '保存列配置']);
    const enabled = () =>
      Object.fromEntries(runtime.regionButtons(view.master).map(b => [b.label, runtime.buttonEnabled(view.master, b)]));
    expect(enabled()).toEqual({ 新增: true, 复制: false, 删除: false, 同步价格: false, 保存列配置: true });
    ctx.master.select('2550');
    runtime.onSelection(MASTER, ['2550']);
    expect(enabled()).toEqual({ 新增: true, 复制: true, 删除: true, 同步价格: true, 保存列配置: true });
  });

  it('角色没有主表的新增、删除时区域 buttons 里没有这两个按钮，不显示；没有 save 时整页只读', async () => {
    const view = costView();
    view.master.buttons = view.master.buttons.filter(b => b.action !== 'addRow' && b.action !== 'deleteRow');
    view.systemButtons = ['advancedSearch'];
    const { runtime } = await openCostPage(view);
    expect(runtime.regionButtons(view.master).map(b => b.label)).toEqual(['复制', '同步价格', '保存列配置']);
    runtime.onSelection(MASTER, ['2550']);
    // 复制：没有保存时不可用
    expect(runtime.buttonEnabled(view.master, view.master.buttons[0])).toBe(false);
    expect(runtime.cellEditable(MASTER, '2550', 'MEMO')).toBe(false);
    expect(runtime.edit(MASTER, '2550', 'MEMO', 'x')).toBe(false);
  });

  it('成本单 D（2550）明细改了单价、E（2551）也改了没保存，选中 D 点"同步价格"：不提示保存，命令只带 D 的主键；成功后 D 受影响的行显示后端的值，E 的修改仍在', async () => {
    const ctx = await openCostPage();
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206323', 'PRICE', '80');
    runtime.edit(MATERIAL, '206324', 'MEMO', '换料');
    runtime.edit(MASTER, '2551', 'MEMO', 'E 的修改');
    const result: CommandResult = {
      requestKey: UUID,
      outcome: 'saved',
      rows: [{ ...materialRow('206323', '2550', '25', '聚维酮K30', '82'), entity: MATERIAL }],
      idMap: {},
      prompts: [],
      skipped: [],
      approvals: []
    };
    fake.http.on('POST', '/api/commands', result);
    const view = runtime.view.value!;
    const button = view.master.buttons.find(b => b.action === 'syncPrice')!;
    await runtime.clickButton(view.master, button);
    const [command] = fake.http.callsTo('POST', '/api/commands');
    expect(command.body).toMatchObject({
      page: MASTER,
      operation: 'COST_PINGGU.syncPrice',
      documents: [],
      params: { selectedRows: [{ entity: MASTER, rowKey: '2550' }] }
    });
    expect(fake.messages.some(m => m.text.includes('保存'))).toBe(false);
    expect(runtime.gridRow(MATERIAL, '206323').PRICE).toBe('82');
    expect(runtime.model.buffer.isChanged(MATERIAL, '206323', 'PRICE')).toBe(false);
    expect(runtime.model.buffer.isChanged(MATERIAL, '206324', 'MEMO')).toBe(true);
    expect(runtime.model.buffer.isChanged(MASTER, '2551', 'MEMO')).toBe(true);
    expect(ctx.material.updatedIds).toContain('206323');
  });

  it('"同步采购价"的 requiresSelection 为 false：没有选中行也能点，selectedRows 为空数组；成功后结果中的行显示后端的值', async () => {
    const view = costView();
    view.master.buttons = view.master.buttons.map(b =>
      b.action === 'syncPrice' ? { ...b, label: '同步采购价', requiresSelection: false } : b
    );
    const ctx = await openCostPage(view);
    const { runtime, fake } = ctx;
    const button = view.master.buttons.find(b => b.action === 'syncPrice')!;
    expect(runtime.buttonEnabled(view.master, button)).toBe(true);
    const result: CommandResult = {
      requestKey: UUID,
      outcome: 'saved',
      rows: [
        { ...materialRow('206400', '2551', '25', '聚维酮K30', '45'), entity: MATERIAL },
        { ...recalculated('2551', '原备注', '12.5'), entity: MASTER }
      ],
      idMap: {},
      prompts: [],
      skipped: [],
      approvals: []
    };
    fake.http.on('POST', '/api/commands', result);
    await runtime.clickButton(view.master, button);
    const [command] = fake.http.callsTo('POST', '/api/commands');
    expect(command.body).toMatchObject({
      operation: 'COST_PINGGU.syncPrice',
      documents: [],
      params: { selectedRows: [] }
    });
    expect(runtime.gridRow(MASTER, '2551').TOTAL_COST).toBe('12.5');
    expect(ctx.master.updatedIds).toContain('2551');
    expect(fake.messages.at(-1)).toEqual({ kind: 'success', text: '同步采购价已完成' });
  });

  it('业务按钮没有改到数据（outcome 为 unchanged）：按按钮名称说明，不说"没有需要保存的修改"', async () => {
    const view = costView();
    view.master.buttons = view.master.buttons.map(b =>
      b.action === 'syncPrice' ? { ...b, label: '由BOM生成明细', requiresSelection: false } : b
    );
    const { runtime, fake } = await openCostPage(view);
    const unchanged: CommandResult = {
      requestKey: UUID,
      outcome: 'unchanged',
      rows: [],
      idMap: {},
      prompts: [],
      skipped: [],
      approvals: []
    };
    fake.http.on('POST', '/api/commands', unchanged);
    await runtime.clickButton(view.master, view.master.buttons.find(b => b.action === 'syncPrice')!);
    expect(fake.messages.at(-1)).toEqual({ kind: 'success', text: '由BOM生成明细：没有需要修改的数据' });
  });

  it('选中成本单 2550 点"由BOM生成明细"：删掉的明细从明细区去掉，后端新增的明细出现在明细区，主表显示重算后的值', async () => {
    const view = costView();
    view.master.buttons = [
      ...view.master.buttons,
      {
        key: 'master:generateFromBom',
        action: 'generateFromBom',
        label: '由BOM生成明细',
        operation: 'COST_PINGGU.generateFromBom',
        requiresSelection: true
      }
    ];
    const ctx = await openCostPage(view);
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    expect(ctx.material.ids).toEqual(['206323', '206324', '206325']);
    // 后端新增的行带着后端生成的 clientRowId
    const added = (row: ReturnType<typeof materialRow>) => ({
      ...row,
      entity: MATERIAL,
      clientRowId: `tmp-00000000-0000-5000-8000-000000${row.rowKey}`
    });
    const result: CommandResult = {
      requestKey: UUID,
      outcome: 'saved',
      rows: [
        { entity: MATERIAL, rowKey: '206323', deleted: true },
        { entity: MATERIAL, rowKey: '206324', deleted: true },
        { entity: MATERIAL, rowKey: '206325', deleted: true },
        added(materialRow('208500', '2550', '115', '硬脂酸镁', '75')),
        added(materialRow('208501', '2550', '9631', '聚维酮K30', '45')),
        { ...recalculated('2550', null, '20.1'), entity: MASTER }
      ],
      idMap: {},
      prompts: [],
      skipped: [],
      approvals: []
    };
    fake.http.on('POST', '/api/commands', result);
    await runtime.clickButton(view.master, view.master.buttons.find(b => b.action === 'generateFromBom')!);
    const [command] = fake.http.callsTo('POST', '/api/commands');
    expect(command.body).toMatchObject({ params: { selectedRows: [{ entity: MASTER, rowKey: '2550' }] } });
    expect(ctx.material.ids).toEqual(['208500', '208501']);
    expect(runtime.gridRow(MATERIAL, '208500')).toMatchObject({ GOODSNAME: '硬脂酸镁', PRICE: '75', DOCID: '2550' });
    expect(runtime.model.buffer.recordOf(MATERIAL, '208501')).toBe('2550');
    expect(runtime.gridRow(MASTER, '2550').TOTAL_COST).toBe('20.1');
  });

  it('按钮命令失败时编辑缓冲不变', async () => {
    const ctx = await openCostPage();
    const { runtime, fake } = ctx;
    ctx.master.select('2550');
    runtime.onSelection(MASTER, ['2550']);
    runtime.edit(MASTER, '2550', 'MEMO', '改');
    const before = runtime.model.buffer.snapshot();
    fake.http.fail('POST', '/api/commands', new PlatformError(409, 'ROW_NOT_FOUND', '选中的行已被删除'));
    const view = runtime.view.value!;
    await runtime.clickButton(view.master, view.master.buttons.find(b => b.action === 'syncPrice')!);
    expect(runtime.model.buffer.snapshot()).toEqual(before);
    expect(fake.messages.at(-1)).toEqual({ kind: 'error', text: '选中的行已被删除' });
  });
});

describe('预览（FP-05）', () => {
  it('编辑后按 preview 阶段求值，old 取已提交值；只刷新结果中有变化的行', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master, material } = ctx;
    await selectRecord(ctx, '2550');
    fake.calc.respond(
      (request: EvaluationRequest): EvaluationResult => ({
        ok: true,
        rows: [
          {
            entity: MASTER,
            rowKey: '2550',
            computed: { TOTAL_COST: '13.0507' },
            fields: {},
            style: { row: null, cells: {} }
          },
          {
            entity: MATERIAL,
            rowKey: '206323',
            computed: { AMOUNT: request.document.details[MATERIAL][0].values.PRICE === '80' ? '800' : '750' },
            fields: {},
            style: { row: null, cells: {} }
          }
        ],
        effects: [
          {
            kind: 'prompt',
            rule: 'R_MARGIN_LOW',
            message: '毛利率低于 5%',
            entity: MASTER,
            rowKey: '2550',
            field: 'TOTAL_COST'
          }
        ]
      })
    );
    material.updated.length = 0;
    runtime.edit(MATERIAL, '206323', 'PRICE', '80');
    await runtime.settled();
    // 页面加载、选中单据时的显示求值（purpose display，FP-18）在前面，这里只看编辑后的预览
    const [request] = fake.calc.requests.filter(r => r.purpose === 'operation');
    expect(request).toMatchObject({
      purpose: 'operation',
      phase: 'preview',
      page: MASTER,
      operation: 'COST_PINGGU.save'
    });
    expect(request.context).toEqual({
      userId: '1',
      departmentId: '10',
      role: 'COST_ACCOUNTANT',
      today: '2026-10-29',
      origin: 'user'
    });
    expect(request.document.details[MATERIAL][0]).toMatchObject({ rowKey: '206323', old: { PRICE: '75' } });
    expect(request.changed).toEqual([{ entity: MATERIAL, rowKey: '206323', op: 'modify', fields: ['PRICE'] }]);
    expect(fake.http.callsTo('GET', '/api/rules-packs/:packId/:version')).toHaveLength(1);
    expect(runtime.gridRow(MASTER, '2550').TOTAL_COST).toBe('13.0507');
    expect(runtime.gridRow(MATERIAL, '206323').AMOUNT).toBe('800');
    expect(runtime.model.isCalcChanged(MATERIAL, '206323', 'AMOUNT')).toBe(true);
    expect(master.updatedIds).toContain('2550');
    expect(material.updatedIds.filter(id => id !== '206323')).toEqual([]);
    expect(runtime.ui.effects.value.map(e => e.message)).toEqual(['毛利率低于 5%']);
    // 预览只用于显示：命令中不带计算字段
    expect(runtime.model.buffer.documents()[0].details[0]).toEqual({
      entity: MATERIAL,
      op: 'modify',
      rowKey: '206323',
      changes: { PRICE: '80' }
    });
  });

  it('计算 Worker 不可用时照常编辑和保存，提示预览不可用', async () => {
    const { runtime, fake } = await openCostPage();
    // Worker 不可用：之后的每次求值都失败（编辑时先加载单据，单据的显示求值和预览都要经 Worker，FP-18）
    fake.calc.respond(() => {
      throw Object.assign(new Error('WASM 加载失败'), { code: 'EVAL_FAILED' });
    });
    runtime.edit(MASTER, '2550', 'QTY', '12');
    await runtime.settled();
    expect(runtime.state.previewError).toBe('本地预览不可用：WASM 加载失败');
    expect(runtime.state.dirtyCount).toBe(1);
  });
});

describe('配置原地替换（FP-09）', () => {
  it('收到 config.changed 后以后台请求重新读取页面视图，原地替换；选中行、展开的表单和正在编辑的值不变', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master } = ctx;
    await selectRecord(ctx, '2550');
    runtime.openForm('2550');
    runtime.edit(MASTER, '2550', 'MEMO', '正在输入');
    const changed = costView();
    changed.version = 14;
    changed.master.fields = changed.master.fields.map(f => (f.name === 'QTY' ? { ...f, editable: false } : f));
    changed.rulesPack = { packId: MASTER, version: 8 };
    fake.http.on('GET', '/api/pages/:pageCode/view', changed);
    const refreshed = master.refreshed;
    fake.realtime.push(serverMessageSamples[0]);
    await new Promise(resolve => setTimeout(resolve, 0));
    await runtime.settled();
    const viewCalls = fake.http.callsTo('GET', '/api/pages/:pageCode/view');
    expect(viewCalls.at(-1)?.options?.background).toBe(true);
    expect(runtime.view.value?.version).toBe(14);
    expect(runtime.state.viewVersion).toBe(1);
    expect(runtime.cellEditable(MASTER, '2550', 'QTY')).toBe(false);
    expect(runtime.gridRow(MASTER, '2550').MEMO).toBe('正在输入');
    expect(runtime.state.formRecord).toBe('2550');
    expect(runtime.state.activeRecord).toBe('2550');
    expect(master.selected).toEqual(['2550']);
    expect(master.refreshed).toBeGreaterThan(refreshed);
    const packs = fake.http.callsTo('GET', '/api/rules-packs/:packId/:version');
    expect(packs.at(-1)).toMatchObject({ path: '/api/rules-packs/COST_PINGGU/8', options: { background: true } });
    expect(fake.realtime.sent[0]).toEqual({ type: 'subscribe', pages: [MASTER] });
  });

  it('管理员把数量 QTY 设为不显示再改回：表格换上新的列后按页面视图重排（与刷新后相同），QTY 回到备注之后', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master, material } = ctx;
    const push = async (view: ReturnType<typeof costView>) => {
      fake.http.on('GET', '/api/pages/:pageCode/view', view);
      // 每次配置变更是一条新事件（同一 eventId 的事件只处理一次）
      const eventId = `1f2e3d4c-5b6a-4978-8695-a4b3c2d1e0${String(view.version).padStart(2, '0')}`;
      fake.realtime.push({ ...serverMessageSamples[0], eventId } as (typeof serverMessageSamples)[0]);
      await new Promise(resolve => setTimeout(resolve, 0));
      await runtime.settled();
    };
    const hidden = costView();
    hidden.version = 14;
    hidden.master.fields = hidden.master.fields.map(f => (f.name === 'QTY' ? { ...f, visible: false } : f));
    await push(hidden);
    runtime.columnsLoaded(MASTER);
    expect(master.ordered.at(-1)).toEqual(['DOCID', 'GOODSNAME', 'MEMO', 'TOTAL_COST', 'CREATE_BY', 'STATUS']);
    await push({ ...costView(), version: 15 });
    // 表格还没换上新的列时不排；换上之后排一次（AG Grid 的 maintainColumnOrder 原来把 QTY 放到最右边）
    expect(master.ordered).toHaveLength(1);
    runtime.columnsLoaded(MASTER);
    runtime.columnsLoaded(MATERIAL);
    expect(master.ordered.at(-1)).toEqual(['DOCID', 'GOODSNAME', 'MEMO', 'QTY', 'TOTAL_COST', 'CREATE_BY', 'STATUS']);
    expect(material.ordered.at(-1)).toEqual(['DTLID', 'GOODSID', 'GOODSNAME', 'PRICE', 'USAGE', 'AMOUNT', 'MEMO']);
    // 之后表格再换列（例如字典加载后）不再重排，用户在页面上拖过的先后不变
    runtime.columnsLoaded(MASTER);
    expect(master.ordered).toHaveLength(2);
  });

  it('有个人列配置时：个人配置中的列按个人配置，重新显示的列按页面视图的先后排在后面（与刷新后相同）', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master } = ctx;
    // 已保存的个人配置把备注拖到最前面（FORM 是页面视图中不可见的字段，不参与）
    runtime.personal = {
      grids: {
        master: {
          columns: [
            { field: 'MEMO', width: 200, pinned: null, hide: false },
            { field: 'FORM', width: 80, pinned: null, hide: false }
          ]
        }
      }
    };
    fake.http.on('GET', '/api/pages/:pageCode/view', { ...costView(), version: 14 });
    fake.realtime.push(serverMessageSamples[0]);
    await new Promise(resolve => setTimeout(resolve, 0));
    await runtime.settled();
    runtime.columnsLoaded(MASTER);
    expect(master.ordered.at(-1)).toEqual(['MEMO', 'DOCID', 'GOODSNAME', 'QTY', 'TOTAL_COST', 'CREATE_BY', 'STATUS']);
  });
});

describe('字典', () => {
  it('字段有 dictType 时按 GET /api/dicts/{dictType} 读取一次，显示标签、保存值', async () => {
    const view = costView();
    view.master.fields = view.master.fields.map(f =>
      f.name === 'STATUS' ? { ...f, dictType: 'COST_STATUS', default: null } : f
    );
    const ctx = await openCostPage(view, fake =>
      fake.http.on('GET', '/api/dicts/:dictType', {
        items: [
          { value: '1', label: '草稿' },
          { value: '2', label: '评估中' }
        ]
      })
    );
    const { runtime, fake } = ctx;
    await new Promise(resolve => {
      setTimeout(resolve, 0);
    });
    expect(fake.http.callsTo('GET', '/api/dicts/:dictType').map(c => c.params.dictType)).toEqual(['COST_STATUS']);
    expect([...runtime.dicts.get('COST_STATUS')!]).toEqual([
      ['1', '草稿'],
      ['2', '评估中']
    ]);
    runtime.edit(MASTER, '2550', 'STATUS', '2');
    expect(runtime.model.buffer.documents()[0].master).toEqual({
      op: 'modify',
      rowKey: '2550',
      changes: { STATUS: '2' }
    });
  });
});

describe('个人列配置（FP-11）', () => {
  it('上层隐藏的列不能被个人配置设为显示；保存只提交改变的部分', async () => {
    const view = costView();
    const ctx = await openCostPage(view);
    const { runtime, fake } = ctx;
    // 个人配置中有页面视图不可见的 FORM：不应用
    runtime.personal = {
      grids: {
        master: {
          columns: [
            { field: 'FORM', width: 80, pinned: null, hide: false },
            { field: 'MEMO', width: 300, pinned: null, hide: false }
          ]
        }
      }
    };
    const grid = new (ctx.master.constructor as new () => typeof ctx.master)();
    runtime.attach(MASTER, grid);
    expect(grid.applied).toEqual([{ field: 'MEMO', width: 300, pinned: null, hide: false }]);
    // 主表改了列宽，明细没改
    runtime.personal = {};
    grid.state = view.master.fields
      .filter(f => f.visible)
      .map(f => ({ field: f.name, width: f.name === 'MEMO' ? 260 : f.width, pinned: f.pinned, hide: false }));
    ctx.material.state = view.details[0].fields
      .filter(f => f.visible)
      .map(f => ({ field: f.name, width: f.width, pinned: f.pinned, hide: false }));
    await runtime.saveGridConfig();
    const [put] = fake.http.callsTo('PUT', '/api/pages/:pageCode/personal');
    expect(put.body).toEqual({ grids: { master: { columns: grid.state } } });
    expect(fake.messages.at(-1)).toEqual({ kind: 'success', text: '列配置已保存' });
  });

  it('切换明细显示方式存进个人配置', async () => {
    const { runtime, fake } = await openCostPage();
    await runtime.setDetailMode('stack');
    expect(fake.http.callsTo('PUT', '/api/pages/:pageCode/personal')[0].body).toEqual({ detailMode: 'stack' });
    expect(runtime.state.detailMode).toBe('stack');
  });
});
