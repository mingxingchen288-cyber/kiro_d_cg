/**
 * 角色权限（C06 第 8 节、FC-04），对照旧系统 `views/_builtin/permission/index.vue`：
 * - 页面权限树：勾选页面授权，已授权的页面可以"配置按钮""配置列""配置行"；
 * - 按钮权限：全部按钮（`["*"]`），或者勾选页面级的保存、高级查询（`system:save`），每个区域的新增、删除、修改
 *   （`master:modify`、`COST_MATERIAL:addRow`，C06 v24 第 8 节），其余区域按钮（`master:copyRow`）和导出（`export:<编码>`）；
 * - 列权限：按区域列出字段的可见、可编辑（C06 另允许增加必填），只能收紧；
 * - 行权限：可视化配置或自定义 SQL；可视化条件生成的 SQL 与旧系统 generateSqlFromConditions 相同。
 */
import type { CompareOp, FieldFlags, Logic, PageContent, RolePage, RowConditionItem, VisualRowPolicy } from '../core/types';

export const ROW_OP_OPTIONS: Array<{ label: string; value: CompareOp }> = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '大于', value: 'gt' },
  { label: '大于等于', value: 'ge' },
  { label: '小于', value: 'lt' },
  { label: '小于等于', value: 'le' },
  { label: '包含', value: 'like' },
  { label: '属于', value: 'in' },
  { label: '为空', value: 'isNull' },
  { label: '不为空', value: 'isNotNull' }
];

export const DYNAMIC_VALUE_OPTIONS = [
  { label: '当前用户', value: '${username}' },
  { label: '当前用户ID', value: '${userId}' }
];

function formatSqlValue(value: string, valueType: 'static' | 'dynamic') {
  if (valueType === 'dynamic') return value;
  if (/^-?\d+(\.\d+)?$/.test(value)) return value;
  return `'${value.replace(/'/g, "''")}'`;
}

/** 可视化条件 → SQL 条件（同旧系统） */
export function generateRowSql(logic: Logic, conditions: RowConditionItem[]) {
  const parts = conditions
    .map(cond => {
      const field = cond.field;
      const value = String(cond.value ?? '');
      switch (cond.op) {
        case 'eq':
          return `${field} = ${formatSqlValue(value, cond.valueType)}`;
        case 'ne':
          return `${field} <> ${formatSqlValue(value, cond.valueType)}`;
        case 'gt':
          return `${field} > ${formatSqlValue(value, cond.valueType)}`;
        case 'ge':
          return `${field} >= ${formatSqlValue(value, cond.valueType)}`;
        case 'lt':
          return `${field} < ${formatSqlValue(value, cond.valueType)}`;
        case 'le':
          return `${field} <= ${formatSqlValue(value, cond.valueType)}`;
        case 'like':
          return `${field} LIKE '%${value.replace(/'/g, "''")}%'`;
        case 'in':
          return `${field} IN (${value
            .split(',')
            .map(v => formatSqlValue(v.trim(), cond.valueType))
            .join(', ')})`;
        case 'isNull':
          return `${field} IS NULL`;
        case 'isNotNull':
          return `${field} IS NOT NULL`;
        default:
          return '';
      }
    })
    .filter(Boolean);
  return parts.join(` ${logic} `);
}

export interface RowPolicyForm {
  mode: 'visual' | 'sql';
  logic: Logic;
  conditions: RowConditionItem[];
  sql: string;
}

export function rowPolicyForm(rows: RolePage['rows']): RowPolicyForm {
  if (typeof rows === 'string') return { mode: 'sql', logic: 'AND', conditions: [], sql: rows };
  if (rows) return { mode: 'visual', logic: rows.logic, conditions: JSON.parse(JSON.stringify(rows.conditions)), sql: '' };
  return { mode: 'visual', logic: 'AND', conditions: [], sql: '' };
}

/** 表单 → C06 `rows`；没有条件、SQL 为空时为 null（可以访问全部行） */
export function rowPolicyValue(form: RowPolicyForm): VisualRowPolicy | string | null {
  if (form.mode === 'sql') return form.sql.trim() || null;
  const conditions = form.conditions
    .filter(c => c.field)
    .map(c => {
      const item: RowConditionItem = { field: c.field, fieldLabel: c.fieldLabel, op: c.op, valueType: c.valueType };
      if (c.op !== 'isNull' && c.op !== 'isNotNull') item.value = c.value ?? '';
      return item;
    });
  if (!conditions.length) return null;
  return { mode: 'visual', logic: form.logic, conditions, sql: generateRowSql(form.logic, conditions) };
}

export interface ButtonChoice {
  key: string;
  label: string;
}

export interface ButtonGroup {
  groupName: string;
  buttons: ButtonChoice[];
}

/** 页面级的权限：保存（没有时整页只读）、高级查询 */
export const PAGE_BUTTONS: ButtonChoice[] = [
  { key: 'system:save', label: '保存' },
  { key: 'system:advancedSearch', label: '高级查询' }
];

/** 区域的新增、删除、修改（C06 v24 第 8 节，用户 2026-10-30"控制到明细级别"），权限键为 `<区域>:<动作>` */
export const ROW_ACTIONS = [
  { action: 'addRow', label: '新增' },
  { action: 'deleteRow', label: '删除' },
  { action: 'modify', label: '修改' }
] as const;

export interface AreaPermissionRow {
  /** `master` 或明细实体编码 */
  area: string;
  /** 主表为"主表"，明细取页面配置中的标题，例如"原料/辅料""包材" */
  title: string;
  /** 依次为新增、删除、修改的权限键 */
  choices: ButtonChoice[];
}

const MASTER_TITLE = '主表';

/** 增删改表：一行一个区域，主表在前，明细按页面配置的顺序；单表页只有主表 */
export function areaPermissionRows(page: PageContent): AreaPermissionRow[] {
  const areas = [
    { area: 'master', title: MASTER_TITLE },
    ...(page.details ?? []).map(d => ({ area: d.entity, title: d.title }))
  ];
  return areas.map(a => ({ ...a, choices: ROW_ACTIONS.map(r => ({ key: `${a.area}:${r.action}`, label: r.label })) }));
}

const inMatrix = (action: string) => action === 'addRow' || action === 'deleteRow';

/** 其余的区域按钮（复制、业务按钮、保存列配置，分组显示区域标题）和导出配置；新增、删除在增删改表中 */
export function buttonGroups(page: PageContent, exports: Array<{ key: string; name: string }>): ButtonGroup[] {
  const choices = (area: string, buttons: Array<{ action: string; label: string }> | undefined) =>
    (buttons ?? []).filter(b => !inMatrix(b.action)).map(b => ({ key: `${area}:${b.action}`, label: b.label }));
  const groups: ButtonGroup[] = [{ groupName: MASTER_TITLE, buttons: choices('master', page.master.buttons) }];
  for (const detail of page.details ?? [])
    groups.push({ groupName: detail.title, buttons: choices(detail.entity, detail.buttons) });
  if (exports.length) groups.push({ groupName: '导出', buttons: exports.map(e => ({ key: `export:${e.key}`, label: e.name })) });
  return groups.filter(g => g.buttons.length);
}

export interface ColumnRow {
  field: string;
  label: string;
  /** 页面和实体给出的基线：基线不可见的不能设为可见，基线不可编辑的不能设为可编辑 */
  baseVisible: boolean;
  baseEditable: boolean;
  visible: boolean;
  editable: boolean;
  required: boolean;
}

/** 列权限表的一行一个字段；`policy` 为 role 中该区域已有的设置 */
export function columnRows(
  fields: Array<{ name: string; label: string; role: string; source: string }>,
  base: Record<string, FieldFlags>,
  policy: Record<string, FieldFlags> | undefined
): ColumnRow[] {
  return fields.map(f => {
    const b = base[f.name] ?? {};
    const baseVisible = b.visible !== false;
    const baseEditable = b.editable !== false && f.role === 'input';
    const p = policy?.[f.name] ?? {};
    return {
      field: f.name,
      label: f.label,
      baseVisible,
      baseEditable,
      visible: baseVisible && p.visible !== false,
      editable: baseEditable && p.editable !== false,
      required: p.required === true
    };
  });
}

/** 列权限表 → C06 `columns` 中一个区域：只写比基线收紧的字段（同 C06 样例，写出 visible、editable） */
export function columnPolicy(rows: ColumnRow[]): Record<string, FieldFlags> {
  const out: Record<string, FieldFlags> = {};
  for (const row of rows) {
    const changed = row.visible !== row.baseVisible || row.editable !== row.baseEditable || row.required;
    if (!changed) continue;
    const flags: FieldFlags = { visible: row.visible, editable: row.visible && row.editable };
    if (row.required) flags.required = true;
    out[row.field] = flags;
  }
  return out;
}
