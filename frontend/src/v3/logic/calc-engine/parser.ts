/**
 * 元数据解析器
 * 从 PAGE_COMPONENT.COMPONENT_CONFIG 解析计算规则、聚合规则、Tab 配置
 */
import type { AggRule, CalcRule } from './calculator';

// ==================== 类型定义 ====================

/** Tab 配置 */
export interface TabConfig {
  key: string;
  title: string;
  mode: 'group' | 'multi';
  // group 模式
  groupField?: string;
  groupValue?: string;
  groupValues?: string[]; // 多个分组值
  // multi 模式
  tableCode?: string;
  // 通用
  columns: string[];
  initialSort?: Array<{ colId: string; sort: 'asc' | 'desc' }>; // AG Grid 初始排序
  variantKey?: string; // 变体列分组键
}

/** DETAIL_GRID 组件配置（从数据库读取） */
export interface DetailGridComponentConfig {
  title?: string;
  mode?: 'group' | 'multi';
  groupField?: string;
  groupValue?: string;
  groupValues?: string[];
  columns?: string[];
  initialSort?: Array<{ colId: string; sort: 'asc' | 'desc' }>;
  variantKey?: string;
  buttons?: any[];
}

/** 主表 GRID 组件的全局配置（calcRules/aggregates 等从这里读取） */
export interface MasterGridGlobalConfig {
  broadcast?: string[];
  calcRules?: CalcRule[];
  aggregates?: AggRule[];
  postProcess?: string;
  masterCalcRules?: CalcRule[];
  nestedConfig?: NestedConfig;
  enterpriseConfig?: EnterpriseConfig;
  height?: string;
  selectionMode?: string;
  buttons?: any[];
}

/** @deprecated 保留类型别名，旧代码引用不报错 */
export type TabsComponentConfig = MasterGridGlobalConfig;

/** 页面组件（从 API 返回） */
export interface PageComponent {
  id: number;
  pageCode: string;
  componentKey: string;
  componentType: string;
  parentKey?: string;
  sortOrder: number;
  refTableCode?: string;
  componentConfig?: string;
  children?: PageComponent[];
}

/** 企业版功能配置 */
export interface EnterpriseConfig {
  enableSidebar?: boolean; // 启用侧边栏
  enableExcelExport?: boolean; // 启用 Excel 导出
  cellSelection?: boolean; // 启用单元格选择
  groupBy?: string[]; // 分组字段
  aggregations?: Array<{
    // 聚合配置
    field: string;
    aggFunc: 'sum' | 'min' | 'max' | 'avg' | 'count' | 'first' | 'last';
  }>;
  groupColumnName?: string; // 分组列名称
}

/** 汇总行聚合配置 */
export interface SummaryAggConfig {
  sourceField: string; // 从表源字段
  targetField: string; // 汇总行目标字段
  algorithm: 'SUM' | 'AVG' | 'COUNT' | 'MAX' | 'MIN';
}

/** 汇总行列配置 */
export interface SummaryColumnConfig {
  field: string; // 字段名
  headerName: string; // 列标题
  width?: number; // 列宽
}

/** 三层嵌套配置 */
export interface NestedConfig {
  enabled?: boolean; // 是否启用三层嵌套
  summaryColumns?: SummaryColumnConfig[]; // 汇总行显示的列
  summaryAggregates?: SummaryAggConfig[]; // 汇总行聚合规则
  groupLabelField?: string; // 分组标签字段名，默认 'groupLabel'
  groupLabelHeader?: string; // 分组标签表头，默认 '分类'
}

/** 解析结果 */
export interface ParsedPageConfig {
  masterTableCode: string;
  detailTableCode: string;
  detailFkColumn?: string; // 从表外键列（从 TABLE_METADATA.PARENT_FK_COLUMN 获取）
  tabs: TabConfig[];
  broadcast: string[];
  broadcastFields: string[]; // 广播字段（别名，兼容旧代码）
  calcRules: CalcRule[];
  aggregates: AggRule[];
  groupField?: string;
  mode: 'group' | 'multi';
  postProcess?: string; // 聚合后处理表达式
  masterCalcRules: CalcRule[]; // 主表计算规则
  enterpriseConfig?: EnterpriseConfig; // 企业版功能配置
  nestedConfig?: NestedConfig; // 三层嵌套配置
}

// ==================== 解析函数 ====================

/**
 * 解析页面组件树，提取主从表配置
 */
export function parsePageComponents(
  components: PageComponent[],
  options?: { masterGridKey?: string; detailTabsKey?: string }
): ParsedPageConfig | null {
  const masterKey = options?.masterGridKey;
  let masterGrid = masterKey ? findComponent(components, masterKey, 'GRID') : null;
  if (!masterGrid) {
    masterGrid = findComponent(components, 'masterGrid', 'GRID');
  }
  if (!masterGrid) {
    const grids = findComponentsByType(components, 'GRID');
    if (grids.length === 1) masterGrid = grids[0];
  }
  if (!masterGrid) {
    console.warn('[Parser] 未找到 masterGrid 组件');
    return null;
  }

  // 解析主表组件配置（包含全局配置 + 企业版配置）
  const masterConfig = parseComponentConfig<MasterGridGlobalConfig>(masterGrid.componentConfig);
  const enterpriseConfig = masterConfig?.enterpriseConfig;

  // 查找所有 DETAIL_GRID 组件，每个代表一个从表 tab
  const detailGrids = findComponentsByType(components, 'DETAIL_GRID');

  if (detailGrids.length === 0) {
    // 单表模式
    return {
      masterTableCode: masterGrid.refTableCode || '',
      detailTableCode: '',
      tabs: [],
      broadcast: [],
      broadcastFields: [],
      calcRules: [],
      aggregates: [],
      mode: 'group',
      masterCalcRules: [],
      enterpriseConfig
    };
  }

  // 按 sortOrder 排序
  detailGrids.sort((a, b) => (a.sortOrder || 0) - (b.sortOrder || 0));

  // 从每个 DETAIL_GRID 的 componentConfig 解析 tab 配置
  const tabs: TabConfig[] = detailGrids.map(dg => {
    const dgConfig = parseComponentConfig<DetailGridComponentConfig>(dg.componentConfig);
    return {
      key: dg.componentKey,
      title: dgConfig?.title || dg.componentKey,
      mode: dgConfig?.mode || 'multi',
      groupField: dgConfig?.groupField,
      groupValue: dgConfig?.groupValue,
      groupValues: dgConfig?.groupValues,
      tableCode: dg.refTableCode || undefined,
      columns: dgConfig?.columns || [],
      initialSort: dgConfig?.initialSort,
      variantKey: dgConfig?.variantKey
    };
  });

  const broadcastList = masterConfig?.broadcast || [];

  return {
    masterTableCode: masterGrid.refTableCode || '',
    detailTableCode: detailGrids[0]?.refTableCode || '',
    tabs,
    broadcast: broadcastList,
    broadcastFields: broadcastList,
    calcRules: masterConfig?.calcRules || [],
    aggregates: masterConfig?.aggregates || [],
    groupField: undefined,
    mode: 'multi',
    postProcess: masterConfig?.postProcess,
    masterCalcRules: masterConfig?.masterCalcRules || [],
    enterpriseConfig,
    nestedConfig: masterConfig?.nestedConfig
  };
}

/**
 * @deprecated 不再使用，DETAIL_GRID 组件直接解析
 */
export function parseTabConfig(config: any): TabConfig[] {
  if (!config?.tabs) return [];
  return config.tabs.map((tab: any) => ({
    key: tab.key,
    title: tab.title,
    mode: config.mode || 'group',
    groupField: config.groupField,
    groupValue: tab.value,
    groupValues: tab.values,
    tableCode: tab.tableCode,
    columns: tab.columns || [],
    initialSort: tab.initialSort,
    variantKey: tab.variantKey
  }));
}

/**
 * 解析计算规则（从 COMPONENT_CONFIG）
 */
export function parseCalcRules(config: any): CalcRule[] {
  if (!config?.calcRules) return [];

  return config.calcRules.map((rule: any, idx: number) => ({
    field: rule.field,
    expression: rule.expression,
    triggerFields: rule.triggerFields || [],
    condition: rule.condition,
    order: rule.order ?? idx
  }));
}

/**
 * 解析聚合规则（从 COMPONENT_CONFIG）
 */
export function parseAggRules(config: any): AggRule[] {
  if (!config?.aggregates) return [];

  return config.aggregates.map((rule: any) => ({
    sourceField: rule.sourceField,
    targetField: rule.targetField,
    algorithm: rule.algorithm,
    filter: rule.filter,
    expression: rule.expression
  }));
}

/**
 * 从组件树中查找指定 key 的组件
 */
function findComponent(components: PageComponent[], key: string, type?: string): PageComponent | null {
  for (const comp of components) {
    if (comp.componentKey === key && (!type || comp.componentType === type)) {
      return comp;
    }
    if (comp.children) {
      const found = findComponent(comp.children, key, type);
      if (found) return found;
    }
  }
  return null;
}

/**
 * 从组件树中查找指定类型的组件
 */
function findComponentByType(components: PageComponent[], type: string): PageComponent | null {
  for (const comp of components) {
    if (comp.componentType === type) {
      return comp;
    }
    if (comp.children) {
      const found = findComponentByType(comp.children, type);
      if (found) return found;
    }
  }
  return null;
}

function findComponentsByType(components: PageComponent[], type: string): PageComponent[] {
  const result: PageComponent[] = [];
  for (const comp of components) {
    if (comp.componentType === type) {
      result.push(comp);
    }
    if (comp.children) {
      result.push(...findComponentsByType(comp.children, type));
    }
  }
  return result;
}

/**
 * 解析组件配置 JSON
 */
function parseComponentConfig<T>(configStr?: string): T | null {
  if (!configStr) return null;
  try {
    return JSON.parse(configStr) as T;
  } catch (e) {
    console.warn('[Parser] JSON 解析失败:', configStr, e);
    return null;
  }
}

/**
 * 从列元数据提取默认值
 */
export function extractDefaultValues(
  columns: Array<{ columnName: string; dataType: string; defaultValue?: any }>
): Record<string, any> {
  const defaults: Record<string, any> = {};

  for (const col of columns) {
    if (col.defaultValue !== undefined && col.defaultValue !== null) {
      defaults[col.columnName] = col.defaultValue;
    } else {
      // 约定：数字类型默认 0，文本类型默认空字符串
      defaults[col.columnName] = col.dataType === 'number' ? 0 : '';
    }
  }

  return defaults;
}

/**
 * 过滤列定义（根据 Tab 的 columns 配置）
 */
export function filterColumns<T extends { field?: string; columnName?: string }>(
  allColumns: T[],
  visibleFields: string[]
): T[] {
  if (!visibleFields || visibleFields.length === 0) return allColumns;

  return allColumns.filter(col => {
    const field = col.field || col.columnName;
    return field && visibleFields.includes(field);
  });
}
