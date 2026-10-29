/**
 * 高级查询（C09 第 4 节 ListRequest.advanced，queries-export QE-12）：条件不写 `entity` 时属于主表；同一明细实体的
 * 条件由同一条明细行同时满足，`group`、`logic` 用于组内的且、或。运算符与旧系统 AdvancedSearchDialog.vue 相同，
 * 只用可见字段（C05）。
 */
import type { AdvancedCondition, AdvancedQuery } from '../../contracts/http';
import type { FieldType, PageView } from '../../contracts/page-view';

export type OperatorOption = { label: string; value: string };

const NUMBER_OPERATORS: OperatorOption[] = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '大于', value: 'gt' },
  { label: '大于等于', value: 'ge' },
  { label: '小于', value: 'lt' },
  { label: '小于等于', value: 'le' },
  { label: '介于', value: 'between' },
  { label: '不介于', value: 'notBetween' },
  { label: 'IN', value: 'in' },
  { label: 'NOT IN', value: 'notIn' },
  { label: '为空', value: 'isNull' },
  { label: '不为空', value: 'isNotNull' }
];

const DATE_OPERATORS: OperatorOption[] = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '大于', value: 'gt' },
  { label: '大于等于', value: 'ge' },
  { label: '小于', value: 'lt' },
  { label: '小于等于', value: 'le' },
  { label: '介于', value: 'between' },
  { label: '不介于', value: 'notBetween' }
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

const BOOLEAN_OPERATORS: OperatorOption[] = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' }
];

export function operatorsFor(type: FieldType): OperatorOption[] {
  if (type === 'number') return NUMBER_OPERATORS;
  if (type === 'date' || type === 'datetime') return DATE_OPERATORS;
  if (type === 'boolean') return BOOLEAN_OPERATORS;
  return TEXT_OPERATORS;
}

export const needsNoValue = (operator: string) => operator === 'isNull' || operator === 'isNotNull';
export const needsTwoValues = (operator: string) => operator === 'between' || operator === 'notBetween';
export const takesList = (operator: string) => operator === 'in' || operator === 'notIn';

/** 对话框中的一行条件 */
export interface ConditionDraft {
  /** 主表为 null */
  entity: string | null;
  field: string;
  operator: string;
  value: string;
  value2: string;
  /** 明细条件的组和组内与上一条的关系 */
  group: string;
  logic: 'and' | 'or';
}

export function emptyCondition(view: PageView, entity: string | null = null): ConditionDraft {
  const region = entity ? view.details.find(d => d.entity === entity) : view.master;
  const field = region?.fields.find(f => f.visible);
  return {
    entity,
    field: field?.name ?? '',
    operator: field ? operatorsFor(field.type)[0].value : 'eq',
    value: '',
    value2: '',
    group: 'g1',
    logic: 'and'
  };
}

/** 对话框中的条件转成 ListRequest 的 `advanced`；没有有效条件时为 null（与旧系统相同，值为空的条件忽略） */
export function buildAdvanced(view: PageView, drafts: ConditionDraft[], op: 'and' | 'or'): AdvancedQuery | null {
  const conditions: AdvancedCondition[] = [];
  const firstInGroup = new Set<string>();
  for (const draft of drafts) {
    const region = draft.entity ? view.details.find(d => d.entity === draft.entity) : view.master;
    const field = region?.fields.find(f => f.name === draft.field && f.visible);
    if (!field) continue;
    let value: AdvancedCondition['value'];
    if (needsNoValue(draft.operator)) value = null;
    else if (needsTwoValues(draft.operator)) {
      if (draft.value.trim() === '' || draft.value2.trim() === '') continue;
      value = [draft.value.trim(), draft.value2.trim()];
    } else if (takesList(draft.operator)) {
      const items = draft.value
        .split(',')
        .map(v => v.trim())
        .filter(Boolean);
      if (!items.length) continue;
      value = items;
    } else {
      if (draft.value.trim() === '') continue;
      value = field.type === 'boolean' ? draft.value === 'true' : draft.value.trim();
    }
    const condition: AdvancedCondition = { field: field.name, operator: draft.operator, value };
    if (draft.entity) {
      condition.entity = draft.entity;
      condition.group = draft.group;
      const groupKey = `${draft.entity}\u0000${draft.group}`;
      if (firstInGroup.has(groupKey)) condition.logic = draft.logic;
      firstInGroup.add(groupKey);
    }
    conditions.push(condition);
  }
  return conditions.length ? { op, conditions } : null;
}
