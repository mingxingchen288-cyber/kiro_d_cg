/**
 * 业务例子 E39 的页面部分（T-FA-1 验收）：物料清单页把聚维酮K30（25）的执行价 75 改为 80，触发"物料清单改价审批"
 * （C06 7.10）。受影响单据默认全选；审批人取消 2556 那一行后用 preview 重算，这一行恢复为单价 75、金额 23.25，
 * 每盒成本恢复为改前的值，其他行仍为 75 → 80；通过时 `checkedRows` 不含 2556，带上 preview 返回的指纹。
 */
import { describe, expect, it } from 'vitest';
import { createPlatformApi } from '../../src/contracts/api';
import { ApprovalDetailRuntime } from '../../src/modules/approval/detail-runtime';
import { gridRows, statusLabel } from '../../src/modules/approval/view-model';
import { ADMIN, E39Backend, E39_INITIAL_FINGERPRINT, E39_PREVIEW_FINGERPRINT, ROLES, shellFor } from './support';

describe('E39 物料清单改价审批：取消 2556', () => {
  it('打开详情默认全选，取消 2556 后这一行恢复为 75、23.25，通过时 checkedRows 不含 2556', async () => {
    const backend = new E39Backend();
    const fake = shellFor(ADMIN, ROLES.ADMIN, backend);
    const rt = new ApprovalDetailRuntime('203', { api: createPlatformApi(fake.http), message: fake.shell.message });
    await rt.load();
    expect(rt.fingerprint.value).toBe(E39_INITIAL_FINGERPRINT);

    // 来源单据主表：物料清单 25，单价 75 → 80
    const master = rt.view.value!.master;
    expect(master.title).toBe('物料清单');
    expect(gridRows(master.rows)[0].texts).toEqual(['25', '聚维酮K30', '75.00', '75.00 → 80.00']);

    // 受影响单据：按修改表主键（DTLID）一个勾选框，默认全选；记录已不存在的行没有勾选框
    const block = rt.view.value!.affected[0];
    expect([block.title, block.editable]).toEqual(['成本核算（原辅料）', true]);
    let rows = gridRows(block.rows);
    expect(rows.map(r => [r.key, r.lead, r.missing])).toEqual([
      ['206323', true, false],
      ['103681', true, false],
      [null, false, true]
    ]);
    expect(rt.groupCount(block)).toBe(3);
    expect(rt.selectableKeys(block)).toEqual(['206323', '103681']);
    expect(rt.isChecked(block, '206323')).toBe(true);
    expect(rt.isChecked(block, '103681')).toBe(true);
    expect(rt.canToggle(block, '103681')).toBe(true);
    expect(rows[1].texts.slice(3, 5)).toEqual(['75.00 → 80.00', '23.25 → 24.80']);
    expect(rows[2].texts).toEqual(['2601', '—', '聚维酮K30', '75.00', '150.00', '—', '—']);
    expect(rt.selectionCount()).toEqual({ checked: 2, total: 2 });

    // 取消 2556：preview 提交当前勾选，按返回的 view 刷新
    await rt.toggle(block, '103681', false);
    expect(backend.previews).toEqual([
      { checkedRows: [{ flow: 'GOODS_TO_COST', block: 'costMaterial', key: '206323' }] }
    ]);
    expect(rt.isChecked(block, '103681')).toBe(false);
    rows = gridRows(rt.view.value!.affected[0].rows);
    expect(rows[1].texts).toEqual(['2556', '10mg氯丙嗪片', '聚维酮K30', '75.00', '23.25', '1.1566', '689.03']);
    expect(rows[1].changed.some(Boolean)).toBe(false);
    expect(rows[0].texts.slice(3, 5)).toEqual(['75.00 → 80.00', '750.00 → 800.00']);
    expect(rt.fingerprint.value).toBe(E39_PREVIEW_FINGERPRINT);
    expect(rt.selectionCount()).toEqual({ checked: 1, total: 2 });

    // 通过：只提交勾选的 206323，带 preview 返回的指纹
    const result = await rt.pass();
    expect(result?.approvals[0].status).toBe('approved');
    const [body] = backend.passes;
    expect(body.checkedRows).toEqual([{ flow: 'GOODS_TO_COST', block: 'costMaterial', key: '206323' }]);
    expect(body.fingerprint).toBe(E39_PREVIEW_FINGERPRINT);
    expect(statusLabel(rt.detail.value!)).toBe('已通过 · 第 1 级');
  });

  it('表头全选只选能勾选的行，不含记录已不存在的行', async () => {
    const backend = new E39Backend();
    const fake = shellFor(ADMIN, ROLES.ADMIN, backend);
    const rt = new ApprovalDetailRuntime('203', { api: createPlatformApi(fake.http), message: fake.shell.message });
    await rt.load();
    const block = rt.view.value!.affected[0];
    await rt.toggleAll(block, false);
    expect(backend.previews.at(-1)).toEqual({ checkedRows: [] });
    expect(rt.selectionCount()).toEqual({ checked: 0, total: 2 });
    await rt.toggleAll(block, true);
    expect(backend.previews.at(-1)).toEqual({
      checkedRows: [
        { flow: 'GOODS_TO_COST', block: 'costMaterial', key: '206323' },
        { flow: 'GOODS_TO_COST', block: 'costMaterial', key: '103681' }
      ]
    });
    expect(gridRows(rt.view.value!.affected[0].rows)[1].texts[3]).toBe('75.00 → 80.00');
  });
});
