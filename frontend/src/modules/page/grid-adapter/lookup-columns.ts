/**
 * grid-adapter：Lookup 对话框结果表格的列（同旧系统 LookupDialog.vue 第 107–116 行）。
 * 有 Lookup 配置的显示列（C05 `lookup.columns`）时按它的顺序，表头为标题，配了宽度的列固定宽度，没配的平分（不小于 120）；
 * 没有时（页面视图没带显示列）按返回值中的列名，表头为列名。
 */
import type { ColDef } from 'ag-grid-community';
import type { FieldValues } from '../../../contracts/command';
import type { LookupColumn } from '../../../contracts/page-view';

export function lookupColumnDefs(columns: LookupColumn[], rows: FieldValues[]): ColDef<FieldValues>[] {
  const shown = columns.length
    ? columns
    : [...new Set(rows.flatMap(row => Object.keys(row)))].map(name => ({ column: name, label: name, width: null }));
  return shown.map(col => ({
    field: col.column,
    headerName: col.label || col.column,
    ...(col.width ? { width: col.width } : { flex: 1, minWidth: 120 }),
    sortable: true,
    resizable: true
  }));
}
