/**
 * 业务例子 E37 的页面部分（T-FA-1 验收）：成本单 2550 原辅料一次改三行后保存，触发"成本明细改价审批"（C06 7.8）。
 * 详情中原辅料三行的"触发审批"依次为"成本明细改价审批""随审批等待""随审批等待"；物料清单一块只有 25，单价 75 → 90，
 * 不能取消；系统管理员通过后进入第 2 级"采购、生产会签"，采购、生产分别通过后审批结束。
 */
import { describe, expect, it } from 'vitest';
import { createPlatformApi } from '../../src/contracts/api';
import { ApprovalDetailRuntime } from '../../src/modules/approval/detail-runtime';
import { gridRows, statusLabel, stepRows, triggerLabel } from '../../src/modules/approval/view-model';
import { ADMIN, BUYER, E37Backend, MAKER, ROLES, shellFor } from './support';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function open(fake: ReturnType<typeof shellFor>) {
  return new ApprovalDetailRuntime('301', { api: createPlatformApi(fake.http), message: fake.shell.message });
}

describe('E37 成本明细改价审批', () => {
  it('详情：原辅料三行的触发审批、物料清单一块 75 → 90 且不能取消', async () => {
    const backend = new E37Backend();
    const rt = open(shellFor(ADMIN, ROLES.ADMIN, backend));
    await rt.load();
    const detail = rt.detail.value!;
    expect(statusLabel(detail)).toBe('审批中 · 第 1 级');

    const [material, pkg] = rt.view.value!.details;
    expect(material.title).toBe('原辅料');
    const rows = gridRows(material.rows);
    expect(rows.map(r => triggerLabel(r.flows, rt.flowNames()))).toEqual([
      '成本明细改价审批',
      '随审批等待',
      '随审批等待'
    ]);
    expect(rows.map(r => r.change)).toEqual(['修改', '修改', '修改']);
    expect(rows[0].texts).toEqual(['25', '聚维酮K30', '75.00 → 90.00', '750.00 → 900.00']);
    expect(rows[0].changed).toEqual([false, false, true, true]);
    expect(rows[1].texts).toEqual(['310 → 13165', '玉米淀粉 → 微晶纤维素', '22 → 40', '935 → 1700']);
    expect(rows[2].texts).toEqual(['115', '硬脂酸镁', '63', '157.5']);
    expect(pkg.rows).toEqual([]);

    const [goods] = rt.view.value!.affected;
    expect(goods.title).toBe('物料清单');
    const goodsRows = gridRows(goods.rows);
    expect(goodsRows.map(r => [r.key, r.lead, r.texts])).toEqual([['25', true, ['25', '聚维酮K30', '75.00 → 90.00']]]);
    expect(rt.isChecked(goods, '25')).toBe(true);
    expect(rt.canToggle(goods, '25')).toBe(false);
    expect(rt.groupCount(goods)).toBe(1);

    expect(stepRows(detail.steps)).toEqual([
      {
        level: 1,
        node: '管理员审批',
        mode: '或签',
        approvers: '角色：系统管理员（待处理）',
        flowName: '成本明细改价审批',
        status: '待处理',
        time: '—',
        comment: '—'
      },
      {
        level: 2,
        node: '采购、生产会签',
        mode: '会签',
        approvers: '角色：采购（待处理）、角色：生产（待处理）',
        flowName: '成本明细改价审批',
        status: '预计进入',
        time: '—',
        comment: '—'
      }
    ]);
  });

  it('系统管理员通过后进入第 2 级会签，采购、生产分别通过后结束', async () => {
    const backend = new E37Backend();

    // 第 1 级：系统管理员
    const adminShell = shellFor(ADMIN, ROLES.ADMIN, backend, '2026-10-29T10:00:00');
    const admin = open(adminShell);
    await admin.load();
    expect(admin.detail.value!.actions.canPass).toBe(true);
    const first = await admin.pass();
    expect(first?.approvals[0]).toMatchObject({ status: 'pending', level: 2 });
    const [adminPass] = backend.passes;
    expect(adminPass.requestKey).toMatch(UUID);
    // 物料清单一块不能改勾选（selection 为 all），通过时不提交勾选
    expect(adminPass.checkedRows).toEqual([]);
    expect(adminPass.fingerprint).toBe(`sha256:${'3'.repeat(63)}0`);
    expect(adminShell.messages).toContainEqual({ kind: 'success', text: '本级审批已提交' });
    // 通过后重新读取详情：第 2 级待处理，管理员不能再通过
    expect(admin.detail.value!.currentLevel).toBe(2);
    expect(admin.detail.value!.actions.canPass).toBe(false);
    expect(stepRows(admin.detail.value!.steps)[0]).toMatchObject({
      status: '已通过',
      approvers: '角色：系统管理员（已通过，系统管理员）',
      time: '2026-10-29 10:00:00'
    });

    // 第 2 级会签：采购先通过，本级仍待处理
    const buyer = open(shellFor(BUYER, ROLES.BUYER, backend, '2026-10-29T10:05:00'));
    await buyer.load();
    expect(statusLabel(buyer.detail.value!)).toBe('审批中 · 第 2 级');
    expect(buyer.detail.value!.actions.canPass).toBe(true);
    buyer.state.comment = '价格已核对';
    const second = await buyer.pass();
    expect(second?.approvals[0]).toMatchObject({ status: 'pending', level: 2 });
    expect(backend.passes[1]).toMatchObject({ comment: '价格已核对', checkedRows: [] });
    expect(stepRows(buyer.detail.value!.steps)[1]).toEqual({
      level: 2,
      node: '采购、生产会签',
      mode: '会签',
      approvers: '角色：采购（已通过，采购员）、角色：生产（待处理）',
      flowName: '成本明细改价审批',
      status: '待处理（已通过 1/2）',
      time: '2026-10-29 10:05:00',
      comment: '采购员：价格已核对'
    });
    expect(buyer.state.comment).toBe('');

    // 生产通过：审批结束
    const maker = open(shellFor(MAKER, ROLES.MAKER, backend, '2026-10-29T10:10:00'));
    await maker.load();
    expect(maker.detail.value!.actions.canPass).toBe(true);
    const third = await maker.pass();
    expect(third?.approvals[0].status).toBe('approved');
    expect(new Set(backend.passes.map(p => p.requestKey)).size).toBe(3);
    const done = maker.detail.value!;
    expect(statusLabel(done)).toBe('已通过 · 第 2 级');
    expect(done.actions).toEqual({ canPass: false, canReject: false, canWithdraw: false });
    expect(stepRows(done.steps).map(s => s.status)).toEqual(['已通过', '已通过']);
  });
});
