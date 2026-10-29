/**
 * T-CT-4：C09 每个接口的模拟实现都能调用并返回样例（CT-04）；计算 Worker、实时事件、ShellApi 的模拟实现可用。
 */
import { describe, expect, it } from 'vitest';
import { createPlatformApi } from '../../src/contracts/api';
import { PlatformError } from '../../src/contracts/errors';
import { createFakeCalc } from '../../src/contracts/fakes/calc';
import { createFakeHttp } from '../../src/contracts/fakes/http';
import { createFakeRealtime } from '../../src/contracts/fakes/realtime';
import * as s from '../../src/contracts/fakes/samples';
import { createFakeShell } from '../../src/contracts/fakes/shell';

const UUID = '3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c';
const FP = s.approvalDetailSample.fingerprint;

describe('C09 每个接口的模拟实现', () => {
  const http = createFakeHttp();
  const api = createPlatformApi(http);

  /** [接口, 调用, 期望的方法和路径, 期望的响应] */
  const cases: Array<[string, () => Promise<unknown>, string, unknown]> = [
    ['登录', () => api.login('admin', 'admin123..'), 'POST /api/auth/login', s.loginResponseSample],
    ['选角色', () => api.selectRole('COST_ACCOUNTANT'), 'POST /api/auth/role', s.selectRoleResponseSample],
    ['退出', () => api.logout(), 'POST /api/auth/logout', undefined],
    ['当前用户', () => api.me(), 'GET /api/me', s.meResponseSample],
    [
      '账号列表',
      () => api.listAccounts({ keyword: '', startRow: 0, endRow: 50 }),
      'GET /api/admin/accounts',
      s.accountListSample
    ],
    [
      '新建账号',
      () =>
        api.createAccount({
          username: 'zhangsan',
          displayName: '张三',
          departmentId: '10',
          password: 'p',
          roleCodes: ['COST_ACCOUNTANT']
        }),
      'POST /api/admin/accounts',
      s.accountSample
    ],
    [
      '修改账号',
      () => api.updateAccount('113', { displayName: '张三', departmentId: '10', roleCodes: [], enabled: false }),
      'PUT /api/admin/accounts/113',
      s.accountSample
    ],
    ['改密码', () => api.changePassword('113', 'p'), 'POST /api/admin/accounts/113/password', undefined],
    ['部门', () => api.departments(), 'GET /api/admin/departments', s.departmentListSample],
    ['页面视图', () => api.pageView('COST_PINGGU'), 'GET /api/pages/COST_PINGGU/view', s.pageViewSample],
    ['规则包', () => api.rulesPack('COST_PINGGU', 7), 'GET /api/rules-packs/COST_PINGGU/7', s.rulesPackSample],
    ['配置项列表', () => api.configItems('page'), 'GET /api/config/items', s.configItemListSample],
    [
      '配置项',
      () => api.configItem('page', 'COST_PINGGU'),
      'GET /api/config/items/page/COST_PINGGU',
      s.configItemSample
    ],
    [
      '保存配置项',
      () => api.saveConfigItem('page', 'COST_PINGGU', { name: '成本核算', content: {} }),
      'PUT /api/config/items/page/COST_PINGGU',
      s.configSaveResponseSample
    ],
    [
      '删除配置项',
      () => api.deleteConfigItem('page', 'COST_PINGGU'),
      'DELETE /api/config/items/page/COST_PINGGU',
      undefined
    ],
    ['校验配置', () => api.validateConfig({ items: [] }), 'POST /api/config/validate', s.configValidateResponseSample],
    [
      '向导读列',
      () => api.wizardColumns({ readView: 'T_COST_GOODS_PRICE_V', table: 'T_COST_GOODS' }),
      'POST /api/config/wizard/columns',
      s.wizardColumnsResponseSample
    ],
    [
      '读表结构',
      () => api.schemaColumns('V_COST_PINGGU_MATERIAL'),
      'POST /api/config/schema/columns',
      s.schemaColumnsResponseSample
    ],
    [
      '向导生成',
      () =>
        api.wizardGenerate({
          parentMenu: 'cost',
          pageCode: 'GOODS_PRICE_MANAGE',
          title: '物料清单及成本',
          layout: 'single',
          detailMode: 'tabs',
          audit: true,
          master: {},
          details: []
        }),
      'POST /api/config/wizard/generate',
      undefined
    ],
    [
      '列表',
      () => api.listRows('COST_PINGGU', s.listRequestSample),
      'POST /api/pages/COST_PINGGU/rows',
      s.listResponseSample
    ],
    [
      '按主键读行',
      () => api.rowsByKeys('COST_PINGGU', { entity: 'COST_PINGGU', rowKeys: ['1001', '1002'] }),
      'POST /api/pages/COST_PINGGU/rows/by-keys',
      s.rowsByKeysResponseSample
    ],
    [
      '单据加载',
      () => api.loadRecord('COST_PINGGU', '1001'),
      'GET /api/pages/COST_PINGGU/records/1001',
      s.recordResponseSample
    ],
    [
      'Lookup',
      () => api.lookupSearch('GOODS', { keyword: '胶', startRow: 0, endRow: 50 }),
      'POST /api/lookups/GOODS/search',
      s.lookupSearchResponseSample
    ],
    ['字典', () => api.dict('STATUS'), 'GET /api/dicts/STATUS', s.dictResponseSample],
    ['个人配置', () => api.personal('COST_PINGGU'), 'GET /api/pages/COST_PINGGU/personal', s.personalConfigSample],
    [
      '保存个人配置',
      () => api.savePersonal('COST_PINGGU', { detailMode: 'stack' }),
      'PUT /api/pages/COST_PINGGU/personal',
      { detailMode: 'stack' }
    ],
    ['导出配置', () => api.exports('COST_PINGGU'), 'GET /api/pages/COST_PINGGU/exports', s.exportListSample],
    ['命令', () => api.runCommand(s.commandSaveSample), 'POST /api/commands', s.resultSavedSample],
    ['待办', () => api.approvals({ box: 'todo', startRow: 0, endRow: 50 }), 'GET /api/approvals', s.approvalListSample],
    ['审批详情', () => api.approvalDetail('203'), 'GET /api/approvals/203', s.approvalDetailSample],
    [
      '审批预览',
      () => api.approvalPreview('203', { checkedRows: [] }),
      'POST /api/approvals/203/preview',
      s.previewResponseSample
    ],
    [
      '通过',
      () =>
        api.passApproval('203', {
          requestKey: UUID,
          fingerprint: FP,
          checkedRows: [],
          comment: '价格已核对',
          params: {}
        }),
      'POST /api/approvals/203/pass',
      s.approvalProcessedSample
    ],
    [
      '驳回',
      () => api.rejectApproval('203', { requestKey: UUID, comment: '价格偏高' }),
      'POST /api/approvals/203/reject',
      s.approvalProcessedSample
    ],
    [
      '撤回',
      () => api.withdrawApproval('203', { requestKey: UUID, comment: '录入有误' }),
      'POST /api/approvals/203/withdraw',
      s.approvalProcessedSample
    ],
    ['站内通知', () => api.inbox({ unread: true, startRow: 0, endRow: 20 }), 'GET /api/inbox', s.inboxListSample],
    ['已读', () => api.markRead(UUID), `POST /api/inbox/${UUID}/read`, undefined],
    [
      '投递记录',
      () => api.deliveries({ status: 'abandoned', startRow: 0, endRow: 50 }),
      'GET /api/admin/deliveries',
      s.deliveryListSample
    ],
    ['重新排队', () => api.requeueDelivery(UUID), `POST /api/admin/deliveries/${UUID}/requeue`, undefined],
    [
      '命令审查',
      () => api.commandReview({ startRow: 0, endRow: 50 }),
      'GET /api/admin/command-review',
      s.commandReviewListSample
    ],
    ['命令审查开关', () => api.setCommandReview(false), 'PUT /api/admin/command-review', undefined],
    ['健康检查', () => api.health(), 'GET /health', s.healthSample]
  ];

  it.each(cases)('%s', async (_, call, route, expected) => {
    await expect(call()).resolves.toEqual(expected);
    const last = http.calls.at(-1)!;
    expect(`${last.method} ${last.path}`).toBe(route);
  });

  it('导出返回文件', async () => {
    const file = await api.exportFile('COST_PINGGU', {
      mode: 'page',
      request: s.listRequestSample,
      columns: ['DOCID']
    });
    expect(file).toBeInstanceOf(Blob);
    expect(http.calls.at(-1)!.path).toBe('/api/pages/COST_PINGGU/export');
  });

  it('配置变更后重新读取的页面视图和规则包是后台请求', async () => {
    await api.pageView('COST_PINGGU', true);
    await api.rulesPack('COST_PINGGU', 7, true);
    expect(http.calls.slice(-2).map(c => c.options?.background)).toEqual([true, true]);
  });

  it('可以预设返回值和错误，错误次数用完后恢复样例', async () => {
    const fake = createFakeHttp();
    const platform = createPlatformApi(fake);
    fake.on('GET', '/api/pages/:pageCode/view', { ...s.pageViewSample, title: '另一个' });
    expect((await platform.pageView('X')).title).toBe('另一个');
    fake.fail('POST', '/api/commands', new PlatformError(409, 'DOCUMENT_BUSY', '单据正忙'), 1);
    await expect(platform.runCommand(s.commandSaveSample)).rejects.toMatchObject({ code: 'DOCUMENT_BUSY' });
    await expect(platform.runCommand(s.commandSaveSample)).resolves.toEqual(s.resultSavedSample);
    expect(fake.callsTo('POST', '/api/commands')).toHaveLength(2);
  });
});

describe('计算 Worker、实时事件和 ShellApi 的模拟实现', () => {
  it('同一规则包版本只加载一次；求值默认返回 C07 第 3 节的样例', async () => {
    const calc = createFakeCalc();
    const bytes = new TextEncoder().encode(JSON.stringify(s.rulesPackSample));
    const handle = await calc.load({ packId: 'COST_PINGGU', version: 7, bytes });
    expect(await calc.load({ packId: 'COST_PINGGU', version: 7, bytes })).toBe(handle);
    const result = await calc.evaluate(handle, JSON.stringify(s.evaluationRequestSample));
    expect(JSON.parse(result)).toEqual(s.evaluationResultSample);
    expect(calc.requests).toEqual([s.evaluationRequestSample]);
  });

  it('实时事件按 eventId 去重；订阅和退订按 C10 的消息发出', () => {
    const realtime = createFakeRealtime();
    const received: unknown[] = [];
    realtime.onEvent('config.changed', payload => received.push(payload));
    realtime.subscribe(['COST_PINGGU']);
    realtime.subscribe(['COST_PINGGU']);
    const [configChanged] = s.serverMessageSamples;
    realtime.push(configChanged);
    realtime.push(configChanged);
    realtime.unsubscribe(['COST_PINGGU']);
    realtime.unsubscribe(['COST_PINGGU']);
    expect(received).toEqual([{ pages: ['COST_PINGGU'], version: 13 }]);
    expect(realtime.sent).toEqual([
      { type: 'subscribe', pages: ['COST_PINGGU'] },
      { type: 'unsubscribe', pages: ['COST_PINGGU'] }
    ]);
  });

  it('ShellApi 的模拟实现给出当前用户、角色，记录提示和页签', () => {
    const fake = createFakeShell();
    expect(fake.shell.session.user.value?.displayName).toBe('杨娜');
    expect(fake.shell.session.role.value?.code).toBe('COST_ACCOUNTANT');
    fake.shell.message.success('已保存');
    fake.shell.tabs.setDirty('/page/COST_PINGGU', true);
    expect(fake.messages).toEqual([{ kind: 'success', text: '已保存' }]);
    expect(fake.dirty.get('/page/COST_PINGGU')).toBe(true);
  });
});
