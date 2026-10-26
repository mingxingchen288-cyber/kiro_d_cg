import type { ColDef } from 'ag-grid-community';

export interface ApprovalSelectOption { label: string; value: string | number | null }

export function selectColumn(field: string, headerName: string, options: ApprovalSelectOption[], width = 130): ColDef {
  return {
    field, headerName, width, cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: options.map(option => option.value) },
    valueFormatter: params => options.find(option => option.value === params.value)?.label ?? String(params.value ?? '')
  };
}

export function booleanColumn(field: string, headerName = '启用'): ColDef {
  return { field, headerName, width: 70, cellDataType: 'boolean', filter: false };
}

export function largeTextColumn(field: string, headerName: string, width = 300): ColDef {
  return {
    field, headerName, width, tooltipField: field,
    cellEditor: 'agLargeTextCellEditor', cellEditorPopup: true,
    cellEditorParams: { rows: 8, cols: 65, maxLength: 20000 }
  };
}

export const conditionOptions: ApprovalSelectOption[] = [
  { label: '始终满足', value: 'ALWAYS' }, { label: '字段表达式', value: 'EXPRESSION' }, { label: 'SQL 条件', value: 'SQL' }
];
export const modeOptions: ApprovalSelectOption[] = [
  { label: '或签（任一人）', value: 'OR' }, { label: '会签（全部人）', value: 'AND' }
];
export const actionEventOptions: ApprovalSelectOption[] = [
  { label: '本级完成', value: 'NODE_COMPLETED' }, { label: '流程通过', value: 'FLOW_APPROVED' },
  { label: '流程驳回', value: 'FLOW_REJECTED' }, { label: '流程撤销', value: 'FLOW_CANCELED' }
];

