/**
 * 规则表单（FC-06、C06 第 5 节）：和旧系统一样按表单编辑，不做图形化编辑器。
 * 对照旧系统 RuleConfigDialog.vue（计算、校验）、CellEditableDialog.vue（可编辑）、GridStyleDialog.vue（样式）：
 * - 计算：目标字段、排序、条件（可选）、表达式；多公式时按分支写，旧系统的"分支字段 + 匹配方式 + 值"在这里用来生成分支条件；
 * - 校验：字段、规则（必填、最小值……自定义），生成 `when`（成立时拒绝或提示）、级别、提示文字；
 * - 可编辑：可视化条件（AND/OR，来源本行/主表，字段、运算符、值），作用范围整行或指定字段，生效为不可编辑、可编辑或必填；
 * - 样式：条件、作用范围、背景色、字体颜色、加粗、斜体。
 * 每条规则是一个 `rule` 配置项。
 */
import type { CompareOp, Condition, RuleConditionItem, RuleContent, VisualCondition } from '../core/types';

export type RuleKind = 'calc' | 'validate' | 'editable' | 'style';

export const RULE_KIND_TITLES: Record<RuleKind, string> = {
  calc: '计算规则',
  validate: '校验规则',
  editable: '可编辑规则',
  style: '样式规则'
};

export function kindOf(rule: RuleContent): RuleKind {
  if (rule.category === 'calc') return 'calc';
  if (rule.category === 'validate') return 'validate';
  const effect = rule.effect ?? {};
  return effect.rowStyle || effect.cellStyle ? 'style' : 'editable';
}

/** 运算符：同旧系统可编辑规则、行权限的中文写法；取值同 C06 第 8 节 */
export const OP_OPTIONS: Array<{ label: string; value: CompareOp }> = [
  { label: '= 等于', value: 'eq' },
  { label: '≠ 不等于', value: 'ne' },
  { label: '> 大于', value: 'gt' },
  { label: '≥ 大于等于', value: 'ge' },
  { label: '< 小于', value: 'lt' },
  { label: '≤ 小于等于', value: 'le' },
  { label: '包含', value: 'like' },
  { label: '属于', value: 'in' },
  { label: '为空', value: 'isNull' },
  { label: '非空', value: 'isNotNull' }
];

export const LOGIC_OPTIONS = [
  { label: 'AND (全部满足)', value: 'AND' },
  { label: 'OR (任一满足)', value: 'OR' }
];

export const SOURCE_OPTIONS = [
  { label: '当前行字段', value: 'row' },
  { label: '主表字段', value: 'master' }
];

export function newVisual(): VisualCondition {
  return { logic: 'AND', conditions: [] };
}

export function newConditionItem(field = ''): RuleConditionItem {
  return { source: 'row', field, op: 'eq', value: '' };
}

/** 可视化条件保存时去掉 `isNull`、`isNotNull` 的值（C06 第 1.1 节：`value` 可省略） */
export function cleanVisual(condition: VisualCondition): VisualCondition {
  return {
    logic: condition.logic,
    conditions: condition.conditions
      .filter(c => c.field)
      .map(c => {
        const item: RuleConditionItem = { source: c.source, field: c.field, op: c.op };
        if (c.op !== 'isNull' && c.op !== 'isNotNull') item.value = c.value ?? null;
        return item;
      })
  };
}

export function isVisual(condition: Condition | null | undefined): condition is VisualCondition {
  return typeof condition === 'object' && condition !== null;
}

// ---- 计算规则的分支条件（旧系统多公式的匹配方式）

export type MatchType = 'equals' | 'contains' | 'notContains' | 'regex';

export const MATCH_OPTIONS: Array<{ label: string; value: MatchType }> = [
  { label: '等值', value: 'equals' },
  { label: '包含', value: 'contains' },
  { label: '不包含', value: 'notContains' },
  { label: '正则', value: 'regex' }
];

/**
 * ZEN 表达式的字符串常量：没有转义，到下一个同样的引号为止（zen-expression 2.1.6）。含单引号的文字用双引号括起，
 * 其余用单引号；写法同后端 `config/expressions.py` 的 `_string`。
 */
const quote = (text: string) => (text.includes("'") ? `"${text}"` : `'${text}'`);

/** 旧系统"分支字段 + 匹配方式 + 值" → ZEN 表达式条件，例如正则 → `matches(GOODSNAME, '桶|说明书')` */
export function matchCondition(field: string, type: MatchType, value: string) {
  if (type === 'regex') return `matches(${field}, ${quote(value)})`;
  if (type === 'contains') return `contains(${field}, ${quote(value)})`;
  if (type === 'notContains') return `not contains(${field}, ${quote(value)})`;
  return `${field} == ${quote(value)}`;
}

// ---- 校验规则的写法（旧系统 validationRuleOptions）

export type ValidateType = 'required' | 'min' | 'max' | 'minLength' | 'maxLength' | 'pattern' | 'custom';

export const VALIDATE_OPTIONS: Array<{ label: string; value: ValidateType }> = [
  { label: '必填', value: 'required' },
  { label: '最小值', value: 'min' },
  { label: '最大值', value: 'max' },
  { label: '最小长度', value: 'minLength' },
  { label: '最大长度', value: 'maxLength' },
  { label: '正则匹配', value: 'pattern' },
  { label: '自定义', value: 'custom' }
];

/** 生成校验条件（成立时拒绝或提示）；自定义时由管理员直接写条件 */
export function validateCondition(field: string, type: ValidateType, value: string) {
  switch (type) {
    case 'required':
      return `${field} == null or ${field} == ''`;
    case 'min':
      return `${field} < ${value}`;
    case 'max':
      return `${field} > ${value}`;
    case 'minLength':
      return `len(${field}) < ${value}`;
    case 'maxLength':
      return `len(${field}) > ${value}`;
    case 'pattern':
      return `not matches(${field}, ${quote(value)})`;
    default:
      return value;
  }
}

/** 规则编码：`目标.类别.字段`，重复时加序号；管理员可以改 */
export function suggestKey(target: string, kind: RuleKind, field: string | null, used: Set<string>) {
  const base = `${target}.${kind}.${field || 'row'}`;
  if (!used.has(base)) return base;
  let n = 2;
  while (used.has(`${base}.${n}`)) n += 1;
  return `${base}.${n}`;
}
