/**
 * 审批前端测试用的详情样例和"后端"替身。
 *
 * 数据按业务例子 E37、E39 和 C06 7.8、7.10 的配置，单据、物料、明细号取自 d_cg 的真实数据（与后端 approval 的测试
 * `backend/tests/approval/support.py` 相同）：
 * - 成本单 2550（250mg乙酰唑胺片）的原辅料 206323 聚维酮K30（物料 25，单价 75，每批数量 10，金额 750）、206326 玉米淀粉
 *   （310，单价 22，42.5，935）、206325 硬脂酸镁（115，单价 63，2.5，157.5）；成本单 2556（10mg氯丙嗪片）中聚维酮K30
 *   的明细 103681（单价 75、每批数量 0.31、金额 23.25）。
 * - 说明用的假设值（不是 d_cg 中的值）：E37 主表的每盒成本 18.425 → 27.575 取自后端测试替身规则（每盒成本 = 每批物料
 *   成本 / 100）；E39 中 2550、2556 的每盒成本、千片加工费和第三行"记录已不存在"取自 C09 第 6 节的样例（C09 写明是假设的），
 *   2556 勾选时的每盒成本、千片加工费的修改后（1.1721、688.50）是这里假设的；采购员（2001）、生产员（3001）两个账号同后端测试。
 *
 * "后端"替身：把 FakeHttp 的审批接口换成按场景状态返回的函数，状态随通过请求推进（只为跑通页面的正向流程）。
 */
import type { CommandResult } from '../../src/contracts/command';
import type { ApprovalDetail, CurrentUser, PassRequest, PreviewRequest } from '../../src/contracts/http';
import { approvalDetailSample } from '../../src/contracts/fakes/samples';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import type { FakeCall } from '../../src/contracts/fakes/http';

type Step = ApprovalDetail['steps'][number];
type Member = Step['members'][number];
type View = ApprovalDetail['view'];
type Row = View['affected'][number]['rows'][number];

const c = (before: string | null, after: string | null = before) => ({ before, after });

export const ADMIN: CurrentUser = { userId: '1', username: 'admin', displayName: '系统管理员', departmentId: null };
export const YANGNA: CurrentUser = { userId: '112', username: 'yangna', displayName: '杨娜', departmentId: '10' };
export const BUYER: CurrentUser = { userId: '2001', username: 'buyer', displayName: '采购员', departmentId: '20' };
export const MAKER: CurrentUser = { userId: '3001', username: 'maker', displayName: '生产员', departmentId: '30' };

export const ROLES = {
  ADMIN: { code: 'ADMIN', name: '系统管理员', admin: true },
  COST: { code: 'COST', name: '成本会计', admin: false },
  BUYER: { code: '008', name: '采购', admin: false },
  MAKER: { code: '007', name: '生产', admin: false }
};

type Person = CurrentUser;

const member = (id: string, name: string, extra: Partial<Member> = {}): Member => ({
  type: 'role',
  id,
  name,
  status: 'pending',
  processedBy: null,
  processedAt: null,
  comment: null,
  ...extra
});

const passedBy = (person: Person, at: string, comment: string | null = null): Partial<Member> => ({
  status: 'passed',
  processedBy: { userId: person.userId, displayName: person.displayName },
  processedAt: at,
  comment
});

const ok = (approvalId: string, requestKey: string, status: 'pending' | 'approved', level: number): CommandResult => ({
  requestKey,
  outcome: 'approvalProcessed',
  rows: [],
  idMap: {},
  prompts: [],
  skipped: [],
  approvals: [
    {
      approvalId,
      document: approvalId === '301' ? { entity: 'COST_PINGGU', recordKey: '2550' } : { entity: 'COST_GOODS_PRICE', recordKey: '25' },
      status,
      level,
      flows: approvalId === '301' ? ['COST_TO_GOODS'] : ['GOODS_TO_COST']
    }
  ]
});

// ============================================================ E37：成本明细改价审批（C06 7.8），审批 301

export function e37View(): View {
  return {
    master: {
      key: 'cost',
      title: '成本单及成本变化',
      columns: ['单据号', '产品', '每盒成本', '千片加工费'],
      rows: [
        {
          op: 'modify',
          flows: ['COST_TO_GOODS'],
          cells: [c('2550'), c('250mg乙酰唑胺片'), c('18.425', '27.575'), c(null)]
        }
      ]
    },
    details: [
      {
        key: 'material',
        title: '原辅料',
        columns: ['物料', '物料名称', '单价', '金额'],
        rows: [
          { op: 'modify', flows: ['COST_TO_GOODS'], cells: [c('25'), c('聚维酮K30'), c('75.00', '90.00'), c('750.00', '900.00')] },
          { op: 'modify', flows: [], cells: [c('310', '13165'), c('玉米淀粉', '微晶纤维素'), c('22', '40'), c('935', '1700')] },
          { op: 'modify', flows: [], cells: [c('115'), c('硬脂酸镁'), c('63'), c('157.5')] }
        ]
      },
      { key: 'package', title: '包材', columns: ['物料', '物料名称', '单价', '金额'], rows: [] }
    ],
    affected: [
      {
        flow: 'COST_TO_GOODS',
        key: 'goods',
        title: '物料清单',
        selection: 'all',
        editable: false,
        columns: ['物料ID', '物料名称', '单价'],
        rows: [{ op: 'modify', ref: { key: '25' }, checked: true, cells: [c('25'), c('聚维酮K30'), c('75.00', '90.00')] }]
      }
    ]
  };
}

/** E37 的审批过程：第 1 级系统管理员或签，第 2 级采购、生产会签（90 > 82.5） */
export class E37Backend {
  /** 已通过的人：admin → buyer → maker */
  passed: Array<{ person: Person; at: string; comment: string | null }> = [];
  readonly passes: PassRequest[] = [];

  private steps(): Step[] {
    const admin = this.passed.find(p => p.person === ADMIN);
    const buyer = this.passed.find(p => p.person === BUYER);
    const maker = this.passed.find(p => p.person === MAKER);
    const level2Done = Boolean(buyer && maker);
    return [
      {
        level: 1,
        flow: 'COST_TO_GOODS',
        flowName: '成本明细改价审批',
        node: '管理员审批',
        mode: 'or',
        status: admin ? 'passed' : 'pending',
        members: [member('ADMIN', '系统管理员', admin ? passedBy(ADMIN, admin.at, admin.comment) : {})]
      },
      {
        level: 2,
        flow: 'COST_TO_GOODS',
        flowName: '成本明细改价审批',
        node: '采购、生产会签',
        mode: 'and',
        status: level2Done ? 'passed' : admin ? 'pending' : 'upcoming',
        members: [
          member('008', '采购', buyer ? passedBy(BUYER, buyer.at, buyer.comment) : {}),
          member('007', '生产', maker ? passedBy(MAKER, maker.at, maker.comment) : {})
        ]
      }
    ];
  }

  private level() {
    return this.passed.length === 0 ? 1 : 2;
  }

  private status() {
    return this.passed.length === 3 ? 'approved' : 'pending';
  }

  /** 当前用户是不是本级尚未处理的审批人 */
  private pendingFor(person: Person) {
    if (this.status() !== 'pending') return false;
    if (this.level() === 1) return person === ADMIN;
    return (person === BUYER || person === MAKER) && !this.passed.some(p => p.person === person);
  }

  detail(person: Person): ApprovalDetail {
    const mine = this.pendingFor(person);
    return {
      approvalId: '301',
      status: this.status(),
      page: 'COST_PINGGU',
      pageTitle: '成本核算',
      operation: 'COST_PINGGU.save',
      operationLabel: '保存',
      source: { entity: 'COST_PINGGU', recordKey: '2550', label: '250mg乙酰唑胺片' },
      applicant: { userId: YANGNA.userId, displayName: YANGNA.displayName },
      submittedAt: '2026-10-29T09:30:00',
      currentLevel: this.level(),
      steps: this.steps(),
      view: e37View(),
      fingerprint: `sha256:${'3'.repeat(63)}${this.passed.length}`,
      params: [],
      actions: {
        canPass: mine,
        canReject: mine,
        canWithdraw: person === YANGNA && this.passed.length === 0 && this.status() === 'pending'
      },
      history: [
        {
          action: 'submit',
          level: 1,
          by: { userId: YANGNA.userId, displayName: YANGNA.displayName },
          at: '2026-10-29T09:30:00',
          comment: null
        },
        ...this.passed.map(p => ({
          action: 'pass' as const,
          level: p.person === ADMIN ? 1 : 2,
          by: { userId: p.person.userId, displayName: p.person.displayName },
          at: p.at,
          comment: p.comment
        }))
      ]
    };
  }

  pass(person: Person, body: PassRequest, at: string): CommandResult {
    this.passes.push(body);
    this.passed.push({ person, at, comment: body.comment ?? null });
    return ok('301', body.requestKey, this.status() === 'approved' ? 'approved' : 'pending', this.level());
  }
}

// ============================================================ E39：物料清单改价审批（C06 7.10），审批 203

const E39_FLOW_STEP: Step = {
  level: 1,
  flow: 'GOODS_TO_COST',
  flowName: '物料清单改价审批',
  node: '管理员审批',
  mode: 'or',
  status: 'pending',
  members: [member('ADMIN', '系统管理员')]
};

/** 取消 2556 之后的 view：C09 第 6 节的样例（只保留 GOODS_TO_COST 一个审批流） */
export function e39PreviewView(): View {
  const view = structuredClone(approvalDetailSample.view);
  view.master.rows[0].flows = ['GOODS_TO_COST'];
  return view;
}

export const E39_INITIAL_FINGERPRINT = `sha256:${'1'.repeat(64)}`;
export const E39_PREVIEW_FINGERPRINT = approvalDetailSample.fingerprint;

/** 打开详情时的 view：默认全选，2556 也显示 75.00 → 80.00、23.25 → 24.80（0.31 × 80，单价、金额的 precision 为 2） */
export function e39InitialView(): View {
  const view = e39PreviewView();
  const rows = view.affected[0].rows;
  const k2556 = rows.find(r => r.ref?.key === '103681') as Row;
  k2556.op = 'modify';
  k2556.checked = true;
  k2556.cells[3] = c('75.00', '80.00');
  k2556.cells[4] = c('23.25', '24.80');
  k2556.cells[5] = c('1.1566', '1.1721');
  k2556.cells[6] = c('689.03', '688.50');
  return view;
}

export class E39Backend {
  approved = false;
  readonly previews: PreviewRequest[] = [];
  readonly passes: PassRequest[] = [];

  detail(person: Person): ApprovalDetail {
    const mine = person === ADMIN && !this.approved;
    return {
      ...structuredClone(approvalDetailSample),
      status: this.approved ? 'approved' : 'pending',
      steps: [
        this.approved
          ? { ...E39_FLOW_STEP, status: 'passed', members: [member('ADMIN', '系统管理员', passedBy(ADMIN, '2026-10-29T10:00:00'))] }
          : structuredClone(E39_FLOW_STEP)
      ],
      view: e39InitialView(),
      fingerprint: E39_INITIAL_FINGERPRINT,
      actions: { canPass: mine, canReject: mine, canWithdraw: false }
    };
  }

  /** 按提交的勾选返回：不含 103681 时为取消 2556 之后的结果，否则为全选的结果 */
  preview(body: PreviewRequest) {
    this.previews.push(body);
    const keys = (body.checkedRows ?? []).map(r => r.key);
    if (keys.includes('103681')) return { view: e39InitialView(), fingerprint: E39_INITIAL_FINGERPRINT };
    return { view: e39PreviewView(), fingerprint: E39_PREVIEW_FINGERPRINT };
  }

  pass(_person: Person, body: PassRequest): CommandResult {
    this.passes.push(body);
    this.approved = true;
    return ok('203', body.requestKey, 'approved', 1);
  }
}

// ============================================================ 装上替身的 ShellApi

interface Backend {
  detail(person: Person): ApprovalDetail;
  pass(person: Person, body: PassRequest, at: string): CommandResult;
  preview?(body: PreviewRequest): unknown;
}

/** 以某个账号登录的 ShellApi，审批接口由 backend 回答 */
export function shellFor(person: Person, role: (typeof ROLES)[keyof typeof ROLES], backend: Backend, at = '2026-10-29T10:00:00') {
  const fake = createFakeShell({ user: person, role });
  fake.http.on('GET', '/api/approvals/:approvalId', () => backend.detail(person));
  fake.http.on('POST', '/api/approvals/:approvalId/pass', (call: FakeCall) => backend.pass(person, call.body as PassRequest, at));
  if (backend.preview) {
    fake.http.on('POST', '/api/approvals/:approvalId/preview', (call: FakeCall) => backend.preview!(call.body as PreviewRequest));
  }
  return fake;
}
