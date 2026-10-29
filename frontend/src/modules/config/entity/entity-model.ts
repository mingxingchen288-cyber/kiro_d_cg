/**
 * 实体编辑中的扩展配置（FC-08、C06 第 2 节）：默认值、对比、必须审批的字段规则。
 * 默认值的写法沿用旧系统 SectionTables.vue 的"默认值"列（当前时间、当前用户ID、当前人员名称、当前部门名称、
 * 当前部门ID）和"选项值"列（逗号分隔，下拉选择，新增行默认取第一个）；C06 另有"当前角色"。
 */
import type { ApprovalRequiredRule, DefaultValue, FieldCompare } from '../core/types';

export const BUILTIN_DEFAULTS: Array<{ label: string; value: Extract<DefaultValue, { type: 'builtin' }>['value'] }> = [
  { label: '当前时间（日期字段取当天）', value: 'currentTime' },
  { label: '当前用户ID', value: 'currentUserId' },
  { label: '当前人员名称', value: 'currentUserName' },
  { label: '当前部门ID', value: 'currentDeptId' },
  { label: '当前部门名称', value: 'currentDeptName' },
  { label: '当前角色', value: 'currentRoleCode' }
];

export function defaultText(value: DefaultValue | null | undefined) {
  if (!value) return '';
  if (value.type === 'builtin') return BUILTIN_DEFAULTS.find(b => b.value === value.value)?.label ?? value.value;
  if (value.type === 'options') return `选项：${value.value.join(',')}`;
  return value.value;
}

export interface DefaultForm {
  type: 'none' | 'static' | 'builtin' | 'options';
  text: string;
  builtin: Extract<DefaultValue, { type: 'builtin' }>['value'];
}

export function defaultForm(value: DefaultValue | null | undefined): DefaultForm {
  if (!value) return { type: 'none', text: '', builtin: 'currentUserName' };
  if (value.type === 'builtin') return { type: 'builtin', text: '', builtin: value.value };
  if (value.type === 'options') return { type: 'options', text: value.value.join(','), builtin: 'currentUserName' };
  return { type: 'static', text: value.value, builtin: 'currentUserName' };
}

/** 表单 → `fields[].default`；"无"时为 null（没有配置时数值字段为 0，其他为空，同旧系统） */
export function defaultValue(form: DefaultForm): DefaultValue | null {
  if (form.type === 'builtin') return { type: 'builtin', value: form.builtin };
  if (form.type === 'options') {
    const values = form.text
      .split(/[,，]/)
      .map(v => v.trim())
      .filter(Boolean);
    return values.length ? { type: 'options', value: values } : null;
  }
  if (form.type === 'static') return form.text === '' ? null : { type: 'static', value: form.text };
  return null;
}

export function compareText(value: FieldCompare | null | undefined) {
  if (!value) return '';
  const format = { value: '差值', percent: '百分比', both: '差值和百分比' }[value.format];
  if (value.mode === 'field') return `与 ${value.field} 对比（${format}）`;
  return `${value.source}.${value.field}（${format}）`;
}

export function newApprovalRequired(): ApprovalRequiredRule {
  return { fields: [], when: { logic: 'AND', conditions: [] }, sourcePages: [] };
}

/** 保存前整理：没有条件时省略 `when`（所有行都满足），`isNull`、`isNotNull` 不写值 */
export function cleanApprovalRequired(rules: ApprovalRequiredRule[]): ApprovalRequiredRule[] {
  return rules.map(rule => {
    const out: ApprovalRequiredRule = { fields: [...rule.fields], sourcePages: [...rule.sourcePages] };
    const conditions = (rule.when?.conditions ?? []).filter(c => c.field);
    if (conditions.length) {
      out.when = {
        logic: rule.when!.logic,
        conditions: conditions.map(c => (c.op === 'isNull' || c.op === 'isNotNull' ? { field: c.field, op: c.op } : { field: c.field, op: c.op, value: c.value ?? '' }))
      };
    }
    return out;
  });
}
