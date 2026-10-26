import type { ColDef } from 'ag-grid-community';
import { useAuthStore } from '@/store/modules/auth';
import TagSelectCellEditor from '@/v3/components/meta-v3/editors/TagSelectCellEditor.vue';
import type { LookupRule } from '@/v3/composables/meta-v3/useMetaColumns';
import type { AggRule, CalcRule, NestedConfig, ValidationRule } from '@/v3/logic/calc-engine';
import type {
  ButtonItemRule,
  ButtonRule,
  CellEditableRule,
  ColumnOverrideRule,
  ContextMenuRule,
  EditableCondition,
  EditableRule,
  GridOptionsRule,
  GridStyleRule,
  LookupRuleConfig,
  PageComponentWithRules,
  PageRule,
  RelationRule,
  RoleBindingRule,
  RowClassRule,
  RowEditableRule,
  ToolbarRule
} from '@/v3/composables/meta-v3/types';

export function collectPageRules(components: PageComponentWithRules[]): PageRule[] {
  const rules: PageRule[] = [];
  const visit = (component: PageComponentWithRules) => {
    if (Array.isArray(component.rules)) {
      for (const rule of component.rules) {
        const componentKey = rule.componentKey || component.componentKey;
        rules.push({ ...rule, componentKey });
      }
    }
    if (Array.isArray(component.children)) {
      component.children.forEach(visit);
    }
  };
  components.forEach(visit);
  return rules;
}

export function groupRulesByComponent(rules: PageRule[]): Map<string, PageRule[]> {
  const map = new Map<string, PageRule[]>();
  for (const rule of rules) {
    if (!rule.componentKey) continue;
    const list = map.get(rule.componentKey) || [];
    list.push(rule);
    map.set(rule.componentKey, list);
  }
  for (const list of map.values()) {
    list.sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));
  }
  return map;
}

export function getComponentRules(rulesByComponent: Map<string, PageRule[]>, componentKeys: string[]): PageRule[] {
  for (const key of componentKeys) {
    const rules = rulesByComponent.get(key);
    if (rules && rules.length > 0) return rules;
  }
  return [];
}

function getRuleByType(rules: PageRule[], ruleType: string): PageRule | undefined {
  return rules.find(rule => rule.ruleType === ruleType);
}

function parseRuleArray<T>(rule: PageRule | undefined, label: string): T[] {
  if (!rule?.rules) return [];
  try {
    const raw = typeof rule.rules === 'string' ? JSON.parse(rule.rules) : rule.rules;
    if (!Array.isArray(raw)) {
      console.warn(`[PageRule] ${label} is not an array`);
      return [];
    }
    return raw as T[];
  } catch (error) {
    console.warn(`[PageRule] Failed to parse ${label}`, error);
    return [];
  }
}

function parseRuleObject<T>(rule: PageRule | undefined, label: string): T | null {
  if (!rule?.rules) return null;
  try {
    const raw = typeof rule.rules === 'string' ? JSON.parse(rule.rules) : rule.rules;
    if (!raw || Array.isArray(raw) || typeof raw !== 'object') {
      console.warn(`[PageRule] ${label} is not an object`);
      return null;
    }
    return raw as T;
  } catch (error) {
    console.warn(`[PageRule] Failed to parse ${label}`, error);
    return null;
  }
}

function normalizeStringList(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.filter(item => typeof item === 'string') as string[];
}

export function parseValidationRuleConfig(componentKey: string, rules: PageRule[]): ValidationRule[] {
  const rule = getRuleByType(rules, 'VALIDATION');
  const items = parseRuleArray<Record<string, any>>(rule, `${componentKey}.VALIDATION`);
  return items
    .map(item => ({
      field: item.field ?? item.columnName,
      required: item.required,
      notZero: item.notZero,
      min: item.min,
      max: item.max,
      pattern: item.pattern,
      message: item.message
    }))
    .filter(item => Boolean(item.field));
}

/**
 * 解析 Lookup 弹窗规则配置
 *
 * 筛选相关字段说明：
 * - filterField: 从"当前行数据"取哪个字段的值作为筛选值
 *   生效场景：filterValueFrom 没写或为 'row'
 *   例：filterField: "id" → 用当前行的 rowData.id 作为筛选值
 *
 * - filterColumn: 弹窗数据源里要过滤的列名（SQL 中的列名）
 *   例：filterColumn: "GOODSID" → 最终会拼成 AND GOODSID = <filterValue>
 *
 * - filterValueFrom: 筛选值来源
 *   'row': 用 rowData[filterField]
 *   'cell': 用你点击的单元格的值（不需要 filterField）
 */
export function parseLookupRuleConfig(componentKey: string, rules: PageRule[]): LookupRule[] {
  const rule = getRuleByType(rules, 'LOOKUP');
  const items = parseRuleArray<LookupRuleConfig>(rule, `${componentKey}.LOOKUP`);
  return items
    .filter(item => Boolean(item.columnName))
    .map(item => ({
      columnName: item.columnName,
      lookupCode: item.lookupCode,
      mapping: item.mapping,
      multiple: item.multiple,
      noFillback: item.noFillback,
      filterField: item.filterField,
      filterColumn: item.filterColumn,
      filterValueFrom: item.filterValueFrom
    }));
}

export function parseCalcRuleConfig(componentKey: string, rules: PageRule[]): CalcRule[] {
  const rule = getRuleByType(rules, 'CALC');
  return parseRuleArray<CalcRule>(rule, `${componentKey}.CALC`);
}

export function parseAggregateRuleConfig(componentKey: string, rules: PageRule[]): AggRule[] {
  const rule = getRuleByType(rules, 'AGGREGATE');
  return parseRuleArray<AggRule>(rule, `${componentKey}.AGGREGATE`);
}

export function parseColumnOverrideConfig(componentKey: string, rules: PageRule[]): ColumnOverrideRule[] {
  const rule = getRuleByType(rules, 'COLUMN_OVERRIDE');
  return parseRuleArray<ColumnOverrideRule>(rule, `${componentKey}.COLUMN_OVERRIDE`);
}

function normalizeSelectCellEditorParams(editorType: string | undefined, params: Record<string, any>) {
  if (!params || typeof params !== 'object') return params;
  if (editorType !== 'agSelectCellEditor' && editorType !== 'agRichSelectCellEditor' && editorType !== 'tagSelectCellEditor') {
    return params;
  }

  const normalized = { ...params };
  if (Array.isArray(normalized.values)) {
    return normalized;
  }
  if (typeof normalized.values === 'string') {
    normalized.values = normalized.values
      .split(',')
      .map((value: string) => value.trim())
      .filter((value: string) => value.length > 0);
    return normalized;
  }
  normalized.values = [];
  return normalized;
}

/**
 * 从 COLUMN_OVERRIDE 中提取 lookup 配置（cellEditor === 'lookup'）
 * 返回 LookupRule[] 格式，可与传统 LOOKUP 规则合并
 */
export function extractLookupFromColumnOverride(overrides: ColumnOverrideRule[]): LookupRule[] {
  if (!overrides || overrides.length === 0) return [];
  const result: LookupRule[] = [];
  for (const override of overrides) {
    if (override.cellEditor !== 'lookup' && override.cellEditor !== 'lookupMultiple') continue;
    const columnName = override.columnName;
    const params = override.cellEditorParams;
    if (!columnName || !params?.lookupCode) continue;
    result.push({
      columnName,
      lookupCode: params.lookupCode,
      mapping: params.mapping || {},
      multiple: Boolean(params.multiple || override.cellEditor === 'lookupMultiple'),
      noFillback: params.noFillback,
      filterField: params.filterField,
      filterColumn: params.filterColumn,
      filterValueFrom: params.filterValueFrom
    });
  }
  return result;
}

export function parseBroadcastRuleConfig(componentKey: string, rules: PageRule[]): string[] | null {
  const rule = getRuleByType(rules, 'BROADCAST');
  if (!rule?.rules) return null;
  try {
    const raw = typeof rule.rules === 'string' ? JSON.parse(rule.rules) : rule.rules;
    const directList = normalizeStringList(raw);
    if (directList) return directList;
    if (raw && typeof raw === 'object') {
      const obj = raw as { fields?: unknown; broadcast?: unknown; broadcastFields?: unknown };
      const list =
        normalizeStringList(obj.fields) ||
        normalizeStringList(obj.broadcast) ||
        normalizeStringList(obj.broadcastFields);
      if (list) return list;
    }
    console.warn(`[PageRule] ${componentKey}.BROADCAST is not a string array`);
    return null;
  } catch (error) {
    console.warn(`[PageRule] Failed to parse ${componentKey}.BROADCAST`, error);
    return null;
  }
}

export function parseSummaryConfigRule(componentKey: string, rules: PageRule[]): NestedConfig | null {
  const rule = getRuleByType(rules, 'SUMMARY_CONFIG') || getRuleByType(rules, 'NESTED_CONFIG');
  if (!rule) return null;
  return parseRuleObject<NestedConfig>(rule, `${componentKey}.${rule.ruleType || 'SUMMARY_CONFIG'}`);
}

export function parseRoleBindingRule(componentKey: string, rules: PageRule[]): RoleBindingRule | null {
  const rule = getRuleByType(rules, 'ROLE_BINDING');
  if (!rule) return null;
  return parseRuleObject<RoleBindingRule>(rule, `${componentKey}.ROLE_BINDING`);
}

export function parseRelationRule(componentKey: string, rules: PageRule[]): RelationRule | null {
  const rule = getRuleByType(rules, 'RELATION');
  if (!rule) return null;
  return parseRuleObject<RelationRule>(rule, `${componentKey}.RELATION`);
}

export function parseGridOptionsRule(componentKey: string, rules: PageRule[]): GridOptionsRule | null {
  const rule = getRuleByType(rules, 'GRID_OPTIONS') || getRuleByType(rules, 'GRID_FEATURES');
  if (!rule) return null;
  return parseRuleObject<GridOptionsRule>(rule, `${componentKey}.${rule.ruleType || 'GRID_OPTIONS'}`);
}

/**
 * 组件配置类型（包含按钮）
 */
type ComponentConfigWithButtons = {
  buttons?: ButtonItemRule[];
};

const REMOVED_BUTTON_ACTIONS = new Set([
  'add',
  'addRow',
  'delete',
  'deleteRow',
  'save',
  'clipboard.copy',
  'clipboard_copy',
  'clipboard.paste',
  'clipboard_paste',
  'batchSelect',
  'batch_select'
]);

function stripRemovedButtonActions(items: ButtonItemRule[] | null | undefined): ButtonItemRule[] {
  if (!Array.isArray(items) || items.length === 0) return [];

  const result: ButtonItemRule[] = [];

  for (const item of items) {
    if (!item) continue;
    const action = typeof item.action === 'string' ? item.action.trim() : '';
    if (action && REMOVED_BUTTON_ACTIONS.has(action)) {
      continue;
    }

    if (Array.isArray(item.items) && item.items.length > 0) {
      const nextChildren = stripRemovedButtonActions(item.items);
      if (item.type === 'group' || nextChildren.length > 0) {
        result.push({ ...item, items: nextChildren });
      }
      continue;
    }

    result.push(item);
  }

  return result;
}

/**
 * 解析组件配置中的按钮
 */
function parseComponentConfigButtons(componentConfig?: string): ButtonItemRule[] | null {
  if (!componentConfig) return null;
  try {
    const config = JSON.parse(componentConfig) as ComponentConfigWithButtons;
    if (Array.isArray(config.buttons)) {
      return stripRemovedButtonActions(config.buttons);
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 解析按钮规则
 * 优先从 componentConfig.buttons 读取，如果没有则从 rules 中读取
 */
export function parseButtonRule(componentKey: string, rules: PageRule[], componentConfig?: string): ButtonRule | null {
  // 优先从 componentConfig.buttons 读取
  const buttons = parseComponentConfigButtons(componentConfig);

  if (buttons && buttons.length > 0) {
    return { items: buttons };
  }

  // 从 rules 中读取 BUTTON 类型
  const rule = getRuleByType(rules, 'BUTTON');
  if (!rule?.rules) return null;
  try {
    const raw = typeof rule.rules === 'string' ? JSON.parse(rule.rules) : rule.rules;
    if (Array.isArray(raw)) {
      return { items: stripRemovedButtonActions(raw) };
    }
    if (raw && typeof raw === 'object') {
      const obj = raw as { items?: unknown };
      if (Array.isArray(obj.items)) {
        return { items: stripRemovedButtonActions(obj.items) };
      }
    }
    console.warn(`[PageRule] ${componentKey}.BUTTON is not a valid object`);
    return null;
  } catch (error) {
    console.warn(`[PageRule] Failed to parse ${componentKey}.BUTTON`, error);
    return null;
  }
}

/**
 * 从按钮项中过滤出指定位置的按钮
 */
function filterButtonsByPosition(items: ButtonItemRule[], position: 'context' | 'toolbar'): ButtonItemRule[] {
  const result: ButtonItemRule[] = [];

  for (const item of items) {
    // separator 只在右键菜单中保留，工具栏不需要
    if (item.type === 'separator') {
      if (position === 'context') {
        result.push(item);
      }
      continue;
    }

    // 检查 position；高级查询是系统工具栏按钮，历史配置没有 position 时也按工具栏处理
    const pos = item.position || (item.action === 'advancedSearch' ? 'toolbar' : 'context');
    if (pos !== position && pos !== 'both') continue;

    // 递归处理子菜单
    if (item.items && item.items.length > 0) {
      const subItems = filterButtonsByPosition(item.items, position);
      if (subItems.length > 0) {
        result.push({ ...item, items: subItems });
      }
    } else {
      result.push(item);
    }
  }

  return result;
}

/**
 * 解析右键菜单规则（从按钮配置中提取 position='context' 的按钮）
 */
export function parseContextMenuRule(
  componentKey: string,
  rules: PageRule[],
  componentConfig?: string
): ContextMenuRule | null {
  const buttonRule = parseButtonRule(componentKey, rules, componentConfig);
  if (!buttonRule) return null;
  const contextItems = filterButtonsByPosition(buttonRule.items, 'context');
  return contextItems.length > 0 ? { items: contextItems } : null;
}

type ColumnOverrideApplyMode = 'full' | 'uiOnly';

function getOverrideMatchKey(override: ColumnOverrideRule): string | null {
  if (typeof override.columnId === 'number' && Number.isFinite(override.columnId)) {
    return `id:${override.columnId}`;
  }
  return override.columnName ? `field:${override.columnName}` : null;
}

function getColDefMatchKey(col: ColDef): string | null {
  const metaColumnId = (col.context as { metaColumnId?: unknown } | undefined)?.metaColumnId;
  if (typeof metaColumnId === 'number' && Number.isFinite(metaColumnId)) {
    return `id:${metaColumnId}`;
  }
  const field = col.field as string | undefined;
  return field ? `field:${field}` : null;
}

export function applyColumnOverrides(
  columns: ColDef[],
  overrides: ColumnOverrideRule[],
  options?: { mode?: ColumnOverrideApplyMode }
): ColDef[] {
  if (!overrides || overrides.length === 0) return columns;
  const applyMode = options?.mode || 'full';
  const applyStructuralOverrides = applyMode === 'full';
  const overrideMap = new Map<string, ColumnOverrideRule>();
  for (const override of overrides) {
    const key = getOverrideMatchKey(override);
    if (!key) continue;
    overrideMap.set(key, override);
  }
  const result = columns.map(col => {
    const field = col.field as string | undefined;
    if (!field) return col;
    const override = overrideMap.get(getColDefMatchKey(col) || '');
    if (!override) return col;
    const updated: ColDef = { ...col };
    if (applyStructuralOverrides) {
      if (override.width != null) updated.width = override.width;
      if (override.visible != null) updated.hide = override.visible === false;
      if (override.editable === false) updated.editable = false;
      if (override.searchable === false) updated.filter = false;
      if (override.searchable === true && updated.filter === false) updated.filter = true;
    }
    // 支持下拉框编辑器
    const isLookupEditor = override.cellEditor === 'lookup' || override.cellEditor === 'lookupMultiple';
    if (override.cellEditor && !isLookupEditor) {
      if (override.cellEditor === 'tagSelectCellEditor') {
        updated.cellEditor = TagSelectCellEditor;
        updated.cellEditorPopup = true;
        updated.cellEditorPopupPosition = 'under';
      } else {
        updated.cellEditor = override.cellEditor;
      }
    }
    if (override.cellEditorParams) {
      const params = normalizeSelectCellEditorParams(override.cellEditor, override.cellEditorParams);
      if (params.mode === 'static') {
        // 纯值模式：values 可能是数组或逗号分隔字符串
        const values = Array.isArray(params.values)
          ? params.values
          : typeof params.values === 'string'
            ? params.values.split(',').map((v: string) => v.trim())
            : [];
        updated.cellEditorParams = { values };
      } else if (params.mode === 'ref') {
        // 关联查询模式：后端已通过 LEFT JOIN 返回 xxxLabel 字段
        // valueFormatter 展示 label，实际值还是原字段
        const labelField = `${field}Label`;
        updated.valueFormatter = (p: any) => {
          if (p.data && p.data[labelField] != null) return p.data[labelField];
          return p.value ?? '';
        };
        // cellEditorParams 透传给前端（后续可用于构建下拉选项）
        updated.cellEditorParams = params;
      } else {
        updated.cellEditorParams = params;
      }
    }
    // 支持聚合函数（底部汇总）
    if (override.aggFunc) {
      updated.aggFunc = override.aggFunc;
    }
    // 显示精度（仅影响显示，不影响底层数据）
    if (override.precision != null) {
      const precision = override.precision;
      const roundMode = override.roundMode || 'round';
      updated.valueFormatter = (params: any) => {
        const val = params.value;
        if (val == null || val === '') return '';
        const num = Number(val);
        if (!Number.isFinite(num)) return String(val);
        let rounded: number;
        const factor = 10 ** precision;
        switch (roundMode) {
          case 'ceil':
            rounded = Math.ceil(num * factor) / factor;
            break;
          case 'floor':
            rounded = Math.floor(num * factor) / factor;
            break;
          default:
            rounded = Math.round(num * factor) / factor;
            break;
        }
        // 去掉尾部多余的零，0 就显示 0，不补 0.00
        const fixed = rounded.toFixed(precision);
        return fixed.replace(/\.?0+$/, '') || '0';
      };
    }
    // 支持对比值渲染
    if (override.rulesConfig?.compare?.enabled) {
      const compare = override.rulesConfig.compare;
      updated.cellRenderer = createCompareRenderer(field, {
        compareField: compare.compareField,
        format: compare.format || 'percent',
        upColor: compare.upColor || '#e53935',
        downColor: compare.downColor || '#43a047'
      });
    }
    return updated;
  });

  // 按 COLUMN_OVERRIDE 中的顺序重排列
  if (applyStructuralOverrides) {
    const orderMap = new Map<string, number>();
    overrides.forEach((o, i) => {
      const key = getOverrideMatchKey(o);
      if (key) orderMap.set(key, i);
    });
    if (orderMap.size > 0) {
      const maxOrder = orderMap.size;
      result.sort((a, b) => {
        const oa = orderMap.get(getColDefMatchKey(a) || '') ?? maxOrder;
        const ob = orderMap.get(getColDefMatchKey(b) || '') ?? maxOrder;
        return oa - ob;
      });
    }
  }

  return result;
}

/** 对比渲染配置 */
interface CompareRendererConfig {
  compareField: string;
  format: 'value' | 'percent' | 'both';
  upColor: string;
  downColor: string;
}

/** 创建对比值渲染器 */
function createCompareRenderer(field: string, config: CompareRendererConfig) {
  return (params: any) => {
    const value = params.value;
    const data = params.data;

    if (value == null) return '';

    // 获取对比值
    const compareValue = data?.[config.compareField];

    // 没有对比数据，直接显示当前值
    if (compareValue == null) {
      return String(value);
    }

    // 计算差值
    const current = Number(value);
    const compare = Number(compareValue);
    if (isNaN(current) || isNaN(compare)) {
      return String(value);
    }

    const diff = current - compare;
    const diffPercent = compare !== 0 ? (diff / compare) * 100 : 0;

    // 没有变化
    if (diff === 0) {
      return String(value);
    }

    // 构建差值显示
    const isUp = diff > 0;
    const arrow = isUp ? '↑' : '↓';
    const color = isUp ? config.upColor : config.downColor;

    let diffText = '';
    if (config.format === 'value' || config.format === 'both') {
      diffText = Math.abs(diff).toFixed(2);
    }
    if ((config.format === 'percent' || config.format === 'both') && diffPercent !== 0) {
      const percentText = `${Math.abs(diffPercent).toFixed(1)}%`;
      diffText = config.format === 'both' ? `${diffText} (${percentText})` : percentText;
    }

    return `<span>${value}</span><span style="color:${color};font-size:11px;margin-left:4px">${arrow}${diffText}</span>`;
  };
}

export function attachGroupCellRenderer(columns: ColDef[]): ColDef[] {
  const index = columns.findIndex(col => !col.hide);
  if (index < 0) return columns;
  return columns.map((col, idx) => {
    if (idx !== index) return col;
    return { ...col, cellRenderer: 'agGroupCellRenderer' };
  });
}

function normalizeEditableConditions(raw: unknown): EditableCondition[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map(item => {
      if (!item || typeof item !== 'object') return null;
      const condition = item as EditableCondition;
      if (!condition.field || !condition.operator) return null;
      return {
        source:
          condition.source === 'currentUser' || condition.source === 'currentDepartment' ? condition.source : 'row',
        field: condition.field,
        operator: condition.operator,
        value: condition.value
      } satisfies EditableCondition;
    })
    .filter(Boolean) as EditableCondition[];
}

function normalizeEditableRule(raw: unknown): EditableRule | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, any>;
  const scope = item.scope === 'row' ? 'row' : item.scope === 'cell' ? 'cell' : null;
  if (!scope) return null;

  const conditions = normalizeEditableConditions(item.conditions);
  let condition: EditableCondition | undefined;
  if (!conditions.length && item.condition && typeof item.condition === 'object') {
    const [single] = normalizeEditableConditions([item.condition]);
    condition = single;
  }

  return {
    scope,
    logic: item.logic === 'OR' ? 'OR' : 'AND',
    conditions,
    condition,
    sqlCheck: typeof item.sqlCheck === 'string' ? item.sqlCheck : undefined,
    editableFields:
      scope === 'cell' && Array.isArray(item.editableFields)
        ? item.editableFields.filter((field: unknown) => typeof field === 'string')
        : undefined
  };
}

export function parseEditableRule(componentKey: string, rules: PageRule[]): EditableRule[] {
  const rule = rules.find(r => r.ruleType === 'EDITABLE');
  if (!rule?.rules) return [];
  try {
    const raw = typeof rule.rules === 'string' ? JSON.parse(rule.rules) : rule.rules;
    const items = Array.isArray(raw) ? raw : [raw];
    return items.map(normalizeEditableRule).filter(Boolean) as EditableRule[];
  } catch (error) {
    console.warn(`[PageRule] Failed to parse ${componentKey}.EDITABLE`, error);
    return [];
  }
}

/** 解析 ROW_EDITABLE 规则 */
export function parseRowEditableRule(componentKey: string, rules: PageRule[]): RowEditableRule[] {
  return parseEditableRule(componentKey, rules)
    .filter(rule => rule.scope === 'row')
    .map(rule => ({
      logic: rule.logic,
      conditions: rule.conditions,
      condition: rule.condition,
      sqlCheck: rule.sqlCheck
    }));
}

/** 根据 ROW_EDITABLE 规则生成 editable 回调 */
export function buildRowEditableCallback(rules: RowEditableRule[]): ((params: any) => boolean) | undefined {
  if (!rules || rules.length === 0) return undefined;
  return (params: any) => {
    const data = params.data;
    if (!data) return true;
    for (const rule of rules) {
      if (checkRuleConditions(data, rule)) {
        return true;
      }
    }
    return false;
  };
}

/** 解析 CELL_EDITABLE 规则 */
export function parseCellEditableRule(componentKey: string, rules: PageRule[]): CellEditableRule[] {
  const editableRules = parseEditableRule(componentKey, rules)
    .filter(rule => rule.scope === 'cell')
    .map(rule => ({
      logic: rule.logic,
      conditions: rule.conditions,
      condition: rule.condition,
      sqlCheck: rule.sqlCheck,
      editableFields: Array.isArray(rule.editableFields) ? rule.editableFields : []
    }))
    .filter(rule => rule.editableFields.length > 0);
  const requiredRules = parseRuleArray<Record<string, unknown>>(
    getRuleByType(rules, 'APPROVAL_REQUIRED'),
    `${componentKey}.APPROVAL_REQUIRED`
  );
  const approvalRules: CellEditableRule[] = [];
  for (const rule of requiredRules) {
    // 例外规则必须可在前后端用同一份行数据判断，不能将身份或 SQL 条件降级为无条件开放。
    if (!rule || rule.scope !== 'cell' || rule.sqlCheck != null) continue;
    if (rule.logic != null && rule.logic !== 'AND' && rule.logic !== 'OR') continue;
    if (!Array.isArray(rule.conditions) || rule.conditions.length === 0) continue;
    const validConditions = rule.conditions.every(condition => {
      if (!condition || typeof condition !== 'object') return false;
      if (condition.source != null && condition.source !== 'row') return false;
      if (typeof condition.field !== 'string' || !condition.field.trim()) return false;
      if (!['eq', 'ne', 'notNull', 'isNull'].includes(condition.operator)) return false;
      if (['notNull', 'isNull'].includes(condition.operator)) return true;
      return condition.value !== undefined && (condition.value === null || typeof condition.value !== 'object');
    });
    if (!validConditions) continue;
    if (!Array.isArray(rule.editableFields) ||
      !rule.editableFields.every(field => typeof field === 'string' && field.trim())) continue;
    const normalized = normalizeEditableRule(rule);
    if (!normalized?.editableFields?.length) continue;
    approvalRules.push({
      requireApproval: true,
      logic: normalized.logic,
      conditions: normalized.conditions,
      editableFields: normalized.editableFields
    });
  }
  return [...editableRules, ...approvalRules];
}

/** 检查单个条件是否匹配 */
function checkCondition(data: any, condition: EditableCondition): boolean {
  let fieldValue: any;
  if (condition.source === 'currentUser') {
    fieldValue = useAuthStore().userInfo.userId;
  } else if (condition.source === 'currentDepartment') {
    fieldValue = useAuthStore().userInfo.departmentId;
  } else {
    fieldValue = data[condition.field];
  }
  switch (condition.operator) {
    case 'notNull':
      return fieldValue != null;
    case 'isNull':
      return fieldValue == null;
    case 'eq':
      // eslint-disable-next-line eqeqeq
      return fieldValue == condition.value;
    case 'ne':
      // eslint-disable-next-line eqeqeq
      return fieldValue != condition.value;
    case 'in':
      return Array.isArray(condition.value) && condition.value.includes(fieldValue);
    case 'notIn':
      return !Array.isArray(condition.value) || !condition.value.includes(fieldValue);
    default:
      return false;
  }
}

/** 检查一条规则的所有前端条件是否匹配 */
function checkRuleConditions(data: any, rule: Pick<RowEditableRule, 'logic' | 'conditions' | 'condition'>): boolean {
  // 新格式：多条件
  if (rule.conditions && rule.conditions.length > 0) {
    const logic = rule.logic || 'AND';
    if (logic === 'OR') {
      return rule.conditions.some(c => checkCondition(data, c));
    }
    return rule.conditions.every(c => checkCondition(data, c));
  }
  // 旧格式：单条件
  if (rule.condition) {
    return checkCondition(data, rule.condition);
  }
  // 没有前端条件（可能只有 sqlCheck），默认通过
  return true;
}

/** 根据 CELL_EDITABLE 规则生成单元格级 editable 回调 */
export function buildCellEditableCallback(
  cellRules: CellEditableRule[],
  rowRules?: RowEditableRule[]
): ((params: any) => boolean) | undefined {
  if ((!cellRules || cellRules.length === 0) && (!rowRules || rowRules.length === 0)) {
    return undefined;
  }

  const rowCallback = buildRowEditableCallback(rowRules || []);
  const approvalRules = (cellRules || []).filter(rule => rule.requireApproval);
  const ordinaryRules = (cellRules || []).filter(rule => !rule.requireApproval);

  // 收集所有被 CELL_EDITABLE 规则管控的字段
  const controlledFields = new Set<string>();
  if (ordinaryRules.length > 0) {
    for (const rule of ordinaryRules) {
      for (const f of rule.editableFields) controlledFields.add(f);
    }
  }

  return (params: any) => {
    const data = params.data;
    const field = params.colDef?.field;

    if (!data) return true;

    // 新增行始终可编辑
    const rowStateApi = params?.context?.rowStateApi as { isRowNew?: (row: any) => boolean } | undefined;
    if (rowStateApi?.isRowNew?.(data)) return true;

    // 需审批的编辑字段是现有规则的例外；是否必须送审由服务端再次校验。
    if (approvalRules.some(rule => rule.editableFields.includes(field) && checkRuleConditions(data, rule))) {
      return true;
    }

    // 检查 CELL_EDITABLE 规则
    if (ordinaryRules.length > 0) {
      for (const rule of ordinaryRules) {
        if (checkRuleConditions(data, rule)) {
          return rule.editableFields.includes(field);
        }
      }
      // 没有匹配的规则 → 被管控的字段默认不可编辑
      if (controlledFields.has(field)) {
        return false;
      }
    }

    // 没有匹配的 CELL_EDITABLE 规则，使用 ROW_EDITABLE 规则
    if (rowCallback) {
      return rowCallback(params);
    }

    return true;
  };
}

/** 解析 GRID_STYLE / ROW_CLASS 规则（向后兼容） */
export function parseGridStyleRule(componentKey: string, rules: PageRule[]): GridStyleRule[] {
  // 优先读 GRID_STYLE，没有则读 ROW_CLASS（向后兼容）
  const rule = rules.find(r => r.ruleType === 'GRID_STYLE') || rules.find(r => r.ruleType === 'ROW_CLASS');
  if (!rule?.rules) return [];
  try {
    const raw = typeof rule.rules === 'string' ? JSON.parse(rule.rules) : rule.rules;
    if (Array.isArray(raw)) return raw as GridStyleRule[];
    if (raw && typeof raw === 'object') return [raw as GridStyleRule];
    return [];
  } catch (error) {
    console.warn(`[PageRule] Failed to parse ${componentKey}.GRID_STYLE`, error);
    return [];
  }
}

/** @deprecated 使用 parseGridStyleRule */
export function parseRowClassRule(componentKey: string, rules: PageRule[]): GridStyleRule[] {
  return parseGridStyleRule(componentKey, rules);
}

/** 条件匹配工具函数 */
function matchCondition(data: any, rule: GridStyleRule): boolean {
  const fieldValue = data[rule.field];
  switch (rule.operator) {
    case 'notNull':
      return fieldValue != null;
    case 'eq':
      return fieldValue === rule.value;
    case 'ne':
      return fieldValue !== rule.value;
    case 'in':
      return Array.isArray(rule.value) && rule.value.includes(fieldValue);
    case 'notIn':
      return !Array.isArray(rule.value) || !rule.value.includes(fieldValue);
    default:
      return false;
  }
}

/** 根据 GRID_STYLE 规则生成 getRowClass 回调（兼容旧 className） */
export function buildRowClassCallback(rules: GridStyleRule[]): ((params: any) => string | undefined) | undefined {
  if (!rules || rules.length === 0) return undefined;
  const classRules = rules.filter(r => r.className);
  if (classRules.length === 0) return undefined;
  return (params: any) => {
    const data = params.data;
    if (!data) return undefined;
    const classes: string[] = [];
    for (const rule of classRules) {
      if (matchCondition(data, rule) && rule.className) {
        classes.push(rule.className);
      }
    }
    return classes.length > 0 ? classes.join(' ') : undefined;
  };
}

/** 根据 GRID_STYLE 规则生成 getRowStyle 回调（scope=row 或无 scope 的规则） */
export function buildRowStyleCallback(
  rules: GridStyleRule[]
): ((params: any) => Record<string, string> | undefined) | undefined {
  if (!rules || rules.length === 0) return undefined;
  const rowRules = rules.filter(r => r.style && (!r.scope || r.scope === 'row'));
  if (rowRules.length === 0) return undefined;

  return (params: any) => {
    const data = params.data;
    if (!data) return undefined;
    const mergedStyle: Record<string, string> = {};
    for (const rule of rowRules) {
      if (!rule.style) continue;
      if (matchCondition(data, rule)) {
        if (rule.style.backgroundColor) mergedStyle.backgroundColor = rule.style.backgroundColor;
        if (rule.style.color) mergedStyle.color = rule.style.color;
        if (rule.style.fontWeight) mergedStyle.fontWeight = rule.style.fontWeight;
        if (rule.style.fontStyle) mergedStyle.fontStyle = rule.style.fontStyle;
      }
    }
    return Object.keys(mergedStyle).length > 0 ? mergedStyle : undefined;
  };
}

/** 根据 GRID_STYLE 规则生成单元格级 cellStyle 回调（scope=cell 的规则） */
export function buildCellStyleRules(
  rules: GridStyleRule[]
): Map<string, (params: any) => Record<string, string> | undefined> {
  const result = new Map<string, (params: any) => Record<string, string> | undefined>();
  if (!rules || rules.length === 0) return result;

  const cellRules = rules.filter(r => r.style && r.scope === 'cell' && r.targetFields?.length);
  if (cellRules.length === 0) return result;

  // 按 targetField 分组
  const rulesByField = new Map<string, GridStyleRule[]>();
  for (const rule of cellRules) {
    for (const field of rule.targetFields!) {
      const list = rulesByField.get(field) || [];
      list.push(rule);
      rulesByField.set(field, list);
    }
  }

  for (const [field, fieldRules] of rulesByField) {
    result.set(field, (params: any) => {
      const data = params.data;
      if (!data) return undefined;
      const mergedStyle: Record<string, string> = {};
      for (const rule of fieldRules) {
        if (!rule.style) continue;
        if (matchCondition(data, rule)) {
          if (rule.style.backgroundColor) mergedStyle.backgroundColor = rule.style.backgroundColor;
          if (rule.style.color) mergedStyle.color = rule.style.color;
          if (rule.style.fontWeight) mergedStyle.fontWeight = rule.style.fontWeight;
          if (rule.style.fontStyle) mergedStyle.fontStyle = rule.style.fontStyle;
        }
      }
      return Object.keys(mergedStyle).length > 0 ? mergedStyle : undefined;
    });
  }

  return result;
}

/** 将单元格样式规则应用到列定义上 */
export function applyCellStyleRules(columns: ColDef[], rules: GridStyleRule[]): ColDef[] {
  const cellStyleMap = buildCellStyleRules(rules);
  if (cellStyleMap.size === 0) return columns;
  return columns.map(col => {
    const field = col.field;
    if (!field) return col;
    const cellStyleFn = cellStyleMap.get(field);
    if (!cellStyleFn) return col;
    return { ...col, cellStyle: cellStyleFn };
  });
}

/**
 * 解析工具栏规则（从按钮配置中提取 position='toolbar' 的按钮）
 */
export function parseToolbarRule(
  componentKey: string,
  rules: PageRule[],
  componentConfig?: string
): ToolbarRule | null {
  const buttonRule = parseButtonRule(componentKey, rules, componentConfig);
  if (!buttonRule) return null;
  const toolbarItems = filterButtonsByPosition(buttonRule.items, 'toolbar');
  return toolbarItems.length > 0 ? { items: toolbarItems } : null;
}

/** 从 COLUMN_OVERRIDE 中提取需要求和的字段列表 */
export function extractSumFields(overrides: ColumnOverrideRule[]): string[] {
  if (!overrides || overrides.length === 0) return [];
  return overrides.filter(o => o.aggFunc === 'sum' && o.columnName).map(o => o.columnName!);
}

/** 根据数据行计算求和汇总行（用于 pinnedBottomRowData） */
export function computeSumRow(rows: any[], sumFields: string[]): Record<string, any> | null {
  if (!sumFields.length || !rows.length) return null;
  const result: Record<string, any> = { _isSumRow: true };
  for (const field of sumFields) {
    let sum = 0;
    for (const row of rows) {
      const val = Number(row[field]);
      if (!isNaN(val)) sum += val;
    }
    result[field] = sum; // 精度由 valueFormatter 统一控制
  }
  return result;
}
