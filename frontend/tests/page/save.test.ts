/**
 * T-FP-3（模拟验证）：保存、局部刷新、失败保留修改、提交审批后的显示、冻结时弹出审批进度、未保存修改的页签标记。
 * 用 contracts 的 C09 模拟实现和 FakeGrid（support.ts）。
 */
import { describe, expect, it } from 'vitest';
import type { CommandResult } from '../../src/contracts/command';
import { PlatformError } from '../../src/contracts/errors';
import type { RecordResponse } from '../../src/contracts/http';
import { approvalDetailSample } from '../../src/contracts/fakes/samples';
import { MASTER, MATERIAL, RECORDS, masterRow, materialRow, openCostPage, selectRecord } from './support';

const UUID = '7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f';

function saved(rows: CommandResult['rows'], extra: Partial<CommandResult> = {}): CommandResult {
  return { requestKey: UUID, outcome: 'saved', rows, idMap: {}, prompts: [], skipped: [], approvals: [], ...extra };
}

describe('保存（FP-06）', () => {
  it('E01：改 200680 的备注为"测试"并保存：命令只含这一格，成功后只更新这一行，清空编辑缓冲', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master } = ctx;
    runtime.model.registerMasterRows([masterRow('200680', null)]);
    master.ids.push('200680');
    expect(runtime.edit(MASTER, '200680', 'MEMO', '测试')).toBe(true);
    expect(runtime.state.dirtyCount).toBe(1);
    expect(fake.dirty.get('/page/COST_PINGGU')).toBe(true);
    // 结果中另有一行 2551，值与页面上相同：逐行比对后不更新
    fake.http.on(
      'POST',
      '/api/commands',
      saved([
        { ...masterRow('200680', '测试'), entity: MASTER },
        { ...masterRow('2551', '原备注'), entity: MASTER }
      ])
    );

    const result = await runtime.save();

    const [command] = fake.http.callsTo('POST', '/api/commands');
    expect(command.body).toMatchObject({
      page: MASTER,
      operation: 'COST_PINGGU.save',
      documents: [
        { entity: MASTER, master: { op: 'modify', rowKey: '200680', changes: { MEMO: '测试' } }, details: [] }
      ],
      params: {}
    });
    expect((command.body as { requestKey: string }).requestKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(result?.outcome).toBe('saved');
    expect(master.updated.at(-1)).toEqual(['200680']);
    expect(runtime.gridRow(MASTER, '200680').MEMO).toBe('测试');
    expect(runtime.state.dirtyCount).toBe(0);
    expect(runtime.state.saving).toBe(false);
    expect(fake.dirty.get('/page/COST_PINGGU')).toBe(false);
    expect(fake.messages).toContainEqual({ kind: 'success', text: '已保存' });
  });

  it('E01：把 200680 的备注从"测试"改回空马上保存，预览补读单据的响应晚于保存结果到达：仍显示保存后的空值', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master } = ctx;
    runtime.model.registerMasterRows([masterRow('200680', '测试')]);
    master.ids.push('200680');
    // 第一次读单据：请求在保存提交前发出，响应等保存结果到达后才返回，内容是保存前的"测试"
    let recordRequested!: () => void;
    const requested = new Promise<void>(resolve => {
      recordRequested = resolve;
    });
    let returnStale!: () => void;
    const stale = new Promise<RecordResponse>(resolve => {
      returnStale = () => resolve({ master: masterRow('200680', '测试'), details: { [MATERIAL]: [] } });
    });
    let reads = 0;
    fake.http.on('GET', '/api/pages/:pageCode/records/:recordKey', () => {
      reads += 1;
      if (reads === 1) {
        recordRequested();
        return stale;
      }
      return { master: masterRow('200680', null), details: { [MATERIAL]: [] } };
    });
    let returnSaved!: () => void;
    const savedResult = new Promise<CommandResult>(resolve => {
      returnSaved = () => resolve(saved([{ ...masterRow('200680', null), entity: MASTER }]));
    });
    fake.http.on('POST', '/api/commands', () => savedResult);

    expect(runtime.edit(MASTER, '200680', 'MEMO', null)).toBe(true);
    const saving = runtime.save();
    await requested;
    returnSaved();
    await saving;
    returnStale();
    await runtime.settled();

    expect(runtime.gridRow(MASTER, '200680').MEMO).toBeNull();
    expect(runtime.model.buffer.committed(MASTER, '200680')?.MEMO).toBeNull();
    // 保存结果到达后重新读了一次
    expect(reads).toBe(2);
  });

  it('保存期间整页只读，单元格不能编辑', async () => {
    const { runtime, fake } = await openCostPage();
    runtime.edit(MASTER, '2550', 'MEMO', '测试');
    let release!: (value: CommandResult) => void;
    fake.http.on('POST', '/api/commands', () => new Promise<CommandResult>(resolve => (release = resolve)));
    const saving = runtime.save();
    await Promise.resolve();
    await Promise.resolve();
    expect(runtime.state.saving).toBe(true);
    expect(runtime.cellEditable(MASTER, '2551', 'MEMO')).toBe(false);
    expect(runtime.edit(MASTER, '2551', 'MEMO', 'x')).toBe(false);
    release(saved([{ ...masterRow('2550', '测试'), entity: MASTER }]));
    await saving;
    expect(runtime.cellEditable(MASTER, '2551', 'MEMO')).toBe(true);
  });

  it('新增明细保存后换成正式主键，表格行标识（clientRowId）不变；计算带出的主表行一起更新', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master, material } = ctx;
    await selectRecord(ctx, '2550');
    await runtime.addRow(MATERIAL);
    const clientRowId = material.ids.at(-1)!;
    expect(clientRowId).toMatch(/^tmp-/);
    runtime.edit(MATERIAL, clientRowId, 'PRICE', '3.50');
    runtime.edit(MATERIAL, clientRowId, 'USAGE', '1');
    fake.http.on(
      'POST',
      '/api/commands',
      saved(
        [
          {
            ...masterRow('2550', null),
            entity: MASTER,
            values: { ...masterRow('2550', null).values, TOTAL_COST: '13.0100' }
          },
          { ...materialRow('7001', '2550', '0', '', '3.50'), entity: MATERIAL, clientRowId }
        ],
        { idMap: { [clientRowId]: '7001' } }
      )
    );
    await runtime.save();
    // 新增行的命令：没有配置默认值的数值字段为 0（C06 第 2 节），不带主键、关联字段和计算字段
    const body = fake.http.callsTo('POST', '/api/commands')[0].body as { documents: Array<{ details: unknown[] }> };
    expect(body.documents[0].details).toEqual([
      { entity: MATERIAL, op: 'add', clientRowId, values: { GOODSID: '0', PRICE: '3.50', USAGE: '1' } }
    ]);
    expect(material.ids).toContain(clientRowId);
    expect(material.updatedIds).toContain(clientRowId);
    expect(runtime.gridRow(MATERIAL, clientRowId)).toMatchObject({ DTLID: '7001', PRICE: '3.50', __id: clientRowId });
    expect(master.updatedIds).toContain('2550');
    expect(runtime.model.buffer.isNew(MATERIAL, clientRowId)).toBe(false);
    // 再次编辑这一行时，按正式主键修改
    runtime.edit(MATERIAL, clientRowId, 'MEMO', '新');
    expect(runtime.model.buffer.documents()[0].details[0]).toMatchObject({ op: 'modify', rowKey: '7001' });
  });

  it('结果中缺的行按主键补查', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, material } = ctx;
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206324', 'MEMO', '测试');
    fake.http.on('POST', '/api/commands', saved([]));
    fake.http.on('POST', '/api/pages/:pageCode/rows/by-keys', {
      rows: [
        {
          ...materialRow('206324', '2550', '115', '硬脂酸镁', '70'),
          values: { ...materialRow('206324', '2550', '115', '硬脂酸镁', '70').values, MEMO: '测试' }
        }
      ]
    });
    await runtime.save();
    expect(fake.http.callsTo('POST', '/api/pages/:pageCode/rows/by-keys')[0].body).toEqual({
      entity: MATERIAL,
      rowKeys: ['206324']
    });
    expect(material.updatedIds).toContain('206324');
    expect(runtime.gridRow(MATERIAL, '206324').MEMO).toBe('测试');
  });

  it('失败时保留全部修改，按错误明细定位到行和字段，不自动重发', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, material } = ctx;
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206323', 'PRICE', '80');
    runtime.edit(MASTER, '2551', 'MEMO', '改');
    const detail = {
      message: '单价超出范围',
      entity: MATERIAL,
      rowKey: '206323',
      clientRowId: null,
      field: 'PRICE',
      approvalId: null,
      configType: null,
      configKey: null,
      path: null
    };
    fake.http.fail('POST', '/api/commands', new PlatformError(422, 'RULE_REJECTED', '规则拒绝', [detail]));
    expect(await runtime.save()).toBeNull();
    expect(fake.http.callsTo('POST', '/api/commands')).toHaveLength(1);
    expect(runtime.state.saving).toBe(false);
    expect(runtime.state.dirtyCount).toBe(2);
    expect(runtime.model.errorsOf(MATERIAL, '206323')).toEqual([{ field: 'PRICE', message: '单价超出范围' }]);
    expect(material.updatedIds).toContain('206323');
    // 错误的文字与明细不同时放在前面；明细指出是原料/辅料的哪一行（物料名称）
    expect(fake.messages.at(-1)).toEqual({ kind: 'error', text: '规则拒绝：单价超出范围（原料/辅料 聚维酮K30）' });
  });

  it('成本单 2919 那样被同一条规则拒绝两行：同样的话只说一次，列出两行的物料名称；主表行用单据号和产品名称', async () => {
    const ctx = await openCostPage();
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206324', 'PRICE', '72');
    const detail = (entity: string, rowKey: string, field: string) => ({
      message: '每片含量必填且必须大于0',
      entity,
      rowKey,
      clientRowId: null,
      field,
      approvalId: null,
      configType: null,
      configKey: null,
      path: null
    });
    fake.http.fail(
      'POST',
      '/api/commands',
      new PlatformError(422, 'RULE_REJECTED', '每片含量必填且必须大于0', [
        detail(MATERIAL, '206323', 'USAGE'),
        detail(MATERIAL, '206324', 'USAGE')
      ])
    );
    await runtime.save();
    expect(fake.messages.at(-1)).toEqual({
      kind: 'error',
      text: '每片含量必填且必须大于0（原料/辅料 聚维酮K30、硬脂酸镁）'
    });
    // 两种文字、主表和明细都有：按文字分组，主表行写单据号和产品名称
    fake.http.fail(
      'POST',
      '/api/commands',
      new PlatformError(422, 'RULE_REJECTED', '规则拒绝', [
        { ...detail(MASTER, '2550', 'MEMO'), message: '备注必填' },
        detail(MATERIAL, '206323', 'USAGE'),
        detail(MATERIAL, '206323', 'PRICE')
      ])
    );
    await runtime.save();
    expect(fake.messages.at(-1)).toEqual({
      kind: 'error',
      text: '规则拒绝：备注必填（单据 2550 250mg乙酰唑胺片）；每片含量必填且必须大于0（原料/辅料 聚维酮K30）'
    });
  });

  it('没有收到响应时同样保留修改，提示检查网络', async () => {
    const { runtime, fake } = await openCostPage();
    runtime.edit(MASTER, '2550', 'MEMO', '测试');
    fake.http.fail('POST', '/api/commands', new PlatformError(0, null, '没有收到服务器的响应，请检查网络后重试'));
    await runtime.save();
    expect(runtime.state.dirtyCount).toBe(1);
    expect(fake.messages.at(-1)?.kind).toBe('error');
  });
});

describe('提交审批与冻结（FP-07、FP-16）', () => {
  it('E20：D 的明细改价提交审批、E 的备注写入：D 整张显示正式数据并冻结，E 按写入结果刷新', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master, material } = ctx;
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206323', 'PRICE', '80');
    await runtime.addRow(MATERIAL);
    const added = material.ids.at(-1)!;
    runtime.edit(MASTER, '2551', 'MEMO', '已核对');
    fake.http.on(
      'POST',
      '/api/commands',
      saved(
        [
          {
            ...materialRow('206323', '2550', '25', '聚维酮K30', '75'),
            entity: MATERIAL,
            frozen: { approvalId: '203' }
          },
          { ...masterRow('2551', '已核对'), entity: MASTER }
        ],
        {
          outcome: 'approvalSubmitted',
          idMap: { [added]: '7002' },
          approvals: [
            {
              approvalId: '203',
              document: { entity: MASTER, recordKey: '2550' },
              status: 'pending',
              level: 1,
              flows: ['COST_TO_GOODS']
            }
          ]
        }
      )
    );
    await runtime.save();
    expect(material.ids).not.toContain(added);
    expect(runtime.gridRow(MATERIAL, '206323').PRICE).toBe('75');
    expect(runtime.frozenBy(MATERIAL, '206324')).toBe('203');
    expect(runtime.frozenBy(MASTER, '2550')).toBe('203');
    expect(runtime.cellEditable(MATERIAL, '206324', 'MEMO')).toBe(false);
    expect(runtime.gridRow(MASTER, '2551').MEMO).toBe('已核对');
    expect(master.updatedIds).toEqual(expect.arrayContaining(['2550', '2551']));
    expect(runtime.state.dirtyCount).toBe(0);
    expect(fake.messages).toContainEqual({ kind: 'warning', text: '单据 2550 已提交审批，审批结束前显示正式数据' });
  });

  it('成本单 2550 被审批 203 锁定：改单价、删除明细、新增明细都不进入编辑，弹出审批 203 的进度', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, material } = ctx;
    // 列表和单据加载中，2550 的行都带 frozen（C09 DataRow）
    runtime.model.registerMasterRows([masterRow('2550', null, '203')]);
    fake.http.on('GET', '/api/pages/:pageCode/records/:recordKey', {
      ...RECORDS['2550'],
      master: masterRow('2550', null, '203')
    });
    fake.http.on('GET', '/api/approvals/:approvalId', approvalDetailSample);
    await selectRecord(ctx, '2550');
    expect(runtime.edit(MATERIAL, '206323', 'PRICE', '80')).toBe(false);
    material.select('206324');
    runtime.deleteSelected(MATERIAL);
    await runtime.addRow(MATERIAL);
    await Promise.resolve();
    expect(runtime.model.buffer.size).toBe(0);
    expect(material.ids).toEqual(['206323', '206324', '206325']);
    expect(fake.http.callsTo('GET', '/api/approvals/:approvalId').map(c => c.params.approvalId)).toEqual([
      '203',
      '203',
      '203'
    ]);
    const progress = runtime.ui.frozen.value!;
    expect(progress.items[0]).toMatchObject({ approvalId: '203', pageTitle: '物料清单及成本', currentLevel: 1 });
    expect(progress.items[0].steps.map(s => [s.level, s.node, s.status])).toEqual([
      [1, '管理员审批', 'pending'],
      [1, '采购复核', 'pending'],
      [2, '管理员复核', 'upcoming']
    ]);
  });

  it('页面加载后 2551 才被锁定：保存返回 FROZEN_BY_APPROVAL，弹出锁定它的审批的进度，修改保留', async () => {
    const { runtime, fake } = await openCostPage();
    runtime.edit(MASTER, '2551', 'MEMO', '改');
    const detail = {
      message: '单据 2551 已被审批 204 锁定',
      entity: MASTER,
      rowKey: '2551',
      clientRowId: null,
      field: null,
      approvalId: '204',
      configType: null,
      configKey: null,
      path: null
    };
    fake.http.fail('POST', '/api/commands', new PlatformError(409, 'FROZEN_BY_APPROVAL', '单据已被审批锁定', [detail]));
    fake.http.on('GET', '/api/approvals/:approvalId', { ...approvalDetailSample, approvalId: '204' });
    await runtime.save();
    expect(fake.http.callsTo('GET', '/api/approvals/:approvalId').map(c => c.params.approvalId)).toEqual(['204']);
    expect(runtime.ui.frozen.value?.items.map(i => i.approvalId)).toEqual(['204']);
    expect(runtime.state.dirtyCount).toBe(1);
  });
});
