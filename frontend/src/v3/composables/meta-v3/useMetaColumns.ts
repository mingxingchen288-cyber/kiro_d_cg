/**
 * 元数据列定义转换
 * 将后端元数据转换为 AG Grid ColDef
 */
import type { ColDef } from 'ag-grid-community';
import { fetchTableMetadata, fetchTableMetadataWithPermission } from '@/service/api';
import DateCellEditor from '@/v3/components/meta-v3/editors/DateCellEditor.vue';
import TagSelectCellEditor from '@/v3/components/meta-v3/editors/TagSelectCellEditor.vue';
import type { CalcRule } from '@/v3/logic/calc-engine';

type ColumnMetadata = Api.Metadata.ColumnMetadata;

interface NumberFormatConfig {
  precision?: number;
  trimZeros?: boolean;
  roundMode?: 'round' | 'ceil' | 'floor';
  useGrouping?: boolean;
}

const _DEFAULT_NUMBER_PRECISION = 2; // 已废弃，精度由 COLUMN_OVERRIDE 配置控制

/** 样式规则 */
export interface StyleRule {
  condition: StyleCondition;
  cellStyle?: Record<string, string>;
  rowStyle?: Record<string, string>;
  style?: Record<string, string>;
}

/** 样式条件 */
export interface StyleCondition {
  type: 'contains' | 'startsWith' | 'endsWith' | 'equals' | 'compare';
  pattern?: string;
  compareValue?: any;
  operator?: '>' | '>=' | '<' | '<=' | '==' | '!=';
}

/** 行样式规则（用于 getRowClass） */
export interface RowStyleRule {
  columnName: string;
  condition: StyleCondition;
  rowStyle: Record<string, string>;
  className: string;
}

/**
 * 元数据转 AG Grid 列定义
 */
export function metaToColDef(col: ColumnMetadata): ColDef {
  const colDef: ColDef = {
    field: col.columnName,
    headerName: col.headerText,
    editable: Boolean(col.editable),
    sortable: col.sortable !== false,
    resizable: true,
    context: {
      metaColumnId: col.id,
      columnName: col.columnName,
      dataType: col.dataType
    }
  };

  if (col.width && col.width > 0) {
    colDef.width = col.width;
  }
  if (col.visible === false) {
    colDef.hide = true;
  }
  if (col.pinned) {
    colDef.pinned = col.pinned;
  }

  applyDefaultValueEditor(colDef, col);

  switch (col.dataType) {
    case 'number':
      colDef.type = 'numericColumn';
      colDef.valueParser = params => {
        if (params.newValue === '' || params.newValue === null || params.newValue === undefined) {
          return null;
        }
        const val = Number(params.newValue);
        return isNaN(val) ? null : val;
      };
      colDef.valueFormatter = params => formatNumberValue(params.value);
      break;
    case 'date':
      if (col.editable) {
        colDef.cellEditor = DateCellEditor;
        colDef.cellEditorPopup = true;
        colDef.cellEditorPopupPosition = 'under';
      }
      colDef.valueParser = params => normalizeDateValue(params.newValue);
      colDef.valueFormatter = params => {
        if (!params.value) return '';
        return normalizeDateValue(params.value) || '';
      };
      break;
    case 'datetime':
      colDef.valueFormatter = params => {
        if (!params.value) return '';
        const date = new Date(params.value);
        return isNaN(date.getTime()) ? params.value : date.toLocaleString('zh-CN');
      };
      break;
    case 'checkbox':
      colDef.cellRenderer = 'agCheckboxCellRenderer';
      if (col.editable) {
        colDef.cellEditor = 'agCheckboxCellEditor';
      }
      colDef.valueGetter = params => isCheckedValue(params.data?.[col.columnName]);
      colDef.valueSetter = params => {
        if (!params.data) return false;
        const nextValue = isCheckedValue(params.newValue) ? 1 : 0;
        if (Object.is(params.data[col.columnName], nextValue)) {
          return false;
        }
        params.data[col.columnName] = nextValue;
        return true;
      };
      break;
  }

  if (col.rulesConfig) {
    try {
      const config = JSON.parse(col.rulesConfig);
      const numberFormat = resolveNumberFormat(config);
      if (col.dataType === 'number' && numberFormat) {
        colDef.valueFormatter = params => formatNumberValue(params.value, numberFormat);
      }
      if (config.columnControl?.lockVisible === true || config.lockVisible === true) {
        colDef.lockVisible = true;
        colDef.suppressColumnsToolPanel = true;
      }
      applyEditorConfig(colDef, config);
      if (typeof config.aggFunc === 'string' && config.aggFunc.length > 0) {
        colDef.aggFunc = config.aggFunc;
      }

      if (config.comparator) {
        colDef.comparator = getComparator(config.comparator);
      }

      if (config.style && Array.isArray(config.style)) {
        const cellClassRules: Record<string, (params: any) => boolean> = {};

        config.style.forEach((rule: StyleRule, index: number) => {
          const className = `meta-cell-${col.columnName}-${index}`;
          const condition = rule.condition;

          cellClassRules[className] = (params: any) => {
            const value = params.value;
            if (value == null) return false;
            return matchStyleRule(value, condition);
          };
        });

        colDef.cellClassRules = cellClassRules;

        colDef.context = {
          ...(colDef.context || {}),
          styleRules: config.style,
          columnName: col.columnName
        };
      }

      if (config.compare?.enabled) {
        const compareConfig = {
          format: config.compare.format || 'value',
          upColor: config.compare.upColor || '#e53935',
          downColor: config.compare.downColor || '#43a047'
        };
        colDef.cellRenderer = (params: any) => {
          return renderCompareValue(params, col.columnName, compareConfig);
        };
      }
    } catch (e) {
      console.warn(`[useMetaColumns] 解析 rulesConfig 失败: ${col.columnName}`, e);
    }
  }

  return colDef;
}

function isCheckedValue(value: any) {
  if (value === true) return true;
  if (typeof value === 'number') return value !== 0;
  const text = String(value ?? '').trim().toLowerCase();
  return ['1', 'true', 'y', 'yes', '是'].includes(text);
}

function parseDefaultValueConfig(raw: any) {
  if (raw == null || raw === '') return null;
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : { type: 'static', value: raw };
    } catch {
      return { type: 'static', value: raw };
    }
  }
  return typeof raw === 'object' ? raw : { type: 'static', value: raw };
}

function getMultiDefaultOptions(raw: any): string[] {
  const config = parseDefaultValueConfig(raw);
  if (!config || config.type !== 'multi') return [];
  const values = Array.isArray(config.value) ? config.value : String(config.value || '').split(',');
  return values.map((item: any) => String(item).trim()).filter(Boolean);
}

function applyDefaultValueEditor(colDef: ColDef, col: ColumnMetadata) {
  if (!col.editable) return;
  const values = getMultiDefaultOptions(col.defaultValue);
  if (values.length === 0) return;
  colDef.cellEditor = 'agSelectCellEditor';
  colDef.cellEditorParams = { values };
  colDef.valueFormatter = params => (params.value == null ? '' : String(params.value));
}

function normalizeDateValue(value: any): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    const match = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : trimmed;
  }
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return formatLocalDate(value);
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : formatLocalDate(date);
  }
  return String(value);
}

function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function resolveNumberFormat(config: any): NumberFormatConfig | null {
  if (!config || typeof config !== 'object') return null;
  const format = config.format ?? null;
  const precisionRaw = format?.precision ?? config.precision;
  const useGrouping = Boolean(format?.useGrouping ?? config.useGrouping);
  const trimZeros = Boolean(format?.trimZeros ?? config.trimZeros);
  const roundModeRaw = format?.roundMode ?? config.roundMode;
  const roundMode = roundModeRaw === 'ceil' || roundModeRaw === 'floor' ? roundModeRaw : 'round';
  const hasFormat = precisionRaw != null || useGrouping || trimZeros || roundModeRaw != null;
  if (!hasFormat) return null;
  if (precisionRaw == null) {
    return { trimZeros, roundMode, useGrouping };
  }
  const precision = Number(precisionRaw);
  if (!Number.isFinite(precision) || precision < 0) return null;
  return { precision: Math.floor(precision), trimZeros, roundMode, useGrouping };
}

function formatNumberValue(value: any, format?: NumberFormatConfig): string {
  if (value === null || value === undefined || value === '') return '';
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  if (!format) {
    return String(num);
  }
  let rounded = num;
  if (format.precision != null) {
    const factor = 10 ** format.precision;
    switch (format.roundMode) {
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
  }
  let text = format.precision != null ? rounded.toFixed(format.precision) : String(rounded);
  if (format.trimZeros && format.precision != null) {
    text = trimTrailingZeros(text);
  }
  if (format.useGrouping) {
    text = applyThousandsGrouping(text);
  }
  return text;
}

function applyThousandsGrouping(value: string): string {
  const [numberPart, exponentPart] = value.split(/e/i);
  const [integerPart, decimalPart] = numberPart.split('.');
  const sign = integerPart.startsWith('-') ? '-' : '';
  const unsignedInteger = sign ? integerPart.slice(1) : integerPart;
  const groupedInteger = unsignedInteger.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const groupedNumber = `${sign}${groupedInteger}${decimalPart != null ? `.${decimalPart}` : ''}`;
  return exponentPart != null ? `${groupedNumber}e${exponentPart}` : groupedNumber;
}

function normalizeSelectEditorParams(editorType: string, editorParams: any) {
  if (!editorParams || typeof editorParams !== 'object') return editorParams;
  if (editorType !== 'agSelectCellEditor' && editorType !== 'agRichSelectCellEditor' && editorType !== 'tagSelectCellEditor') {
    return editorParams;
  }

  const normalized = { ...editorParams };
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

function applyEditorConfig(colDef: ColDef, config: any) {
  if (!config || typeof config !== 'object') return;
  const editorType = config.editor?.type || config.cellEditor;
  const editorParams = config.editor?.params || config.cellEditorParams;
  if (
    typeof editorType !== 'string' ||
    editorType.length === 0 ||
    editorType === 'lookup' ||
    editorType === 'lookupMultiple'
  ) {
    return;
  }
  if (editorType === 'tagSelectCellEditor') {
    colDef.cellEditor = TagSelectCellEditor;
    colDef.cellEditorPopup = true;
    colDef.cellEditorPopupPosition = 'under';
    colDef.cellEditorParams = normalizeSelectEditorParams(editorType, editorParams || {});
    return;
  }
  colDef.cellEditor = editorType;
  if (editorParams && typeof editorParams === 'object') {
    colDef.cellEditorParams = normalizeSelectEditorParams(editorType, editorParams);
  }
}

function trimTrailingZeros(value: string): string {
  return value.replace(/(?:\.0+|(\.\d+?)0+)$/, '$1');
}

/**
 * 获取自定义排序函数
 */
function getComparator(comparatorName: string) {
  const comparators: Record<string, (valueA: any, valueB: any) => number> = {
    customCategorySort: (valueA: any, valueB: any) => {
      const order: Record<string, number> = {
        原料: 1,
        辅料: 2,
        印字包材: 3,
        非印字包材: 4
      };

      const orderA = order[valueA] || 999;
      const orderB = order[valueB] || 999;

      return orderA - orderB;
    }
  };

  return comparators[comparatorName] || undefined;
}

/**
 * 匹配样式规则
 */
export function matchStyleRule(value: any, condition: StyleCondition): boolean {
  if (!condition) return false;

  const { type, pattern, operator, compareValue } = condition;

  switch (type) {
    case 'contains':
      return String(value).includes(pattern || '');
    case 'startsWith':
      return String(value).startsWith(pattern || '');
    case 'endsWith':
      return String(value).endsWith(pattern || '');
    case 'equals':
      return value === compareValue;
    case 'compare':
      switch (operator) {
        case '>':
          return Number(value) > Number(compareValue);
        case '>=':
          return Number(value) >= Number(compareValue);
        case '<':
          return Number(value) < Number(compareValue);
        case '<=':
          return Number(value) <= Number(compareValue);
        case '==':
          return value == compareValue;
        case '!=':
          return value != compareValue;
        default:
          return false;
      }
    default:
      return false;
  }
}

interface CompareRenderConfig {
  format: string;
  upColor: string;
  downColor: string;
}

function renderCompareValue(params: any, columnName: string, config: CompareRenderConfig): string {
  const value = params.value;
  const data = params.data;

  if (value == null) return '';

  const diff = data?.[`${columnName}Diff`];
  const diffPercent = data?.[`${columnName}DiffPercent`];

  if (diff == null && diffPercent == null) {
    return String(value);
  }

  let diffHtml = '';
  if (diff != null && diff !== 0) {
    const isUp = diff > 0;
    const arrow = isUp ? '↑' : '↓';
    const color = isUp ? config.upColor : config.downColor;

    let diffText = '';
    if (config.format === 'value' || config.format === 'both') {
      diffText = Math.abs(diff).toFixed(2);
    }
    if ((config.format === 'percent' || config.format === 'both') && diffPercent != null) {
      const percentText = `${Math.abs(diffPercent).toFixed(1)}%`;
      diffText = config.format === 'both' ? `${diffText} (${percentText})` : percentText;
    }

    diffHtml = `<span style="color:${color};font-size:11px;margin-left:4px">${arrow}${diffText}</span>`;
  }

  return `<span>${value}</span>${diffHtml}`;
}

/**
 * 从列元数据提取行样式规则
 */
export function extractRowStyleRules(columns: ColumnMetadata[]): RowStyleRule[] {
  const rules: RowStyleRule[] = [];

  columns.forEach(col => {
    if (!col.rulesConfig) return;

    try {
      const config = JSON.parse(col.rulesConfig);
      if (!config.style || !Array.isArray(config.style)) return;

      config.style.forEach((rule: StyleRule, index: number) => {
        if (rule.rowStyle && Object.keys(rule.rowStyle).length > 0) {
          rules.push({
            columnName: col.columnName,
            condition: rule.condition,
            rowStyle: rule.rowStyle,
            className: `meta-row-${col.columnName}-${index}`
          });
        }
      });
    } catch {
      // ignore parse errors
    }
  });

  return rules;
}

/**
 * 创建行样式类函数（用于 AG Grid getRowClass）
 */
export function createRowClassGetter(rules: RowStyleRule[]) {
  if (rules.length === 0) return undefined;

  return (params: any): string | undefined => {
    const data = params.data;
    if (!data) return undefined;

    for (const rule of rules) {
      const value = data[rule.columnName];
      if (value != null && matchStyleRule(value, rule.condition)) {
        return rule.className;
      }
    }

    return undefined;
  };
}

/**
 * 批量转换列定义
 */
export function metaToColDefs(columns: ColumnMetadata[]): ColDef[] {
  return columns.sort((a, b) => a.displayOrder - b.displayOrder).map(metaToColDef);
}

/**
 * 从元数据提取计算规则
 */
export function extractCalcRules(columns: ColumnMetadata[]): CalcRule[] {
  const rules: CalcRule[] = [];

  columns.forEach((col, index) => {
    if (col.rulesConfig) {
      try {
        const config = JSON.parse(col.rulesConfig);
        if (config.calculate) {
          const calc = config.calculate;

          if (calc.formulaField && calc.formulas) {
            rules.push({
              field: col.columnName,
              expression: '',
              triggerFields: [],
              formulaField: calc.formulaField,
              formulas: calc.formulas,
              order: index
            });
          } else if (calc.expression) {
            rules.push({
              field: col.columnName,
              expression: calc.expression,
              triggerFields: calc.triggerFields || [],
              order: index
            });
          }
        }
      } catch (e) {
        console.warn(`[useMetaColumns] 解析 rulesConfig 失败: ${col.columnName}`, e);
      }
    }
  });

  return rules;
}

/**
 * 从元数据提取默认值
 */
export function extractDefaultValues(columns: ColumnMetadata[]): Record<string, any> {
  const defaults: Record<string, any> = {};

  columns.forEach(col => {
    if (col.dataType === 'number') {
      defaults[col.columnName] = 0;
    } else {
      defaults[col.columnName] = '';
    }
  });

  return defaults;
}

/**
 * Lookup 弹窗规则
 */
export interface LookupRule {
  columnName: string;
  lookupCode: string;
  mapping: Record<string, string>;
  multiple?: boolean;
  noFillback?: boolean;
  filterField?: string;
  filterColumn?: string;
  filterValueFrom?: 'row' | 'cell';
}

/**
 * 从元数据提取 lookup 配置
 */
export function extractLookupRules(columns: ColumnMetadata[]): LookupRule[] {
  const rules: LookupRule[] = [];

  columns.forEach(col => {
    if (!col.rulesConfig) return;

    try {
      const config = JSON.parse(col.rulesConfig);
      if (config.lookup?.code && config.lookup?.mapping) {
        rules.push({
          columnName: col.columnName,
          lookupCode: config.lookup.code,
          mapping: config.lookup.mapping,
          multiple: Boolean(config.lookup.multiple || config.cellEditor === 'lookupMultiple' || config.editor?.type === 'lookupMultiple'),
          noFillback: config.lookup.noFillback,
          filterField: config.lookup.filterField,
          filterColumn: config.lookup.filterColumn,
          filterValueFrom: config.lookup.filterValueFrom
        });
      }
    } catch {
      // ignore parse errors
    }
  });

  return rules;
}

/**
 * 加载表元数据并转换
 */
export async function loadTableMeta(tableCode: string, pageCode?: string, gridKey?: string) {
  const { data, error } = pageCode
    ? await fetchTableMetadataWithPermission(tableCode, pageCode, gridKey)
    : await fetchTableMetadata(tableCode);

  if (error || !data) {
    console.error(`[useMetaColumns] 加载元数据失败: ${tableCode}`, error);
    return null;
  }

  const columns = metaToColDefs(data.columns);
  const rowStyleRules = extractRowStyleRules(data.columns);

  injectDynamicStyles(columns, rowStyleRules);

  return {
    metadata: data,
    columns,
    rawColumns: data.columns,
    calcRules: extractCalcRules(data.columns),
    defaultValues: extractDefaultValues(data.columns),
    lookupRules: extractLookupRules(data.columns),
    rowStyleRules,
    getRowClass: createRowClassGetter(rowStyleRules)
  };
}

/**
 * 注入动态样式到页面
 */
function injectDynamicStyles(columns: ColDef[], rowStyleRules: RowStyleRule[] = []) {
  const styleId = 'meta-dynamic-styles';
  let styleEl = document.getElementById(styleId) as HTMLStyleElement;

  if (!styleEl) {
    styleEl = document.createElement('style');
    styleEl.id = styleId;
    document.head.appendChild(styleEl);
  }

  const existingRules = new Set<string>();
  const existingContent = styleEl.textContent || '';
  existingContent.split('\n').forEach(line => {
    const match = line.match(/^\.(meta-(?:cell|row)-[^\s{]+)/);
    if (match) existingRules.add(match[1]);
  });

  const newRules: string[] = [];

  columns.forEach(col => {
    const styleRules = col.context?.styleRules as StyleRule[] | undefined;
    const columnName = col.context?.columnName;

    if (styleRules && columnName) {
      styleRules.forEach((rule: StyleRule, index: number) => {
        const className = `meta-cell-${columnName}-${index}`;

        if (existingRules.has(className)) return;

        const styles = rule.cellStyle || rule.style || {};

        const styleStr = Object.entries(styles)
          .map(([key, value]) => {
            const cssKey = key.replace(/([A-Z])/g, '-$1').toLowerCase();
            return `${cssKey}: ${value}`;
          })
          .join('; ');

        if (styleStr) {
          newRules.push(`.${className} { ${styleStr} !important; }`);
        }
      });
    }
  });

  rowStyleRules.forEach(rule => {
    if (existingRules.has(rule.className)) return;

    const styleStr = Object.entries(rule.rowStyle)
      .map(([key, value]) => {
        const cssKey = key.replace(/([A-Z])/g, '-$1').toLowerCase();
        return `${cssKey}: ${value}`;
      })
      .join('; ');

    if (styleStr) {
      newRules.push(`.ag-row.${rule.className} { ${styleStr} !important; }`);
      newRules.push(`.ag-row.${rule.className} .ag-cell { ${styleStr} !important; }`);
    }
  });

  if (newRules.length > 0) {
    styleEl.textContent = existingContent + (existingContent ? '\n' : '') + newRules.join('\n');
  }
}
