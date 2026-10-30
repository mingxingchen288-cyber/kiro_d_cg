/**
 * T-AZ-2（模拟验证）：区域的新增、删除、修改（C05 v8 `canModify`、C06 v24 第 8 节，用户 2026-10-30
 * "权限可以按照新增 删除 修改 保存 这样给吗？控制到明细级别"），业务例子 E42。
 *
 * 页面视图按后端的生成规则手写：角色没有某个区域的新增、删除时，这个区域的 `buttons` 里没有这两个按钮；
 * 没有修改时 `canModify` 为 false。
 */
import { describe, expect, it } from 'vitest';
import type { CommandResult } from '../../src/contracts/command';
import { MASTER, MATERIAL, costView, openCostPage, selectRecord } from './support';

const UUID = '7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f';
const saved: CommandResult = {
  requestKey: UUID,
  outcome: 'saved',
  rows: [],
  idMap: {},
  prompts: [],
  skipped: [],
  approvals: []
};

/** 只有保存和原辅料的新增、删除、修改（端到端用例的 PF_TEST 角色）：主表只剩不改数据的按钮，不能改 */
function materialOnlyView() {
  const view = costView();
  view.master.buttons = view.master.buttons.filter(b => b.action === 'saveGridConfig');
  view.master.canModify = false;
  view.systemButtons = ['save'];
  return view;
}

describe('区域的新增、删除、修改（T-AZ-2）', () => {
  it('E42：主表已有的行不能改；原辅料能改单价、能新增、能删除，保存的命令主表不改', async () => {
    const view = materialOnlyView();
    const ctx = await openCostPage(view);
    const { runtime, fake, material } = ctx;
    expect(runtime.regionButtons(view.master).map(b => b.label)).toEqual(['保存列配置']);
    expect(runtime.regionButtons(view.details[0]).map(b => b.label)).toEqual(['新增', '复制', '删除']);
    expect(runtime.cellEditable(MASTER, '2550', 'MEMO')).toBe(false);
    expect(runtime.edit(MASTER, '2550', 'MEMO', '改')).toBe(false);

    await selectRecord(ctx, '2550');
    expect(runtime.cellEditable(MATERIAL, '206323', 'PRICE')).toBe(true);
    expect(runtime.edit(MATERIAL, '206323', 'PRICE', '80')).toBe(true);
    await runtime.addRow(MATERIAL);
    const added = material.ids.at(-1)!;
    expect(runtime.edit(MATERIAL, added, 'PRICE', '3.50')).toBe(true);
    material.selected = ['206325'];
    runtime.deleteSelected(MATERIAL);
    fake.http.on('POST', '/api/commands', saved);
    await runtime.save();

    const body = fake.http.callsTo('POST', '/api/commands')[0].body as { documents: unknown[] };
    expect(body.documents).toEqual([
      {
        entity: MASTER,
        master: { op: 'none', rowKey: '2550' },
        details: [
          { entity: MATERIAL, op: 'modify', rowKey: '206323', changes: { PRICE: '80' } },
          { entity: MATERIAL, op: 'add', clientRowId: added, values: { GOODSID: '0', PRICE: '3.50', USAGE: '0' } },
          { entity: MATERIAL, op: 'delete', rowKey: '206325' }
        ]
      }
    ]);
  });

  it('区域没有修改、有新增：原辅料已保存的行整行只读，新增的行照常填写并写进命令', async () => {
    const view = costView();
    view.details[0].canModify = false;
    const ctx = await openCostPage(view);
    const { runtime, fake, material } = ctx;
    await selectRecord(ctx, '2550');
    // 物料（GOODSID）是回填的 Lookup 字段，任何行都只能经 Lookup 选（FP-15），这里只看能直接填写的字段
    for (const field of ['PRICE', 'USAGE', 'MEMO'])
      expect(runtime.cellEditable(MATERIAL, '206323', field), field).toBe(false);
    expect(runtime.edit(MATERIAL, '206323', 'PRICE', '80')).toBe(false);
    expect(runtime.cellEditable(MASTER, '2550', 'MEMO')).toBe(true);

    await runtime.addRow(MATERIAL);
    const added = material.ids.at(-1)!;
    for (const field of ['PRICE', 'USAGE', 'MEMO'])
      expect(runtime.cellEditable(MATERIAL, added, field), field).toBe(true);
    runtime.edit(MATERIAL, added, 'PRICE', '3.50');
    runtime.edit(MATERIAL, added, 'MEMO', '新');
    fake.http.on('POST', '/api/commands', saved);
    await runtime.save();
    const body = fake.http.callsTo('POST', '/api/commands')[0].body as { documents: Array<{ details: unknown[] }> };
    expect(body.documents[0].details).toEqual([
      {
        entity: MATERIAL,
        op: 'add',
        clientRowId: added,
        values: { GOODSID: '0', PRICE: '3.50', USAGE: '0', MEMO: '新' }
      }
    ]);
  });
});
