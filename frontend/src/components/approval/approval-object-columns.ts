import type { ColDef } from 'ag-grid-community';
import type { ApprovalRuntimeObject, ApprovalRuntimeObjectColumn } from '@/service/api/approval-runtime';

const statusNames: Record<string, string> = {
  PENDING: '待审批', APPROVED: '已通过', REJECTED: '已驳回', CANCELED: '已撤销'
};

function displayValue(value: unknown) {
  if (value == null) return '';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

export function buildApprovalObjectColumns(
  objects: ApprovalRuntimeObject[],
  definitions: ApprovalRuntimeObjectColumn[] = []
): ColDef<ApprovalRuntimeObject>[] {
  const displayColumns: ApprovalRuntimeObjectColumn[] = definitions.length
    ? definitions
    : [...new Set(objects.flatMap(object => Object.keys(object.values || {})))].map(field => ({ field, label: field }));
  return [
    { field: 'label', headerName: '审批对象', minWidth: 180, flex: 1 },
    { field: 'tableCode', headerName: '业务表', width: 140 },
    { field: 'status', headerName: '对象结果', width: 100, valueFormatter: params => statusNames[params.value] || params.value },
    ...displayColumns.map(column => ({
      colId: `value:${column.field}`,
      headerName: column.label || column.headerName || column.field,
      minWidth: 140,
      valueGetter: (params: { data?: ApprovalRuntimeObject }) => params.data?.values?.[column.field],
      valueFormatter: (params: { value: unknown }) => displayValue(params.value)
    }))
  ];
}
