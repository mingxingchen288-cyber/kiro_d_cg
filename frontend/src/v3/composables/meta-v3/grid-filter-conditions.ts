import type { DynamicQueryCondition } from '@/service/api';

type QueryCondition = DynamicQueryCondition;

let filterGroupSeq = 0;

function normalizeTextValue(value: any) {
  return typeof value === 'string' ? value.toUpperCase() : value;
}

function toTextCondition(field: string, type: string, value: any): QueryCondition | null {
  if (type === 'blank') return { field, operator: 'isNull', value: null };
  if (type === 'notBlank') return { field, operator: 'isNotNull', value: null };
  if (value == null || value === '') return null;
  const normalizedValue = normalizeTextValue(value);
  switch (type) {
    case 'contains':
      return { field, operator: 'like', value: normalizedValue };
    case 'notContains':
      return { field, operator: 'notLike', value: normalizedValue };
    case 'startsWith':
      return { field, operator: 'likeLeft', value: normalizedValue };
    case 'endsWith':
      return { field, operator: 'likeRight', value: normalizedValue };
    case 'equals':
      return { field, operator: 'eq', value: normalizedValue };
    case 'notEqual':
      return { field, operator: 'ne', value: normalizedValue };
    default:
      return null;
  }
}

function toNumberCondition(field: string, type: string, value: any, value2?: any): QueryCondition | null {
  if (type === 'blank') return { field, operator: 'isNull', value: null };
  if (type === 'notBlank') return { field, operator: 'isNotNull', value: null };
  if (value == null || value === '') return null;
  switch (type) {
    case 'equals':
      return { field, operator: 'eq', value };
    case 'notEqual':
      return { field, operator: 'ne', value };
    case 'lessThan':
      return { field, operator: 'lt', value };
    case 'lessThanOrEqual':
      return { field, operator: 'le', value };
    case 'greaterThan':
      return { field, operator: 'gt', value };
    case 'greaterThanOrEqual':
      return { field, operator: 'ge', value };
    case 'inRange':
      if (value2 == null || value2 === '') return null;
      return { field, operator: 'between', value, value2 };
    default:
      return null;
  }
}

function toDateCondition(field: string, type: string, value: any, value2?: any): QueryCondition | null {
  if (type === 'blank') return { field, operator: 'isNull', value: null };
  if (type === 'notBlank') return { field, operator: 'isNotNull', value: null };
  if (value == null || value === '') return null;
  switch (type) {
    case 'equals':
      return { field, operator: 'eq', value };
    case 'notEqual':
      return { field, operator: 'ne', value };
    case 'lessThan':
      return { field, operator: 'lt', value };
    case 'greaterThan':
      return { field, operator: 'gt', value };
    case 'inRange':
      if (value2 == null || value2 === '') return null;
      return { field, operator: 'between', value, value2 };
    default:
      return null;
  }
}

export function buildConditionsFromFilterModel(
  filterModel: Record<string, any> | null | undefined
): QueryCondition[] {
  if (!filterModel) return [];
  const conditions: QueryCondition[] = [];
  for (const [field, filter] of Object.entries(filterModel)) {
    if (!filter) continue;
    const combinedConditions: any[] = Array.isArray(filter.conditions)
      ? filter.conditions
      : [filter.condition1, filter.condition2].filter(Boolean);
    const normalizedCombinedConditions = combinedConditions.map((condition: any) => {
      if (!condition || condition.filterType || !filter.filterType) return condition;
      return { ...condition, filterType: filter.filterType };
    });

    if (filter.operator && normalizedCombinedConditions.length > 0) {
      const groupId = `ag-filter-${Date.now()}-${filterGroupSeq++}`;
      const nestedConditions = normalizedCombinedConditions.flatMap((condition: any) =>
        buildConditionsFromFilterModel({ [field]: condition })
      );
      const groupConditions = nestedConditions.map((condition: QueryCondition, index: number) => ({
        ...condition,
        groupId,
        logicOperator: (index === 0 ? 'AND' : filter.operator === 'OR' ? 'OR' : 'AND') as 'AND' | 'OR'
      }));
      conditions.push(...groupConditions);
      continue;
    }
    if (filter.filterType === 'set' && Array.isArray(filter.values)) {
      if (filter.values.length > 0) {
        conditions.push({ field, operator: 'in', value: filter.values });
      }
      continue;
    }
    const type = filter.type;
    if (filter.filterType === 'text') {
      const cond = toTextCondition(field, type, filter.filter);
      if (cond) conditions.push(cond);
      continue;
    }
    if (filter.filterType === 'number') {
      const cond = toNumberCondition(field, type, filter.filter, filter.filterTo);
      if (cond) conditions.push(cond);
      continue;
    }
    if (filter.filterType === 'date') {
      const cond = toDateCondition(field, type, filter.dateFrom, filter.dateTo);
      if (cond) conditions.push(cond);
    }
  }
  return conditions;
}
