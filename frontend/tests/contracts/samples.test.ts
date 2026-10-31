/**
 * T-CT-4：前端契约类型与样例。
 *
 * - C02、C05、C07、C09、C10 的样例都能被前端类型无损解析：解析后的值与样例逐项相同。代码块中的样例直接从
 *   docs/契约 读取，并与 src/contracts/fakes/samples.ts 中模拟实现返回的样例比较；C09 表格中的行内样例与后端
 *   backend/tests/contracts/test_samples.py 的 INLINE 相同。
 * - 与 T-CT-1 字段名一致：逐个比较前端对象类型和 backend/src/cost_platform/contracts/types.py 中同名类的字段。
 */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import * as c02 from '../../src/contracts/command';
import * as c03 from '../../src/contracts/errors';
import * as c09 from '../../src/contracts/http';
import * as c05 from '../../src/contracts/page-view';
import * as c10 from '../../src/contracts/realtime';
import * as c07 from '../../src/contracts/rules';
import { type Schema, array, objectRegistry } from '../../src/contracts/schema';
import * as s from '../../src/contracts/fakes/samples';

const DOCS = fileURLToPath(new URL('../../../docs/契约/', import.meta.url));
const TYPES_PY = fileURLToPath(new URL('../../../backend/src/cost_platform/contracts/types.py', import.meta.url));

function blocks(prefix: string): string[] {
  const file = readdirSync(DOCS).find(name => name.startsWith(`${prefix}-`))!;
  const text = readFileSync(`${DOCS}${file}`, 'utf-8').replace(/\r\n/g, '\n');
  return [...text.matchAll(/```json\n([\s\S]*?)```/g)].map(m => m[1]);
}
const block = (prefix: string, index: number) => JSON.parse(blocks(prefix)[index]);
const lines = (prefix: string, index: number) =>
  blocks(prefix)
    [index].split('\n')
    .filter(line => line.trim())
    .map(line => JSON.parse(line));

describe('模拟实现中的样例与 docs/契约 中的代码块相同', () => {
  const cases: Array<[string, unknown, unknown]> = [
    ['C02 页面保存', s.commandSaveSample, block('C02', 0)],
    ['C02 审批处理', s.commandApprovalSample, block('C02', 1)],
    ['C02 已写入', s.resultSavedSample, block('C02', 2)],
    ['C02 已提交审批', s.resultApprovalSubmittedSample, block('C02', 3)],
    ['C03 错误', s.errorSample, block('C03', 0)],
    ['C05 页面视图', s.pageViewSample, block('C05', 0)],
    ['C06 配置项', s.configItemSample, block('C06', 0)],
    ['C07 规则包', s.rulesPackSample, block('C07', 0)],
    ['C07 求值请求', s.evaluationRequestSample, block('C07', 1)],
    ['C07 求值结果', s.evaluationResultSample, block('C07', 2)],
    ['C09 列表请求', s.listRequestSample, block('C09', 0)],
    ['C09 个人配置', s.personalConfigSample, block('C09', 1)],
    ['C09 待办摘要', s.approvalSummarySample, block('C09', 2)],
    ['C09 审批详情', s.approvalDetailSample, block('C09', 3)],
    ['C10 频道事件', s.channelEventSample, block('C10', 0)],
    ['C10 浏览器消息', s.clientMessageSamples, lines('C10', 1)],
    ['C10 服务端消息', s.serverMessageSamples, lines('C10', 2)]
  ];
  it.each(cases)('%s', (_, embedded, documented) => {
    expect(embedded).toEqual(documented);
  });
});

const TMP = 'tmp-6a1f2c3d-0b4e-4f5a-8c7d-9e0f1a2b3c4d';
const UUID = '3f2b6c1e-8a4d-4c2e-9b1a-0d6e5f7a8b9c';
const FP = 'sha256:5b1e0c6d9a3f47e28b1c6d0e9f3a2b4c5d6e7f8091a2b3c4d5e6f708192a3b4c';
const command = (document: unknown) => ({
  requestKey: UUID,
  page: 'COST_PINGGU',
  operation: 'COST_PINGGU.save',
  documents: [document],
  params: {}
});

/** [名称, 类型, 样例]：解析后与样例逐项相同 */
const ROUNDTRIP: Array<[string, Schema<unknown>, unknown]> = [
  ['C02 页面保存', c02.Command, block('C02', 0)],
  ['C02 审批处理', c02.Command, block('C02', 1)],
  [
    'C02 新增单据',
    c02.Command,
    command({
      entity: 'COST_PINGGU',
      master: { op: 'add', clientRowId: TMP, values: { QTY: '1' } },
      details: [{ entity: 'COST_MATERIAL', op: 'add', clientRowId: TMP, values: { GOODSID: '115' } }]
    })
  ],
  [
    'C02 删除单据',
    c02.Command,
    command({ entity: 'COST_PINGGU', master: { op: 'delete', rowKey: '1001' }, details: [] })
  ],
  [
    'C02 只改明细',
    c02.Command,
    command({
      entity: 'COST_PINGGU',
      master: { op: 'none', rowKey: '1001' },
      details: [{ entity: 'COST_MATERIAL', op: 'modify', rowKey: '5001', changes: { PRICE: null } }]
    })
  ],
  ['C02 已写入', c02.CommandResult, block('C02', 2)],
  ['C02 已提交审批', c02.CommandResult, block('C02', 3)],
  ['C03 错误', c03.ErrorResponse, block('C03', 0)],
  ['C05 页面视图', c05.PageView, block('C05', 0)],
  ['C07 规则包', c07.RulesPack, block('C07', 0)],
  ['C07 求值请求', c07.EvaluationRequest, block('C07', 1)],
  ['C07 求值结果', c07.EvaluationResult, block('C07', 2)],
  ['C07 显示求值请求', c07.EvaluationRequest, block('C07', 3)],
  ['C07 显示求值结果', c07.EvaluationResult, block('C07', 4)],
  ['C07 失败结果', c07.EvaluationResult, { ok: false, error: { code: 'PACK_INVALID', message: '规则包不能编译' } }],
  ['C09 列表请求', c09.ListRequest, block('C09', 0)],
  ['C09 个人配置', c09.PersonalConfig, block('C09', 1)],
  ['C09 待办摘要', c09.ApprovalSummary, block('C09', 2)],
  ['C09 审批详情', c09.ApprovalDetail, block('C09', 3)],
  ['C10 频道事件', c10.ChannelEvent, block('C10', 0)],
  ...lines('C10', 1).map((m, i): [string, Schema<unknown>, unknown] => [`C10 浏览器消息 ${i}`, c10.ClientMessage, m]),
  ...lines('C10', 2).map((m, i): [string, Schema<unknown>, unknown] => [`C10 服务端消息 ${i}`, c10.ServerMessage, m]),
  // ---- C09 表格中的行内样例（与后端 INLINE 相同）
  ['C09 登录请求', c09.LoginRequest, { username: 'admin', password: 'admin123..' }],
  ['C09 登录响应', c09.LoginResponse, s.loginResponseSample],
  ['C09 选角色请求', c09.SelectRoleRequest, { roleCode: 'COST_ACCOUNTANT' }],
  ['C09 选角色响应', c09.SelectRoleResponse, s.selectRoleResponseSample],
  ['C09 当前用户', c09.MeResponse, s.meResponseSample],
  ['C09 账号列表', c09.AccountList, s.accountListSample],
  [
    'C09 新建账号',
    c09.AccountCreate,
    { username: 'zhangsan', displayName: '张三', departmentId: '10', password: 'p', roleCodes: ['COST_ACCOUNTANT'] }
  ],
  ['C09 修改账号', c09.AccountUpdate, { displayName: '张三', departmentId: '10', roleCodes: [], enabled: false }],
  [
    'C09 修改账号（改账号名）',
    c09.AccountUpdate,
    { username: 'zhangsan2', displayName: '张三', departmentId: '10', roleCodes: [], enabled: true }
  ],
  [
    'C09 当前用户（菜单带图标、没有部门）',
    c09.MeResponse,
    {
      ...s.meResponseSample,
      user: { ...s.meResponseSample.user, departmentId: null, departmentName: null },
      menus: [
        {
          key: 'cost',
          title: '成本',
          kind: 'group',
          icon: 'mdi:currency-usd',
          children: [
            {
              key: 'COST_PINGGU',
              title: '成本核算',
              kind: 'page',
              pageCode: 'COST_PINGGU',
              icon: 'mdi:calculator-variant'
            }
          ]
        }
      ]
    }
  ],
  ['C09 部门列表', c09.DepartmentList, s.departmentListSample],
  ['C09 配置项列表', c09.ConfigItemList, s.configItemListSample],
  ['C06 配置项', c09.ConfigItem, block('C06', 0)],
  ['C09 保存配置请求', c09.ConfigSaveRequest, { name: '成本核算', content: {} }],
  ['C09 保存配置响应', c09.ConfigSaveResponse, s.configSaveResponseSample],
  ['C09 配置校验响应', c09.ConfigValidateResponse, s.configValidateResponseSample],
  ['C09 向导读列请求', c09.WizardColumnsRequest, { readView: 'T_COST_GOODS_PRICE_V', table: 'T_COST_GOODS' }],
  ['C09 向导读列响应', c09.WizardColumnsResponse, s.wizardColumnsResponseSample],
  ['C09 读表结构响应', c09.SchemaColumnsResponse, s.schemaColumnsResponseSample],
  [
    'C09 向导生成请求',
    c09.WizardGenerateRequest,
    {
      parentMenu: 'cost',
      pageCode: 'GOODS_PRICE_MANAGE',
      title: '物料清单及成本',
      layout: 'single',
      detailMode: 'tabs',
      audit: true,
      master: {},
      details: []
    }
  ],
  ['C09 列表响应', c09.ListResponse, s.listResponseSample],
  ['C09 按主键读行请求', c09.ByKeysRequest, { entity: 'COST_PINGGU', rowKeys: ['1001', '1002'] }],
  ['C09 按主键读行响应', c09.RowsResponse, s.rowsByKeysResponseSample],
  ['C09 单据响应', c09.RecordResponse, s.recordResponseSample],
  [
    'C09 Lookup 查询请求',
    c09.LookupSearchRequest,
    { keyword: '胶', filter: { column: 'GOODSTYPE', value: '瓶' }, startRow: 0, endRow: 50 }
  ],
  ['C09 Lookup 查询响应', c09.LookupSearchResponse, s.lookupSearchResponseSample],
  ['C09 不支持关键字搜索的 Lookup 查询响应', c09.LookupSearchResponse, { rows: [], total: 0, keywordSearch: false }],
  ['C09 字典', c09.DictResponse, s.dictResponseSample],
  ['C09 导出列表', c09.ExportList, s.exportListSample],
  ['C09 默认导出', c09.ExportRequest, { mode: 'page', request: block('C09', 0), columns: ['DOCID', 'GOODSNAME'] }],
  [
    'C09 按配置导出',
    c09.ExportRequest,
    { mode: 'config', exportCode: 'cost-pinggu-export', scope: 'current', request: block('C09', 0) }
  ],
  ['C09 待办列表', c09.ApprovalList, s.approvalListSample],
  [
    'C09 预览请求',
    c09.PreviewRequest,
    { checkedRows: [{ flow: 'GOODS_TO_COST', block: 'costMaterial', key: '206323' }] }
  ],
  ['C09 预览响应', c09.PreviewResponse, s.previewResponseSample],
  [
    'C09 通过请求',
    c09.PassRequest,
    {
      requestKey: UUID,
      fingerprint: FP,
      checkedRows: [{ flow: 'GOODS_TO_COST', block: 'costMaterial', key: '206323' }],
      comment: '价格已核对',
      params: { effectiveDate: '2026-11-01' }
    }
  ],
  ['C09 驳回请求', c09.RejectRequest, { requestKey: UUID, comment: '价格偏高' }],
  ['C09 撤回请求', c09.WithdrawRequest, { requestKey: UUID, comment: '录入有误' }],
  ['C09 审批处理结果', c02.CommandResult, s.approvalProcessedSample],
  ['C09 通知列表', c09.InboxList, s.inboxListSample],
  ['C09 投递列表', c09.DeliveryList, s.deliveryListSample],
  ['C09 命令审查记录', c09.CommandReviewList, s.commandReviewListSample],
  ['C09 命令审查开关', c09.CommandReviewToggle, { enabled: false }],
  ['C09 健康检查 ok', c09.HealthResponse, s.healthSample],
  ['C09 健康检查 starting', c09.HealthResponse, { status: 'starting' }]
];

describe('样例解析后内容不变', () => {
  it.each(ROUNDTRIP)('%s', (_, schema, data) => {
    expect(schema.parse(structuredClone(data))).toEqual(data);
  });

  it('模拟实现中的每个样例都能按它的类型解析', () => {
    const typed: Array<[unknown, Schema<unknown>]> = [
      [s.clientMessageSamples, array(c10.ClientMessage)],
      [s.serverMessageSamples, array(c10.ServerMessage)],
      [s.accountSample, c09.Account]
    ];
    for (const [data, schema] of typed) expect(schema.parse(data)).toEqual(data);
  });

  it('只认 camelCase 字段名：样例中的字段改成 snake_case 时不能解析', () => {
    const sample = structuredClone(block('C05', 0));
    sample.page_code = sample.pageCode;
    delete sample.pageCode;
    expect(() => c05.PageView.parse(sample)).toThrow(/page_code|pageCode/);
  });
});

describe('C03 错误体的严格检查（前端接收）', () => {
  it('C03 的样例解析出错误码、提示和定位到行与字段的明细', () => {
    const error = c03.parseErrorResponse(422, JSON.stringify(block('C03', 0)));
    expect(error.code).toBe('FIELD_NOT_WRITABLE');
    expect(error.message).toBe('有字段不能修改');
    expect(error.details[0]).toMatchObject({ entity: 'COST_GOODS_PRICE', rowKey: '115', field: 'PRICE' });
  });

  it('冻结错误给出冻结它的审批', () => {
    const detail = { ...block('C03', 0).details[0], approvalId: '203', field: null };
    const body = { code: 'FROZEN_BY_APPROVAL', message: '单据已被审批冻结', details: [detail, detail] };
    expect(c03.parseErrorResponse(409, JSON.stringify(body)).frozenBy).toEqual(['203']);
  });

  it.each([
    ['明细缺少字段', 422, JSON.stringify({ ...block('C03', 0), details: [{ message: 'PRICE 是 ERP 列，不能修改' }] })],
    ['错误码不在 C03 第 2 节中', 422, JSON.stringify({ ...block('C03', 0), code: 'PRICE_LOCKED' })],
    ['响应不是 JSON', 502, '<html><body>Bad Gateway</body></html>']
  ])('%s：给出带 HTTP 状态码的通用提示', (_, status, text) => {
    const error = c03.parseErrorResponse(status, text);
    expect(error.code).toBeNull();
    expect(error.details).toEqual([]);
    expect(error.message).toContain(`HTTP ${status}`);
  });

  it('每个错误码对应 C03 第 2 节表中的 HTTP 状态', () => {
    const file = readdirSync(DOCS).find(name => name.startsWith('C03-'))!;
    const table = readFileSync(`${DOCS}${file}`, 'utf-8')
      .split(/\r?\n/)
      .map(line => /^\|\s*(\d{3})\s*\|\s*([A-Z_]+)\s*\|/.exec(line))
      .filter((m): m is RegExpExecArray => m !== null)
      .map(m => [m[2], Number(m[1])]);
    expect(Object.entries(c03.ERROR_STATUS).sort()).toEqual(table.sort());
  });
});

// ---- 与后端类型的字段名核对

/** pydantic 的 to_camel：snake_case → camelCase */
function toCamel(name: string) {
  return name.replace(/_([a-z0-9])/g, (_, ch: string) => ch.toUpperCase());
}

function pythonClasses() {
  const text = readFileSync(TYPES_PY, 'utf-8').replace(/\r\n/g, '\n');
  const own = new Map<string, { bases: string[]; fields: string[] }>();
  let current: { bases: string[]; fields: string[] } | null = null;
  for (const line of text.split('\n')) {
    const head = /^class (\w+)\(([^)]*)\):/.exec(line);
    if (head) {
      current = { bases: head[2].split(',').map(b => b.trim()), fields: [] };
      own.set(head[1], current);
      continue;
    }
    if (line && !line.startsWith(' ')) {
      current = null;
      continue;
    }
    const field = current && /^ {4}(\w+): (.*)$/.exec(line);
    if (field && current && field[1] !== 'model_config') {
      const alias = /alias="(\w+)"/.exec(field[2]);
      current.fields.push(alias ? alias[1] : toCamel(field[1]));
    }
  }
  const resolve = (name: string): string[] => {
    const cls = own.get(name);
    if (!cls) return [];
    return [...cls.bases.flatMap(resolve), ...cls.fields];
  };
  return new Map([...own.keys()].map(name => [name, resolve(name).sort()]));
}

/**
 * 前端独有的类型，以及前端比后端多出的字段。多出的字段都是契约缺口，记在
 * .reports/modules/frontend-page/contract-gaps.md：ViewField 的 default（第 1 项）和 compare（第 2 项）。
 */
const FRONTEND_ONLY = new Set(['FieldDefault', 'FieldCompareView']);
const KNOWN_GAPS: Record<string, string[]> = { ViewField: ['compare', 'default'] };

describe('前端类型与后端 types.py 的字段名一致', () => {
  const python = pythonClasses();
  const names = [...objectRegistry.keys()].filter(name => !FRONTEND_ONLY.has(name)).sort();

  it('至少覆盖 C02、C03、C05、C07、C09、C10 的主要类型', () => {
    for (const name of [
      'Command',
      'CommandResult',
      'ErrorResponse',
      'PageView',
      'EvaluationRequest',
      'ApprovalDetail',
      'ConfigChangedEvent'
    ]) {
      expect(names).toContain(name);
    }
  });

  it.each(names)('%s', name => {
    expect(python.has(name), `后端没有类 ${name}`).toBe(true);
    const frontend = Object.keys(objectRegistry.get(name)!.shape)
      .filter(field => !(KNOWN_GAPS[name] ?? []).includes(field))
      .sort();
    expect(frontend).toEqual(python.get(name));
  });
});
