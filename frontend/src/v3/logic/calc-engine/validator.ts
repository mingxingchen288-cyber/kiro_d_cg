/**
 * 数据验证器
 * 从 COLUMN_METADATA.RULES_CONFIG 提取验证规则
 * 支持 required, notZero, min, max, pattern
 */

// ==================== 类型定义 ====================

/** 验证规则（从 COLUMN_METADATA.RULES_CONFIG 解析） */
export interface ValidationRule {
  field: string;
  required?: boolean;
  notZero?: boolean;
  min?: number;
  max?: number;
  pattern?: string;
  message?: string; // 自定义错误消息
}

/** 验证错误 */
export interface ValidationError {
  field: string;
  rowId: number | string;
  message: string;
  value: any;
}

/** 验证结果 */
export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

/** 列元数据（含验证规则） */
export interface ColumnMetadata {
  columnName: string;
  headerText: string;
  dataType: string;
  rulesConfig?: string; // JSON 字符串
}

// ==================== 解析函数 ====================

/**
 * 从列元数据解析验证规则
 */
export function parseValidationRules(columns: ColumnMetadata[]): ValidationRule[] {
  const rules: ValidationRule[] = [];

  for (const col of columns) {
    let hasRule = false;
    let required = false;
    let notZero = false;
    let min: number | undefined;
    let max: number | undefined;
    let pattern: string | undefined;
    let ruleMessage: string | undefined;

    // 列级 required 字段（来自 T_COST_COLUMN_METADATA.REQUIRED）
    if ((col as any).required === true || (col as any).required === 1) {
      required = true;
      hasRule = true;
    }

    // rulesConfig 中的验证配置
    if (col.rulesConfig) {
      try {
        const config = JSON.parse(col.rulesConfig);
        const validation = config.validation || config;

        if (validation.required) { required = true; hasRule = true; }
        if (validation.notZero) { notZero = true; hasRule = true; }
        if (validation.min !== undefined) { min = validation.min; hasRule = true; }
        if (validation.max !== undefined) { max = validation.max; hasRule = true; }
        if (validation.pattern) { pattern = validation.pattern; hasRule = true; }
        if (validation.message) ruleMessage = validation.message;
      } catch (e) {
        console.warn(`[Validator] 解析 ${col.columnName} 的 rulesConfig 失败:`, e);
      }
    }

    if (hasRule) {
      rules.push({
        field: col.columnName,
        required,
        notZero,
        min,
        max,
        pattern,
        message: ruleMessage
      });
    }
  }

  return rules;
}

// ==================== 验证函数 ====================

/**
 * 验证单行数据
 */
export function validateRow(
  row: Record<string, any>,
  rules: ValidationRule[],
  columns: ColumnMetadata[]
): ValidationError[] {
  const errors: ValidationError[] = [];
  const rowId = row.id;

  for (const rule of rules) {
    const value = row[rule.field];
    const col = columns.find(c => c.columnName === rule.field);
    const fieldLabel = col?.headerText || rule.field;

    // required: 必填
    if (rule.required) {
      if (value === undefined || value === null || value === '') {
        errors.push({
          field: rule.field,
          rowId,
          message: rule.message || `${fieldLabel} 不能为空`,
          value
        });
        continue; // 必填未通过，跳过其他验证
      }
    }

    // 空值跳过后续验证
    if (value === undefined || value === null || value === '') continue;

    // notZero: 不能为零
    if (rule.notZero && Number(value) === 0) {
      errors.push({
        field: rule.field,
        rowId,
        message: rule.message || `${fieldLabel} 不能为零`,
        value
      });
    }

    // min: 最小值
    if (rule.min !== undefined && Number(value) < rule.min) {
      errors.push({
        field: rule.field,
        rowId,
        message: rule.message || `${fieldLabel} 不能小于 ${rule.min}`,
        value
      });
    }

    // max: 最大值
    if (rule.max !== undefined && Number(value) > rule.max) {
      errors.push({
        field: rule.field,
        rowId,
        message: rule.message || `${fieldLabel} 不能大于 ${rule.max}`,
        value
      });
    }

    // pattern: 正则匹配
    if (rule.pattern) {
      try {
        const regex = new RegExp(rule.pattern);
        if (!regex.test(String(value))) {
          errors.push({
            field: rule.field,
            rowId,
            message: rule.message || `${fieldLabel} 格式不正确`,
            value
          });
        }
      } catch (e) {
        console.warn(`[Validator] 正则表达式无效: ${rule.pattern}`);
      }
    }
  }

  return errors;
}

/**
 * 验证多行数据
 */
export function validateRows(
  rows: Record<string, any>[],
  rules: ValidationRule[],
  columns: ColumnMetadata[]
): ValidationResult {
  const errors: ValidationError[] = [];

  for (const row of rows) {
    // 跳过已删除的行

    const rowErrors = validateRow(row, rules, columns);
    errors.push(...rowErrors);
  }

  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * 格式化验证错误为用户友好的消息
 */
export function formatValidationErrors(errors: ValidationError[]): string {
  if (errors.length === 0) return '';

  // 按行分组
  const byRow = new Map<number | string, ValidationError[]>();
  for (const err of errors) {
    const list = byRow.get(err.rowId) || [];
    list.push(err);
    byRow.set(err.rowId, list);
  }

  const messages: string[] = [];
  for (const [rowId, rowErrors] of byRow) {
    const fields = rowErrors.map(e => e.message).join('、');
    messages.push(`行 ${rowId}: ${fields}`);
  }

  return messages.join('\n');
}

/**
 * 高亮验证错误的单元格（返回需要高亮的 field 列表）
 */
export function getErrorFields(errors: ValidationError[], rowId: number | string): string[] {
  return errors.filter(e => e.rowId === rowId).map(e => e.field);
}
