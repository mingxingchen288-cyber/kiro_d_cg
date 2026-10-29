/**
 * 配置表格的列写法和主题，沿用旧系统 approval-config-columns.ts、ApprovalConfigGrid.vue：
 * 下拉列、启用列、大文本列；行高 28、字体 13px、表头 #f5f7fa、边框 #dce2e9、无圆角。
 * 旧系统用 legacy CSS 主题，本项目其他表格用 Theming API，同一应用不能混用，这里用 themeQuartz.withParams 给出相同的参数。
 */
import { type ColDef, themeQuartz } from 'ag-grid-community';

export interface SelectOption {
  label: string;
  value: string | number | boolean | null;
}

export const configGridTheme = themeQuartz.withParams({
  fontSize: 13,
  fontFamily: 'inherit',
  rowHeight: 28,
  headerHeight: 28,
  cellHorizontalPadding: 9,
  wrapperBorderRadius: 0,
  headerBackgroundColor: '#f5f7fa',
  borderColor: '#dce2e9'
});

export function selectColumn(field: string, headerName: string, options: SelectOption[], width = 130): ColDef {
  return {
    field,
    headerName,
    width,
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: options.map(option => option.value) },
    valueFormatter: params => options.find(option => option.value === params.value)?.label ?? String(params.value ?? '')
  };
}

export function booleanColumn(field: string, headerName = '启用', width = 70): ColDef {
  return { field, headerName, width, cellDataType: 'boolean', filter: false };
}

export function largeTextColumn(field: string, headerName: string, width = 300): ColDef {
  return {
    field,
    headerName,
    width,
    tooltipField: field,
    cellEditor: 'agLargeTextCellEditor',
    cellEditorPopup: true,
    cellEditorParams: { rows: 8, cols: 65, maxLength: 20000 }
  };
}

/** 可双击打开弹窗的列（蓝色，旧系统 .approval-link） */
export function linkColumn(colId: string, headerName: string, width: number, valueGetter: (data: any) => string): ColDef {
  return {
    colId,
    headerName,
    width,
    editable: false,
    cellClass: 'config-link',
    valueGetter: params => (params.data ? valueGetter(params.data) : ''),
    tooltipValueGetter: params => (params.data ? valueGetter(params.data) : '')
  };
}

export const conditionOptions: SelectOption[] = [
  { label: '始终满足', value: 'always' },
  { label: 'SQL 条件', value: 'sql' }
];

export const modeOptions: SelectOption[] = [
  { label: '或签（任一人）', value: 'or' },
  { label: '会签（全部人）', value: 'and' }
];

export const regionOptions: SelectOption[] = [
  { label: '修改内容 · 主表', value: 'master' },
  { label: '修改内容 · 明细', value: 'detail' },
  { label: '受影响单据', value: 'affected' }
];

export const selectionOptions: SelectOption[] = [
  { label: '默认全选，可取消', value: 'checked' },
  { label: '全部执行，不能取消', value: 'all' },
  { label: '不给审批人看，全部执行', value: 'hidden' }
];
