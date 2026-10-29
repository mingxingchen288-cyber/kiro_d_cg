/**
 * 待办列表（"待审批 / 我的发起"，同旧系统审批通知中心）：每个审批一行，列为来源页面和操作、提交时间、提交人、来源单据号、
 * 状态和当前级别（FA-06）；打开审批详情走路由 `/approval/{approvalId}`（FA-05）；处理后、收到审批通知时刷新列表。
 * 数据为 C09 第 6 节的样例（审批 203，物料清单及成本页保存聚维酮K30）。
 */
import { describe, expect, it } from 'vitest';
import { createPlatformApi } from '../../src/contracts/api';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import { ApprovalDetailRuntime } from '../../src/modules/approval/detail-runtime';
import { ApprovalTodoRuntime, summaryTexts } from '../../src/modules/approval/todo-runtime';

function setup() {
  const fake = createFakeShell();
  const rt = new ApprovalTodoRuntime({
    api: createPlatformApi(fake.http),
    message: fake.shell.message,
    tabs: fake.shell.tabs,
    realtime: fake.shell.realtime
  });
  return { fake, rt };
}

describe('待办列表', () => {
  it('打开时读取"待审批"一页，并读取"我的发起"的条数', async () => {
    const { fake, rt } = setup();
    await rt.load();
    const queries = fake.http.callsTo('GET', '/api/approvals').map(c => c.options?.query);
    expect(queries).toEqual([
      { box: 'todo', startRow: 0, endRow: 50 },
      { box: 'mine', startRow: 0, endRow: 0 }
    ]);
    // C09 第 6 节样例的 total 为 7（两个页签用同一个样例）
    expect(rt.state.counts).toEqual({ todo: 7, mine: 7 });
    expect(rt.state.rows.map(r => r.approvalId)).toEqual(['203']);
    expect(summaryTexts(rt.state.rows[0])).toEqual({
      source: '物料清单及成本（保存）',
      recordKey: '25（聚维酮K30）',
      applicant: '杨娜',
      submittedAt: '2026-10-24 09:30:00',
      status: '审批中 · 第 1 级'
    });
  });

  it('切换到"我的发起"；打开详情用 /approval/{approvalId}', async () => {
    const { fake, rt } = setup();
    await rt.load();
    await rt.switchBox('mine');
    expect(fake.http.callsTo('GET', '/api/approvals').at(-2)?.options?.query).toEqual({
      box: 'mine',
      startRow: 0,
      endRow: 50
    });
    rt.open(rt.state.rows[0]);
    expect(fake.opened).toEqual([{ path: '/approval/203', title: '审批详情 203' }]);
  });

  it('审批处理完成、收到审批通知时重新读取列表', async () => {
    const { fake, rt } = setup();
    const stop = rt.watch();
    await rt.load();
    const before = fake.http.callsTo('GET', '/api/approvals').length;

    const detail = new ApprovalDetailRuntime('203', { api: createPlatformApi(fake.http), message: fake.shell.message });
    await detail.load();
    await detail.pass();
    await rt.idle();
    expect(fake.http.callsTo('GET', '/api/approvals').length).toBe(before + 2);

    fake.realtime.push({
      topic: 'notification',
      eventId: '2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d',
      payload: {
        deliveryId: '3b4c5d6e-7f8a-4b9c-8d0e-2f3a4b5c6d7e',
        title: '您有来自于物料清单及成本页面，业务单据为25的审批',
        body: '',
        link: '/approval/203'
      }
    });
    await rt.idle();
    expect(fake.http.callsTo('GET', '/api/approvals').length).toBe(before + 4);
    stop();
  });
});
