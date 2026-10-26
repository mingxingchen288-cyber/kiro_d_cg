/**
 * 计算引擎模块导出
 */

// 计算器
export {
  type CalcRule,
  type AggRule,
  type FormulaDefinition,
  type CalcRuleDependency,
  type CalcRuntimeScope,
  compileCalcRules,
  compileAggRules,
  calcRowFields,
  calcAggregates,
  getAffectedRules,
  buildCalcRuleDependencies,
  resolveAffectedRuleFieldsByDependencies,
  extractFieldRefsFromExpression,
  extractFieldRefsFromRule,
  normalizeFieldRef,
  isValidIdentifier,
  evalCondition,
  clearCalcCache,
  extractFieldsFromRules
} from './calculator';

// 解析器
export {
  type TabConfig,
  type TabsComponentConfig,
  type DetailGridComponentConfig,
  type MasterGridGlobalConfig,
  type PageComponent,
  type ParsedPageConfig,
  type EnterpriseConfig,
  type NestedConfig,
  type SummaryAggConfig,
  type SummaryColumnConfig,
  parsePageComponents,
  parseTabConfig,
  parseCalcRules,
  parseAggRules,
  extractDefaultValues,
  filterColumns
} from './parser';

// 构建器
export {
  type RowData,
  generateTempId,
  ensureRowKey,
  initRowData
} from './builder';

// 验证器
export {
  type ValidationRule,
  type ValidationError,
  type ValidationResult,
  type ColumnMetadata,
  parseValidationRules,
  validateRow,
  validateRows,
  formatValidationErrors,
  getErrorFields
} from './validator';
