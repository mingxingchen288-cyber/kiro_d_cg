/**
 * 人员管理、部门管理的高级查询（FM-06；C09 v15 `GET /api/admin/accounts`、`/api/admin/departments` 的 `advanced`）。
 *
 * 同旧系统这两个通用页的"高级查询"（cmx `T_COST_PAGE_COMPONENT` 的 user-manage、dept-manage 工具栏 `advancedSearch`，
 * 对话框 `cost-web/src/v3/components/AdvancedSearchDialog.vue`）：一打开就列出勾了"查询"的列（`T_COST_COLUMN_METADATA.SEARCHABLE`）
 * 的条件，填了值自动勾上，可以隐藏条件、在"显示字段"里恢复；底部"已启用 N 项"、重置、取消、查询。运算符和默认运算符
 * 同 frontend-page 的高级查询（FP-22，旧 `useAdvancedSearch.ts`）；模块之间不能互相导入，这里按同样的写法另写一份。
 *
 * 可查的列是旧页面勾了"查询"、新表格上也有的：人员的 ID、用户名、姓名、部门、状态，部门的 ID、部门名称。
 * 旧页面的邮箱、电话、部门编码新平台没有；旧人员页的"部门ID"（Lookup）和"部门名称"两列在新表格合成一列"部门"，
 * 条件里从部门列表中选（等于、不等于、IN、NOT IN、为空、不为空）。旧对话框没有"添加条件"和条件之间的"或"，这里也没有。
 */
import type { AdvancedCondition, AdvancedQuery } from '../../contracts/http';

export type SearchFieldType = 'number' | 'text' | 'select' | 'boolean';

export interface SearchField {
  /** C09 v15 `advanced` 的字段名 */
  name: string;
  label: string;
  type: SearchFieldType;
}

export type SearchOption = { label: string; value: string };

/** 人员管理能查的列（旧 CostUser 的 ID、USERNAME、REAL_NAME、DEPARTMENT_ID/DEPT_NAME、STATUS） */
export const ACCOUNT_SEARCH_FIELDS: SearchField[] = [
  { name: 'userId', label: 'ID', type: 'number' },
  { name: 'username', label: '用户名', type: 'text' },
  { name: 'displayName', label: '姓名', type: 'text' },
  { name: 'departmentId', label: '部门', type: 'select' },
  { name: 'enabled', label: '状态', type: 'boolean' }
];

/** 部门管理能查的列（旧 CostDepartment 的 ID、DEPT_NAME） */
export const DEPARTMENT_SEARCH_FIELDS: SearchField[] = [
  { name: 'departmentId', label: 'ID', type: 'number' },
  { name: 'name', label: '部门名称', type: 'text' }
];

/** 状态的选项：启用、停用 */
export const ENABLED_OPTIONS: SearchOption[] = [
  { label: '启用', value: 'true' },
  { label: '停用', value: 'false' }
];

export type OperatorOption = SearchOption;

const NUMBER_OPERATORS: OperatorOption[] = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '大于', value: 'gt' },
  { label: '大于等于', value: 'ge' },
  { label: '小于', value: 'lt' },
  { label: '小于等于', value: 'le' },
  { label: '包含', value: 'like' },
  { label: '不包含', value: 'notLike' },
  { label: '介于', value: 'between' },
  { label: '不介于', value: 'notBetween' },
  { label: 'IN', value: 'in' },
  { label: 'NOT IN', value: 'notIn' },
  { label: '为空', value: 'isNull' },
  { label: '不为空', value: 'isNotNull' }
];

const TEXT_OPERATORS: OperatorOption[] = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '包含', value: 'like' },
  { label: '不包含', value: 'notLike' },
  { label: 'IN', value: 'in' },
  { label: 'NOT IN', value: 'notIn' },
  { label: '为空', value: 'isNull' },
  { label: '不为空', value: 'isNotNull' }
];

const SELECT_OPERATORS: OperatorOption[] = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: 'IN', value: 'in' },
  { label: 'NOT IN', value: 'notIn' },
  { label: '为空', value: 'isNull' },
  { label: '不为空', value: 'isNotNull' }
];

const BOOLEAN_OPERATORS: OperatorOption[] = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' }
];

export function operatorsFor(type: SearchFieldType): OperatorOption[] {
  if (type === 'number') return NUMBER_OPERATORS;
  if (type === 'select') return SELECT_OPERATORS;
  if (type === 'boolean') return BOOLEAN_OPERATORS;
  return TEXT_OPERATORS;
}

/** 默认运算符（同旧系统 getDefaultOperator）：文本为包含，其他为等于 */
export const defaultOperator = (type: SearchFieldType) => (type === 'text' ? 'like' : 'eq');

export const needsNoValue = (operator: string) => operator === 'isNull' || operator === 'isNotNull';
export const needsTwoValues = (operator: string) => operator === 'between' || operator === 'notBetween';
export const takesList = (operator: string) => operator === 'in' || operator === 'notIn';

/** IN、NOT IN 的值：逗号分隔，中英文逗号都可以（同旧系统 splitInValue） */
export const splitList = (text: string) =>
  text
    .split(/[,，]/)
    .map(v => v.trim())
    .filter(Boolean);

/** 对话框中的一行条件 */
export interface ConditionDraft {
  /** 字段名，一个字段一行 */
  key: string;
  field: string;
  operator: string;
  value: string;
  /** 介于的第二个值 */
  value2: string;
  /** 勾上的条件才参与查询 */
  enabled: boolean;
  /** 隐藏的条件在"显示字段"中恢复 */
  visible: boolean;
}

/** 预置条件：每个能查的列一行，按列的顺序 */
export function presetConditions(fields: SearchField[]): ConditionDraft[] {
  return fields.map(field => ({
    key: field.name,
    field: field.name,
    operator: defaultOperator(field.type),
    value: '',
    value2: '',
    enabled: false,
    visible: true
  }));
}

/** 条件有没有值：为空、不为空不要值；介于要两个值 */
export function hasValue(draft: ConditionDraft) {
  if (needsNoValue(draft.operator)) return true;
  if (needsTwoValues(draft.operator)) return draft.value.trim() !== '' && draft.value2.trim() !== '';
  if (takesList(draft.operator)) return splitList(draft.value).length > 0;
  return draft.value.trim() !== '';
}

/** 填值（`second` 为介于的第二个值）：有值就勾上，没值就取消（同旧系统 markEnabled） */
export function setValue(draft: ConditionDraft, value: string | null, second = false) {
  if (second) draft.value2 = value ?? '';
  else draft.value = value ?? '';
  draft.enabled = hasValue(draft);
}

/**
 * 换运算符（同旧系统 handleOperatorChange）：不是介于时清空第二个值，为空、不为空清空值；下拉选择的字段从 IN 换成
 * 单个值的运算符时只留第一个值。勾选不变（为空、不为空要自己勾上，同旧系统）。
 */
export function setOperator(draft: ConditionDraft, operator: string, picked = false) {
  draft.operator = operator;
  if (!needsTwoValues(operator)) draft.value2 = '';
  if (needsNoValue(operator)) draft.value = '';
  else if (!takesList(operator) && picked) draft.value = splitList(draft.value)[0] ?? '';
}

/** 隐藏条件：清空值、取消勾选（同旧系统 hideCondition） */
export function hideCondition(draft: ConditionDraft) {
  draft.value = '';
  draft.value2 = '';
  draft.enabled = false;
  draft.visible = false;
}

/** 重置：清空值和勾选，运算符和隐藏不变（同旧系统 clearSearch），之后按没有条件重新查询 */
export function resetConditions(drafts: ConditionDraft[]): ConditionDraft[] {
  return drafts.map(d => ({ ...d, value: '', value2: '', enabled: false }));
}

function active(fields: SearchField[], drafts: ConditionDraft[]) {
  return drafts.filter(d => d.visible && d.enabled && hasValue(d) && fields.some(f => f.name === d.field));
}

/** "已启用 N 项" */
export const enabledCount = (fields: SearchField[], drafts: ConditionDraft[]) => active(fields, drafts).length;

/** 对话框中的条件转成 C09 v15 的 `advanced`（同 C09 第 4 节，条件之间为且）；没有参与查询的条件时为 null */
export function buildAdvanced(fields: SearchField[], drafts: ConditionDraft[]): AdvancedQuery | null {
  const conditions: AdvancedCondition[] = active(fields, drafts).map(draft => {
    const field = fields.find(f => f.name === draft.field)!;
    let value: AdvancedCondition['value'];
    if (needsNoValue(draft.operator)) value = null;
    else if (needsTwoValues(draft.operator)) value = [draft.value.trim(), draft.value2.trim()];
    else if (takesList(draft.operator)) value = splitList(draft.value);
    else value = field.type === 'boolean' ? draft.value === 'true' : draft.value.trim();
    return { field: field.name, operator: draft.operator, value };
  });
  return conditions.length ? { op: 'and', conditions } : null;
}
