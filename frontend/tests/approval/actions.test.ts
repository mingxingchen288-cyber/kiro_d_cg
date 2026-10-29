/**
 * 驳回、撤回、人工参数和重新确认（FA-03、FA-04、FA-08）的正向流程，数据同 E37（审批 301）。
 * 人工参数用 C09 第 6 节通过请求样例中的 `effectiveDate`（生效日期），配置写法同 C06 7.1 的 `params` 样例。
 */
import { describe, expect, it } from 'vitest';
import { createPlatformApi } from '../../src/contracts/api';
import { PlatformError } from '../../src/contracts/errors';
import type { PassRequest, RejectRequest, WithdrawRequest } from '../../src/contracts/http';
import { ApprovalDetailRuntime } from '../../src/modules/approval/detail-runtime';
import { ADMIN, E37Backend, ROLES, YANGNA, shellFor } from './support';

function open(fake: ReturnType<typeof shellFor>) {
  return new ApprovalDetailRuntime('301', { api: createPlatformApi(fake.http), message: fake.shell.message });
}

describe('驳回、撤回', () => {
  it('驳回必须填写原因；填写后提交驳回并重新读取详情', async () => {
    const fake = shellFor(ADMIN, ROLES.ADMIN, new E37Backend());
    const rt = open(fake);
    await rt.load();
    expect(await rt.reject()).toBeNull();
    expect(fake.messages).toContainEqual({ kind: 'warning', text: '请填写驳回原因' });
    expect(fake.http.callsTo('POST', '/api/approvals/:approvalId/reject')).toHaveLength(0);

    rt.state.comment = '价格偏高';
    const result = await rt.reject();
    expect(result?.outcome).toBe('approvalProcessed');
    const [call] = fake.http.callsTo('POST', '/api/approvals/:approvalId/reject');
    const body = call.body as RejectRequest;
    expect(body.comment).toBe('价格偏高');
    expect(Object.keys(body).sort()).toEqual(['comment', 'requestKey']);
    expect(fake.messages).toContainEqual({ kind: 'success', text: '已驳回' });
    expect(fake.http.callsTo('GET', '/api/approvals/:approvalId')).toHaveLength(2);
  });

  it('发起人在没人处理前可以撤回（canWithdraw），原因可以不填', async () => {
    const fake = shellFor(YANGNA, ROLES.COST, new E37Backend());
    const rt = open(fake);
    await rt.load();
    expect(rt.detail.value!.actions).toEqual({ canPass: false, canReject: false, canWithdraw: true });
    rt.state.comment = '录入有误';
    await rt.withdraw();
    const [call] = fake.http.callsTo('POST', '/api/approvals/:approvalId/withdraw');
    expect((call.body as WithdrawRequest).comment).toBe('录入有误');
    expect(fake.messages).toContainEqual({ kind: 'success', text: '已撤回' });
  });
});

describe('人工参数（FA-08）', () => {
  it('必填参数没填不能通过；填写后随通过请求提交', async () => {
    const backend = new E37Backend();
    const fake = shellFor(ADMIN, ROLES.ADMIN, backend);
    const detail = backend.detail.bind(backend);
    fake.http.on('GET', '/api/approvals/:approvalId', () => ({
      ...detail(ADMIN),
      params: [{ name: 'effectiveDate', label: '生效日期', type: 'date', source: 'manual', required: true, level: 1 }]
    }));
    const rt = open(fake);
    await rt.load();
    expect(rt.state.params).toEqual({ effectiveDate: null });
    expect(await rt.pass()).toBeNull();
    expect(fake.messages).toContainEqual({ kind: 'warning', text: '请填写生效日期' });
    expect(backend.passes).toHaveLength(0);

    rt.state.params.effectiveDate = '2026-11-01';
    await rt.pass();
    expect(backend.passes[0].params).toEqual({ effectiveDate: '2026-11-01' });
  });
});

describe('重新确认（FA-03）', () => {
  it('通过返回 409 RECONFIRM_REQUIRED：重新读取详情，提示再次确认；再次通过成功', async () => {
    const backend = new E37Backend();
    const fake = shellFor(ADMIN, ROLES.ADMIN, backend);
    fake.http.fail(
      'POST',
      '/api/approvals/:approvalId/pass',
      new PlatformError(409, 'RECONFIRM_REQUIRED', '审批内容已变化，请重新确认'),
      1
    );
    const rt = open(fake);
    await rt.load();
    rt.state.comment = '同意';
    expect(await rt.pass()).toBeNull();
    expect(rt.state.reconfirm).toBe(true);
    expect(fake.http.callsTo('GET', '/api/approvals/:approvalId')).toHaveLength(2);
    expect(fake.messages.some(m => m.kind === 'warning' && m.text.includes('重新确认'))).toBe(true);
    // 意见保留，审批人核对后再次通过
    expect(rt.state.comment).toBe('同意');
    const result = await rt.pass();
    expect(result?.approvals[0].level).toBe(2);
    expect(rt.state.reconfirm).toBe(false);
    const [first, second] = fake.http.callsTo('POST', '/api/approvals/:approvalId/pass').map(c => c.body as PassRequest);
    expect(first.requestKey).not.toBe(second.requestKey);
  });
});
