/**
 * 审批详情和待办的显示文字（不引用 Vue 组件和 AG Grid）：状态、"A → B"、"变化"和"触发审批"列、审批进度的从表。
 * 文字沿用旧系统 `ApprovalDetailDialog.vue`、`ApprovalPresentationGrid.vue`；"随审批等待"取自 FA-06。
 */
import type { ApprovalDetail, ApprovalSummary } from '../../contracts/http';

export type ApprovalView = ApprovalDetail['view'];
export type ViewMasterTable = ApprovalView['master'];
export type ViewDetailTable = ApprovalView['details'][number];
export type ViewAffectedTable = ApprovalView['affected'][number];
export type ViewRow = ViewMasterTable['rows'][number];
export type ViewCell = ViewRow['cells'][number];
export type ApprovalStep = ApprovalDetail['steps'][number];
export type StepMember = ApprovalStep['members'][number];

export const APPROVAL_STATUS: Record<ApprovalDetail['status'], string> = {
  pending: '审批中',
  approved: '已通过',
  rejected: '已驳回',
  withdrawn: '已撤回'
};

export const STEP_STATUS: Record<ApprovalStep['status'], string> = {
  passed: '已通过',
  pending: '待处理',
  rejected: '已驳回',
  upcoming: '预计进入'
};

export const MEMBER_STATUS: Record<StepMember['status'], string> = {
  passed: '已通过',
  pending: '待处理',
  rejected: '已驳回'
};

export const MODE: Record<ApprovalStep['mode'], string> = { or: '或签', and: '会签' };

/** 来源单据明细的"变化"列 */
export const OP_LABEL: Record<ViewRow['op'], string> = { add: '新增', delete: '删除', modify: '修改', none: '未修改' };

/** "触发审批"列为空时（这一行没有触发审批流，随审批等待） */
export const WAITING = '随审批等待';

export const EMPTY = '—';

/** 日期时间按 C01 第 4 节的格式给出，显示时把 T 换成空格 */
export function formatTime(text: string | null | undefined) {
  return text ? text.replace('T', ' ') : EMPTY;
}

/** 顶部状态："审批中 · 第 1 级" */
export function statusLabel(item: Pick<ApprovalDetail, 'status' | 'currentLevel'>) {
  return `${APPROVAL_STATUS[item.status] ?? item.status} · 第 ${item.currentLevel} 级`;
}

export function summaryStatus(item: Pick<ApprovalSummary, 'status' | 'level'>) {
  return `${APPROVAL_STATUS[item.status] ?? item.status} · 第 ${item.level} 级`;
}

/** 来源单据号：`25（聚维酮K30）` */
export function sourceText(source: ApprovalSummary['source']) {
  return source.label ? `${source.recordKey}（${source.label}）` : source.recordKey;
}

/** 来自页面：`物料清单及成本（保存）` */
export function pageText(item: Pick<ApprovalSummary, 'pageTitle' | 'operationLabel'>) {
  return `${item.pageTitle}（${item.operationLabel}）`;
}

export function valueText(value: ViewCell['before']) {
  if (value === null || value === undefined || value === '') return EMPTY;
  if (typeof value === 'boolean') return value ? '是' : '否';
  return value;
}

/** 单元格文字：新增只显示新值，删除显示删除前的值；前后相同时只显示当前值，不同时显示"A → B"（C06 7.6） */
export function cellText(cell: ViewCell, op: ViewRow['op']) {
  if (op === 'add') return valueText(cell.after);
  if (op === 'delete') return valueText(cell.before);
  const before = valueText(cell.before);
  const after = valueText(cell.after);
  return before === after ? after : `${before} → ${after}`;
}

/** 改了的格子用橙色框显示（新增、删除行不标） */
export function cellChanged(cell: ViewCell, op: ViewRow['op']) {
  return op !== 'add' && op !== 'delete' && valueText(cell.before) !== valueText(cell.after);
}

/** 表格中的一行 */
export interface GridRowModel {
  id: string;
  /** 受影响单据：这一行所属修改表的主键（`ref.key`，主键相同的后续行沿用第一行的）；来源单据、记录已不存在的行为 null */
  key: string | null;
  /** 是否为这个主键的第一行（带勾选框） */
  lead: boolean;
  op: ViewRow['op'];
  /** 记录已不存在（FA-09） */
  missing: boolean;
  texts: string[];
  changed: boolean[];
  /** "变化"列 */
  change: string;
  /** "触发审批"列：这一行触发的审批流编码 */
  flows: string[];
}

/**
 * 把 C09 的行转成表格行。主键相同的几行只有第一行带 `ref`（C09 第 6 节），后面不带 `ref` 的行属于前一个主键，
 * 表格中合并这些行的勾选框和相同的格子（同旧系统 `ApprovalPresentationGrid` 的 rowSpan）。
 */
export function gridRows(rows: readonly ViewRow[]): GridRowModel[] {
  let current: string | null = null;
  return rows.map((row, index) => {
    const missing = row.missing === true;
    const lead = Boolean(row.ref);
    if (row.ref) current = row.ref.key;
    else if (missing) current = null;
    return {
      id: `r${index}`,
      key: missing ? null : current,
      lead,
      op: row.op,
      missing,
      texts: row.cells.map(cell => cellText(cell, row.op)),
      changed: row.cells.map(cell => cellChanged(cell, row.op)),
      change: OP_LABEL[row.op] ?? row.op,
      flows: row.flows ?? []
    };
  });
}

/** "触发审批"列的文字：审批流名称用"、"连接；没有触发时为"随审批等待" */
export function triggerLabel(flows: readonly string[], names: ReadonlyMap<string, string>) {
  return flows.length ? flows.map(flow => names.get(flow) ?? flow).join('、') : WAITING;
}

/** 审批流编码 → 名称，取自 `steps`（每个审批流至少有第 1 级的节点） */
export function flowNameMap(steps: readonly ApprovalStep[]) {
  const names = new Map<string, string>();
  for (const step of steps) if (!names.has(step.flow)) names.set(step.flow, step.flowName);
  return names;
}

/** 审批进度从表的一行：按 `steps` 每个节点一行（FA-06） */
export interface StepRow {
  level: number;
  node: string;
  mode: string;
  /** 审批人及各自的处理情况：会签时每个人分别显示 */
  approvers: string;
  flowName: string;
  status: string;
  time: string;
  comment: string;
}

function memberText(member: StepMember) {
  const prefix = member.type === 'role' ? '角色：' : '';
  const by = member.processedBy ? `，${member.processedBy.displayName}` : '';
  return `${prefix}${member.name}（${MEMBER_STATUS[member.status] ?? member.status}${by}）`;
}

function joined(values: Array<string | null | undefined>) {
  const items = [...new Set(values.filter((v): v is string => Boolean(v)))];
  return items.length ? items.join('、') : EMPTY;
}

export function stepRows(steps: readonly ApprovalStep[]): StepRow[] {
  return steps.map(step => {
    const passed = step.members.filter(m => m.status === 'passed').length;
    // 会签进行中：显示已通过几人
    const progress = step.mode === 'and' && step.status === 'pending' && step.members.length > 1 ? `（已通过 ${passed}/${step.members.length}）` : '';
    return {
      level: step.level,
      node: step.node,
      mode: MODE[step.mode] ?? step.mode,
      approvers: step.members.map(memberText).join('、'),
      flowName: step.flowName,
      status: `${STEP_STATUS[step.status] ?? step.status}${progress}`,
      time: joined(step.members.map(m => (m.processedAt ? formatTime(m.processedAt) : null))),
      comment: joined(
        step.members.map(m => (m.comment ? `${m.processedBy?.displayName ?? m.name}：${m.comment}` : null))
      )
    };
  });
}

/** 错误提示：PlatformError 的消息和明细（同旧系统 approvalErrorMessage，保留后端给出的业务错误） */
export function errorText(error: unknown) {
  if (error && typeof error === 'object' && 'message' in error) {
    const details = (error as { details?: Array<{ message: string | null }> }).details ?? [];
    const lines = details.map(d => d.message).filter((m): m is string => Boolean(m));
    return [String((error as { message: unknown }).message), ...lines].join('；');
  }
  return String(error);
}
