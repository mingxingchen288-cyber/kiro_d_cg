/**
 * 审批流配置（FC-05、C06 第 7 节 v17）在编辑界面中的行结构，以及与配置项 `content` 的互转。
 *
 * 界面沿用旧系统 SectionApproval.vue：流程列表一行一个审批流；三个 Tab 各是一张表：
 * - 审批节点：一行一个节点，带"级别"列（同旧系统的审批入口），保存时按级别合成 `levels`；
 * - 冻结节点：一行一项 `freeze`；
 * - 展示数据：一行一块 `display`。
 * `toContent` 只写出有值的可选字段（C06 第 1.1 节），必须写的字段总是写出。
 */
import type {
  ApprovalFlowContent,
  Approver,
  BlockAction,
  DisplayBlock,
  DisplayColumn,
  FlowNode,
  FlowParam,
  NotifyRule,
  RowOp
} from '../core/types';
import { plain } from '../core/store';

export const ROW_OPS: RowOp[] = ['add', 'modify', 'delete'];
export const ROW_OP_LABELS: Record<RowOp, string> = { add: '新增', modify: '修改', delete: '删除' };

let sequence = 0;
export const rowId = (prefix: string) => `${prefix}-${++sequence}`;

export interface NodeRow {
  _id: string;
  level: number;
  name: string;
  conditionType: 'always' | 'sql';
  condition: string;
  department: string | null;
  approvers: Approver[];
  mode: 'or' | 'and';
  enabled: boolean;
}

export interface FreezeRow {
  _id: string;
  enabled: boolean;
  table: string;
  condition: string;
}

export interface DisplayRow {
  _id: string;
  key: string;
  title: string;
  region: 'master' | 'detail' | 'affected';
  source: string;
  condition: string;
  targetTable: string;
  keyColumn: string;
  columns: DisplayColumn[];
  selection: 'checked' | 'all' | 'hidden' | null;
  actions: BlockAction[];
}

export interface FlowDraft {
  _key: string;
  /** 配置项编码 */
  key: string;
  name: string;
  /** 已保存的版本；新建未保存时为 null */
  version: number | null;
  dirty: boolean;
  page: string;
  order: number;
  enabled: boolean;
  operations: Record<string, RowOp[]>;
  nodes: NodeRow[];
  freeze: FreezeRow[];
  display: DisplayRow[];
  params: FlowParam[];
  notify: NotifyRule[];
}

export function newNode(level = 1): NodeRow {
  return {
    _id: rowId('node'),
    level,
    name: '新审批节点',
    conditionType: 'always',
    condition: '',
    department: null,
    approvers: [],
    mode: 'or',
    enabled: true
  };
}

export function newFreeze(): FreezeRow {
  return { _id: rowId('freeze'), enabled: true, table: '', condition: '' };
}

export function newDisplay(region: DisplayRow['region'], source: string, key: string): DisplayRow {
  return {
    _id: rowId('display'),
    key,
    title: '修改内容',
    region,
    source,
    condition: '',
    targetTable: '',
    keyColumn: '',
    columns: [],
    selection: region === 'affected' ? 'checked' : null,
    actions: []
  };
}

export function fromContent(key: string, name: string, version: number | null, content: ApprovalFlowContent): FlowDraft {
  const nodes: NodeRow[] = [];
  for (const level of content.levels ?? []) {
    for (const node of level.nodes) {
      nodes.push({
        _id: rowId('node'),
        level: level.level,
        name: node.name,
        conditionType: node.conditionType,
        condition: node.condition ?? '',
        department: node.department ?? null,
        approvers: plain(node.approvers ?? []),
        mode: node.mode,
        enabled: node.enabled ?? true
      });
    }
  }
  return {
    _key: rowId('flow'),
    key,
    name,
    version,
    dirty: false,
    page: content.page,
    order: content.order,
    enabled: content.enabled ?? true,
    operations: plain(content.operations ?? {}),
    nodes,
    freeze: (content.freeze ?? []).map(f => ({
      _id: rowId('freeze'),
      enabled: f.enabled ?? true,
      table: f.table,
      condition: f.condition
    })),
    display: (content.display ?? []).map(b => ({
      _id: rowId('display'),
      key: b.key,
      title: b.title,
      region: b.region,
      source: b.source,
      condition: b.condition ?? '',
      targetTable: b.targetTable ?? '',
      keyColumn: b.keyColumn ?? '',
      columns: plain(b.columns ?? []),
      selection: b.selection ?? null,
      actions: plain(b.actions ?? [])
    })),
    params: plain(content.params ?? []),
    notify: plain(content.notify ?? [])
  };
}

function cleanColumn(column: DisplayColumn): DisplayColumn {
  const out: DisplayColumn = { field: column.field.trim(), label: column.label.trim() || column.field.trim() };
  if (column.precision !== null && column.precision !== undefined && String(column.precision) !== '')
    out.precision = Number(column.precision);
  if (column.width !== null && column.width !== undefined && String(column.width) !== '') out.width = Number(column.width);
  if (column.targetColumn) out.targetColumn = column.targetColumn.trim();
  return out;
}

function cleanNode(row: NodeRow): FlowNode {
  const node: FlowNode = { name: row.name, conditionType: row.conditionType, approvers: [], mode: row.mode };
  if (row.conditionType === 'sql') node.condition = row.condition.trim();
  node.department = row.department || null;
  node.approvers = plain(row.approvers);
  node.mode = row.mode;
  node.enabled = row.enabled;
  return node;
}

function cleanBlock(row: DisplayRow): DisplayBlock {
  const block: DisplayBlock = { key: row.key.trim(), title: row.title, region: row.region, source: row.source.trim(), columns: [] };
  if (row.condition.trim()) block.condition = row.condition.trim();
  if (row.region === 'affected') {
    if (row.targetTable.trim()) block.targetTable = row.targetTable.trim();
    if (row.keyColumn.trim()) block.keyColumn = row.keyColumn.trim();
  }
  block.columns = row.columns.map(cleanColumn);
  if (row.region === 'affected') {
    block.selection = row.selection ?? 'checked';
    block.actions = plain(row.actions);
  }
  return block;
}

/** 编辑界面的行 → 配置项内容（C06 7.1） */
export function toContent(draft: FlowDraft): ApprovalFlowContent {
  const levels = [...new Set(draft.nodes.map(n => Number(n.level)))]
    .sort((a, b) => a - b)
    .map(level => ({ level, nodes: draft.nodes.filter(n => Number(n.level) === level).map(cleanNode) }));
  const operations: Record<string, RowOp[]> = {};
  for (const [table, ops] of Object.entries(draft.operations)) {
    const sorted = ROW_OPS.filter(op => ops.includes(op));
    if (sorted.length) operations[table] = sorted;
  }
  const content: ApprovalFlowContent = {
    page: draft.page,
    order: Number(draft.order),
    enabled: draft.enabled,
    operations,
    levels,
    freeze: draft.freeze.map(f => ({ table: f.table.trim(), condition: f.condition.trim(), enabled: f.enabled })),
    display: draft.display.map(cleanBlock)
  };
  if (draft.params.length) content.params = plain(draft.params);
  content.propagation = 'end';
  content.notify = plain(draft.notify);
  return content;
}

/** 流程列表"审核操作"列：按页面表格的顺序，例如"原辅料.新增、原辅料.修改、包材.新增、包材.修改" */
export function operationsSummary(operations: Record<string, RowOp[]>, tables: Array<{ entity: string; title: string }>) {
  const known = tables.map(t => t.entity);
  const order = [...known, ...Object.keys(operations).filter(k => !known.includes(k))];
  const parts = order.flatMap(entity => {
    const title = tables.find(t => t.entity === entity)?.title ?? entity;
    return ROW_OPS.filter(op => operations[entity]?.includes(op)).map(op => `${title}.${ROW_OP_LABELS[op]}`);
  });
  return parts.join('、');
}

export function approverSummary(approvers: Approver[], roles: Array<{ label: string; value: string }>, users: Array<{ label: string; value: string }>) {
  if (!approvers.length) return '双击配置审批人';
  return approvers
    .map(a => {
      if (a.type === 'sql') return 'SQL 选人';
      if (a.type === 'role') return `角色：${roles.find(r => r.value === a.role)?.label ?? a.role}`;
      return `人员：${users.find(u => u.value === a.userId)?.label ?? a.userId}`;
    })
    .join('；');
}

export function conditionSummary(row: { conditionType: 'always' | 'sql'; condition: string }) {
  return row.conditionType === 'always' ? '始终满足' : row.condition || '双击配置条件';
}

export function actionsSummary(actions: BlockAction[]) {
  if (!actions.length) return '双击配置通过后的操作';
  return actions
    .map(a => {
      if (a.action === 'updateFields') return `修改 ${a.fields.map(f => f.column).join('、') || '待选字段'}`;
      if (a.action === 'insertRows') return `新增到 ${a.table || '待填表'}`;
      if (a.action === 'deleteRows') return '删除这一行';
      return `逃生舱 ${a.operation || '待选操作'}`;
    })
    .join('；');
}

export function columnsSummary(columns: DisplayColumn[]) {
  return columns.map(c => c.label || c.field).join('、') || '双击配置显示列';
}
