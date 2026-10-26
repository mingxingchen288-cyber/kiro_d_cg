import type { ColDef } from 'ag-grid-community';
import type { RowStateApi } from '@/v3/composables/meta-v3/useWorkingSetStore';

export function isFlagTrue(value: unknown) {
  return value === true || value === 1 || value === '1' || value === 'true';
}

function resolveRowStateApi(params: any): RowStateApi | undefined {
  return params?.context?.rowStateApi;
}

export const DIRTY_CELL_CLASS_RULES: NonNullable<ColDef['cellClassRules']> = {
  'cell-user-changed': (params: any) => {
    const row = params.data;
    const field = params.colDef?.field;
    return resolveRowStateApi(params)?.getFieldChangeType(row, field) === 'user';
  },
  'cell-calc-changed': (params: any) => {
    const row = params.data;
    const field = params.colDef?.field;
    return resolveRowStateApi(params)?.getFieldChangeType(row, field) === 'calc';
  },
  'cell-new': (params: any) => {
    const row = params.data;
    const field = params.colDef?.field;
    const rowStateApi = resolveRowStateApi(params);
    if (!rowStateApi?.isRowNew(row) || rowStateApi.isRowDeleted(row)) return false;
    if (!field) return true;
    return !rowStateApi.getFieldChangeType(row, field);
  },
  'cell-deleted': (params: any) => Boolean(resolveRowStateApi(params)?.isRowDeleted(params.data))
};

export function mergeCellClassRules(
  columns: ColDef[],
  extraRules: ColDef['cellClassRules'] = DIRTY_CELL_CLASS_RULES
): ColDef[] {
  if (!extraRules) return columns;
  return columns.map(col => {
    const merged = { ...(col.cellClassRules || {}), ...(extraRules as Record<string, any>) };
    if (Object.keys(merged).length === 0) return col;
    return { ...col, cellClassRules: merged };
  });
}
