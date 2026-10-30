/**
 * 高级查询（FP-20；C09 第 4 节 ListRequest.advanced，queries-export QE-12），同旧系统 AdvancedSearchDialog.vue、
 * useAdvancedSearch.ts、advanced-search-values.ts：
 * - 预置条件：页面视图中 `searchable` 的可见字段（C05 v7），个人列配置中隐藏了的列不列；先主表，再按明细的顺序。
 * - 运算符同旧系统；默认运算符：有 Lookup、字典或选项值的字段为"等于"，文本为"包含"，其他为"等于"。
 * - 填了值自动勾上、清空自动取消；只有勾上且有值的条件参与查询。
 * - 条件不写 `entity` 时属于主表；同一明细实体的条件由同一条明细行同时满足，`group`、`logic` 用于组内的且、或。
 *   预置的明细条件都在组 g1、且：同旧系统同一明细页签的条件合在一个 EXISTS 里（DynamicDataService.java 第 517–560 行）。
 */
import type { FieldValues } from '../../contracts/command';
import type { AdvancedCondition, AdvancedQuery, PersonalConfig } from '../../contracts/http';
import type { FieldType, PageView, ViewField, ViewRegion } from '../../contracts/page-view';
import { regionKey } from './fields';

export type OperatorOption = { label: string; value: string };

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

/** IN、NOT IN 的值：逗号分隔，中英文逗号都可以（同旧系统 splitInValue） */
export const splitList = (text: string) =>
  text
    .split(/[,，]/)
    .map(v => v.trim())
    .filter(Boolean);

/** 对话框中的一行条件 */
export interface ConditionDraft {
  /** 预置条件为 `<区域>:<字段>`（区域同个人列配置的键：master 或明细实体），添加的条件为 `add-<序号>` */
  key: string;
  /** 预置条件（字段的"查询"标记）：表和字段固定，可以隐藏；添加的条件可以换表和字段、可以删除 */
  preset: boolean;
  /** 主表为 null */
  entity: string | null;
  field: string;
  operator: string;
  value: string;
  value2: string;
  /** 勾上的条件才参与查询 */
  enabled: boolean;
  /** 隐藏的预置条件在"显示字段"中恢复 */
  visible: boolean;
  /** 明细条件的组和组内与上一条的关系 */
  group: string;
  logic: 'and' | 'or';
}

function regionOf(view: PageView, entity: string | null): ViewRegion | undefined {
  return entity ? view.details.find(d => d.entity === entity) : view.master;
}

/** 条件的字段（只用可见字段，C05） */
export function conditionField(view: PageView, draft: Pick<ConditionDraft, 'entity' | 'field'>) {
  return regionOf(view, draft.entity)?.fields.find(f => f.name === draft.field && f.visible);
}

/** 字段名下方的小字：主表为"主表"，明细为明细标题（同旧系统 tableLabel） */
export function tableLabel(view: PageView, entity: string | null) {
  return entity ? (view.details.find(d => d.entity === entity)?.title ?? entity) : '主表';
}

/**
 * 值用下拉选择时的选项：字典（页面运行时已读到的，`dicts` 同 PageRuntime.dicts）或选项值（`default` 为 options），
 * 同旧系统 resolveSelectMeta；都不是时为 null。
 */
export function selectOptions(
  field: ViewField,
  dicts: ReadonlyMap<string, ReadonlyMap<string, string>>
): OperatorOption[] | null {
  if (field.dictType)
    return [...(dicts.get(field.dictType) ?? new Map<string, string>())].map(([value, label]) => ({ label, value }));
  const options = field.default?.type === 'options' ? field.default.value : null;
  return Array.isArray(options) ? options.map(v => ({ label: String(v), value: String(v) })) : null;
}

/** 默认运算符（同旧系统 getDefaultOperator）：有 Lookup、字典或选项值的字段为等于，文本为包含，其他为等于 */
export function defaultOperator(field: ViewField) {
  if (field.lookup || field.dictType || field.default?.type === 'options') return 'eq';
  return field.type === 'text' ? 'like' : 'eq';
}

let sequence = 0;

function draftOf(entity: string | null, field: ViewField | undefined, key: string | null): ConditionDraft {
  if (key === null) sequence += 1;
  return {
    key: key ?? `add-${sequence}`,
    preset: key !== null,
    entity,
    field: field?.name ?? '',
    operator: field ? defaultOperator(field) : 'eq',
    value: '',
    value2: '',
    enabled: false,
    visible: true,
    group: 'g1',
    logic: 'and'
  };
}

/** "添加条件"加的一行：表为 `entity`（主表为 null），字段取这张表第一个可见字段 */
export function emptyCondition(view: PageView, entity: string | null = null): ConditionDraft {
  return draftOf(
    entity,
    regionOf(view, entity)?.fields.find(f => f.visible),
    null
  );
}

/** 添加的条件换表：字段改为这张表第一个可见字段，值清空 */
export function setTable(view: PageView, draft: ConditionDraft, entity: string | null) {
  const { key } = draft;
  Object.assign(draft, emptyCondition(view, entity), { key });
}

/** 添加的条件换字段：运算符不适用于新字段时改为新字段的默认运算符 */
export function setField(view: PageView, draft: ConditionDraft, name: string) {
  draft.field = name;
  const field = conditionField(view, draft);
  if (field && !operatorsFor(field.type).some(o => o.value === draft.operator)) draft.operator = defaultOperator(field);
}

/**
 * 预置条件：页面视图中 `searchable` 为 true 的可见字段，个人列配置中隐藏了的列不列（旧系统列配置叠加个人配置后，
 * 隐藏的列不进条件，MetadataService.java 第 94–96 行）；先主表，再按明细的顺序，同一区域按字段顺序。
 */
export function presetConditions(view: PageView, personal: PersonalConfig = {}): ConditionDraft[] {
  const regions: Array<[string | null, ViewRegion]> = [
    [null, view.master],
    ...view.details.map(d => [d.entity, d] as [string, ViewRegion])
  ];
  const result: ConditionDraft[] = [];
  for (const [entity, region] of regions) {
    const key = regionKey(view, region.entity);
    const hidden = new Set((personal.grids?.[key]?.columns ?? []).filter(c => c.hide).map(c => c.field));
    for (const field of region.fields)
      if (field.visible && field.searchable && !hidden.has(field.name))
        result.push(draftOf(entity, field, `${key}:${field.name}`));
  }
  return result;
}

/**
 * 对话框打开时的条件（同旧系统每次打开时的 syncSearchConditions）：预置条件按当前页面视图重新列出，上次的运算符、值、
 * 勾选和隐藏按条件保留；添加的条件中字段仍可见的排在后面。
 */
export function syncConditions(view: PageView, personal: PersonalConfig, drafts: ConditionDraft[]): ConditionDraft[] {
  const previous = new Map(drafts.filter(d => d.preset).map(d => [d.key, d]));
  const presets = presetConditions(view, personal).map(draft => {
    const old = previous.get(draft.key);
    const field = conditionField(view, draft)!;
    if (!old || !operatorsFor(field.type).some(o => o.value === old.operator)) return draft;
    return {
      ...draft,
      operator: old.operator,
      value: old.value,
      value2: old.value2,
      enabled: old.enabled,
      visible: old.visible
    };
  });
  const added = drafts.filter(d => !d.preset && (!d.field || conditionField(view, d)));
  return [...presets, ...added];
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
 * 换运算符（同旧系统 handleOperatorChange）：不是介于时清空第二个值，为空、不为空清空值；`pickedValues` 为 true
 * （有 Lookup 或下拉选择的字段）时，从 IN 换成单个值的运算符只留第一个值。勾选不变。
 */
export function setOperator(draft: ConditionDraft, operator: string, pickedValues = false) {
  draft.operator = operator;
  if (!needsTwoValues(operator)) draft.value2 = '';
  if (needsNoValue(operator)) draft.value = '';
  else if (!takesList(operator) && pickedValues) draft.value = splitList(draft.value)[0] ?? '';
}

/**
 * Lookup 选的行写进条件（同旧系统 handleLookupSelect）：取这个字段 Lookup 回填映射中对应的列，没有时取同名列；
 * IN、NOT IN 追加到已有的值后面并去掉重复的（不分大小写），其他运算符替换为第一行的值。
 */
export function pickLookup(draft: ConditionDraft, field: ViewField, rows: FieldValues[]) {
  const column = field.lookup?.fill[field.name] ?? field.name;
  const picked = rows
    .map(row => row[column])
    .filter(v => v !== null && v !== undefined && String(v).trim() !== '')
    .map(v => String(v).trim());
  if (!takesList(draft.operator)) {
    setValue(draft, picked[0] ?? '');
    return;
  }
  const values = splitList(draft.value);
  const seen = new Set(values.map(v => v.toLowerCase()));
  for (const value of picked) {
    if (!seen.has(value.toLowerCase())) {
      seen.add(value.toLowerCase());
      values.push(value);
    }
  }
  setValue(draft, values.join(', '));
}

/** 隐藏预置条件：清空值、取消勾选（同旧系统 hideCondition） */
export function hideCondition(draft: ConditionDraft) {
  draft.value = '';
  draft.value2 = '';
  draft.enabled = false;
  draft.visible = false;
}

/** 重置：预置条件清空值和勾选（隐藏的仍隐藏，同旧系统 clearSearch），添加的条件去掉 */
export function resetConditions(drafts: ConditionDraft[]): ConditionDraft[] {
  return drafts.filter(d => d.preset).map(d => ({ ...d, value: '', value2: '', enabled: false }));
}

/** 参与查询的条件：显示着、勾上、有值，字段可见 */
function active(view: PageView, drafts: ConditionDraft[]) {
  return drafts.filter(d => d.visible && d.enabled && hasValue(d) && conditionField(view, d));
}

/** "已启用 N 项" */
export const enabledCount = (view: PageView, drafts: ConditionDraft[]) => active(view, drafts).length;

/** 对话框中的条件转成 ListRequest 的 `advanced`；没有参与查询的条件时为 null */
export function buildAdvanced(view: PageView, drafts: ConditionDraft[], op: 'and' | 'or'): AdvancedQuery | null {
  const conditions: AdvancedCondition[] = [];
  const firstInGroup = new Set<string>();
  for (const draft of active(view, drafts)) {
    const field = conditionField(view, draft)!;
    let value: AdvancedCondition['value'];
    if (needsNoValue(draft.operator)) value = null;
    else if (needsTwoValues(draft.operator)) value = [draft.value.trim(), draft.value2.trim()];
    else if (takesList(draft.operator)) value = splitList(draft.value);
    else value = field.type === 'boolean' ? draft.value === 'true' : draft.value.trim();
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
