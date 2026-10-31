/**
 * 按单据提交（C02 v10 第 1 节，模拟验证；用户 2026-10-31："我也是要求一单一单的提交啊……100个单据 失败了1个，就全部失败"
 * 是不可以的）：一次保存或一个按钮涉及几张单据时，后端每张单据各自成功或失败，没成功的在命令结果的 `failed` 中。
 * 页面上成功的单据照常刷新、丢弃修改，没成功的单据修改保留、错误定位到行和字段，提示同旧系统
 * （useWorkingSetStore.ts 第 1169–1186 行）：第一行为张数，下面每张没成功的单据一行原因。
 */
import { describe, expect, it } from 'vitest';
import type { CommandResult, DocumentFailure } from '../../src/contracts/command';
import type { ErrorDetail } from '../../src/contracts/errors';
import { approvalDetailSample } from '../../src/contracts/fakes/samples';
import { MASTER, MATERIAL, masterRow, openCostPage, selectRecord } from './support';

const UUID = '7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f';

function detail(extra: Partial<ErrorDetail>): ErrorDetail {
  return {
    message: null,
    entity: null,
    rowKey: null,
    clientRowId: null,
    field: null,
    approvalId: null,
    configType: null,
    configKey: null,
    path: null,
    ...extra
  };
}

function result(rows: CommandResult['rows'], failed: DocumentFailure[]): CommandResult {
  return { requestKey: UUID, outcome: 'saved', rows, idMap: {}, prompts: [], skipped: [], approvals: [], failed };
}

const RULE_REJECTED: DocumentFailure = {
  entity: MASTER,
  rowKey: '2550',
  error: {
    code: 'RULE_REJECTED',
    message: '单价必须大于0',
    details: [detail({ message: '单价必须大于0', entity: MATERIAL, rowKey: '206324', field: 'PRICE' })]
  }
};

describe('按单据提交（C02 v10）', () => {
  it('2550 的硬脂酸镁单价改成 0、2551 的备注改为"已核对"一起保存，2550 被规则拒绝：2551 照常刷新，2550 的修改保留并标出', async () => {
    const ctx = await openCostPage();
    const { runtime, fake } = ctx;
    await selectRecord(ctx, '2550');
    runtime.edit(MATERIAL, '206324', 'PRICE', '0');
    runtime.edit(MASTER, '2551', 'MEMO', '已核对');
    fake.http.on(
      'POST',
      '/api/commands',
      result([{ ...masterRow('2551', '已核对'), entity: MASTER }], [RULE_REJECTED])
    );

    await runtime.save();

    const [command] = fake.http.callsTo('POST', '/api/commands');
    expect((command.body as { documents: unknown[] }).documents).toHaveLength(2); // 仍是一个请求，由后端按单据拆
    expect(runtime.gridRow(MASTER, '2551').MEMO).toBe('已核对');
    expect(runtime.model.buffer.isChanged(MASTER, '2551', 'MEMO')).toBe(false);
    expect(runtime.model.buffer.isChanged(MATERIAL, '206324', 'PRICE')).toBe(true);
    expect(runtime.gridRow(MATERIAL, '206324').PRICE).toBe('0');
    expect(runtime.state.dirtyCount).toBe(1);
    expect(fake.dirty.get('/page/COST_PINGGU')).toBe(true);
    expect(runtime.model.errorsOf(MATERIAL, '206324')).toEqual([{ field: 'PRICE', message: '单价必须大于0' }]);
    expect(fake.messages).toContainEqual({
      kind: 'error',
      text: '保存成功 1 张，失败 1 张\n单据 2550 250mg乙酰唑胺片：单价必须大于0（原料/辅料 硬脂酸镁）'
    });
    expect(fake.messages.some(m => m.text === '已保存')).toBe(false);

    // 改好以后再保存：命令只带 2550
    runtime.edit(MATERIAL, '206324', 'PRICE', '72');
    fake.http.on('POST', '/api/commands', result([], []));
    await runtime.save();
    const second = fake.http.callsTo('POST', '/api/commands')[1];
    expect(second.body).toMatchObject({
      documents: [{ entity: MASTER, master: { op: 'none', rowKey: '2550' } }]
    });
    expect((second.body as { documents: unknown[] }).documents).toHaveLength(1);
  });

  it('2550 在审批 204 中、2551 照常：2551 保存，提示 2550 被哪个审批冻结，并弹出审批 204 的进度', async () => {
    const { runtime, fake } = await openCostPage();
    runtime.edit(MASTER, '2550', 'MEMO', '复核');
    runtime.edit(MASTER, '2551', 'MEMO', '复核');
    const frozen: DocumentFailure = {
      entity: MASTER,
      rowKey: '2550',
      error: {
        code: 'FROZEN_BY_APPROVAL',
        message: '数据已被审批冻结，审批结束前不能修改',
        details: [detail({ message: '单据 2550 已被审批 204 冻结', entity: MASTER, rowKey: '2550', approvalId: '204' })]
      }
    };
    fake.http.on('POST', '/api/commands', result([{ ...masterRow('2551', '复核'), entity: MASTER }], [frozen]));
    fake.http.on('GET', '/api/approvals/:approvalId', { ...approvalDetailSample, approvalId: '204' });

    await runtime.save();

    expect(runtime.gridRow(MASTER, '2551').MEMO).toBe('复核');
    expect(runtime.model.buffer.isChanged(MASTER, '2550', 'MEMO')).toBe(true);
    expect(fake.messages).toContainEqual({
      kind: 'error',
      text: '保存成功 1 张，失败 1 张\n单据 2550 250mg乙酰唑胺片：数据已被审批冻结，审批结束前不能修改（审批 204）'
    });
    expect(runtime.ui.frozen.value?.items.map(i => i.approvalId)).toEqual(['204']);
  });

  it('主表选中 2550、2551 点"同步价格"，2550 被规则拒绝：2551 显示后端的值，提示按按钮名称', async () => {
    const ctx = await openCostPage();
    const { runtime, fake, master } = ctx;
    master.selected = ['2550', '2551'];
    runtime.onSelection(MASTER, ['2550', '2551']);
    fake.http.on(
      'POST',
      '/api/commands',
      result([{ ...masterRow('2551', '同步后'), entity: MASTER }], [RULE_REJECTED])
    );
    const view = runtime.view.value!;
    await runtime.clickButton(view.master, view.master.buttons.find(b => b.action === 'syncPrice')!);

    const [command] = fake.http.callsTo('POST', '/api/commands');
    expect(command.body).toMatchObject({
      params: {
        selectedRows: [
          { entity: MASTER, rowKey: '2550' },
          { entity: MASTER, rowKey: '2551' }
        ]
      }
    });
    expect(runtime.gridRow(MASTER, '2551').MEMO).toBe('同步后');
    // 2550 的明细没有打开过，页面上没有这一行的物料名称，按明细号称呼（同只处理一张单据失败时，failure.ts）
    expect(fake.messages).toContainEqual({
      kind: 'error',
      text: '同步价格：完成 1 张，失败 1 张\n单据 2550 250mg乙酰唑胺片：单价必须大于0（原料/辅料 ID 206324）'
    });
    expect(fake.messages.some(m => m.text === '同步价格已完成')).toBe(false);
  });
});

describe('按单据提交：新建的单据没成功（C02 v10）', () => {
  it('新建的成本单数量填 0 被规则拒绝、2551 照常保存：新建的单据和它的修改留在页面上，错误标在格子上，效果栏照旧显示它的提示', async () => {
    const ctx = await openCostPage();
    const { runtime, fake } = ctx;
    await runtime.addRow(MASTER);
    const added = runtime.model.newMasterRows()[0].id;
    const rejected = {
      kind: 'reject' as const,
      rule: 'R_QTY_GT0',
      message: '数量必须大于0',
      entity: MASTER,
      clientRowId: added,
      field: 'QTY'
    };
    // 预览：新建的这张数量为 0 时给出拒绝提示
    fake.calc.respond(request => ({
      ok: true,
      rows: [],
      effects:
        request.document.master.clientRowId === added && request.document.master.values.QTY === '0' ? [rejected] : []
    }));
    runtime.edit(MASTER, added, 'QTY', '0');
    runtime.edit(MASTER, '2551', 'MEMO', '已核对');
    await runtime.settled();
    expect(runtime.ui.effects.value.map(e => e.message)).toEqual(['数量必须大于0']);
    const failure: DocumentFailure = {
      entity: MASTER,
      clientRowId: added,
      error: {
        code: 'RULE_REJECTED',
        message: '数量必须大于0',
        details: [detail({ message: '数量必须大于0', entity: MASTER, clientRowId: added, field: 'QTY' })]
      }
    };
    fake.http.on('POST', '/api/commands', result([{ ...masterRow('2551', '已核对'), entity: MASTER }], [failure]));

    await runtime.save();

    expect(runtime.gridRow(MASTER, '2551').MEMO).toBe('已核对');
    expect(runtime.model.buffer.isChanged(MASTER, '2551', 'MEMO')).toBe(false);
    expect(runtime.model.buffer.isNew(MASTER, added)).toBe(true);
    expect(runtime.gridRow(MASTER, added).QTY).toBe('0');
    expect(runtime.model.errorsOf(MASTER, added)).toEqual([{ field: 'QTY', message: '数量必须大于0' }]);
    expect(fake.messages).toContainEqual({
      kind: 'error',
      text: '保存成功 1 张，失败 1 张\n单据 新增的一张：数量必须大于0'
    });
    expect(runtime.ui.effects.value.map(e => e.message)).toEqual(['数量必须大于0']);
  });
});
