/**
 * Lookup 管理"配置显示列"的数据（C06 第 9 节 `columns`），同旧系统 LookupPanel.vue 的 buildDisplayColumnDrafts、
 * stringifyDisplayColumns：按数据源的列顺序列出，已配置的列带上显示标题和宽度，标题为空时显示字段名。
 * 保存时标题为空或与字段名相同、又没有宽度的列只写列名，其余写 `{"column", "label", "width"}`（没填的项不写）。
 */
import type { LookupColumnItem, LookupContent } from '../core/types';

export interface SourceColumn {
  name: string;
  show: boolean;
  keyword: boolean;
  label: string;
  width: number | null;
}

type ColumnEntry = LookupContent['columns'][number];

function itemOf(entry: ColumnEntry): LookupColumnItem {
  return typeof entry === 'string' ? { column: entry } : entry;
}

/** `columns` 中的列名 */
export function columnNames(columns: ColumnEntry[]): string[] {
  return columns.map(c => itemOf(c).column);
}

/** 表格中"显示列"的文字：有标题时显示标题，否则显示列名 */
export function columnsText(columns: ColumnEntry[]): string {
  return columns.map(c => itemOf(c).label || itemOf(c).column).join(', ');
}

/** 对话框的行：数据源的每一列，带上当前配置（显示、标题、宽度、关键字搜索） */
export function sourceColumnsOf(source: string[], columns: ColumnEntry[], keywordColumns: string[]): SourceColumn[] {
  const current = new Map(columns.map(c => [itemOf(c).column, itemOf(c)]));
  return source.map(name => {
    const item = current.get(name);
    return {
      name,
      show: Boolean(item),
      keyword: keywordColumns.includes(name),
      label: item?.label || name,
      width: item?.width ?? null
    };
  });
}

/** 对话框中勾选显示的列 → `columns` */
export function columnItems(rows: SourceColumn[]): ColumnEntry[] {
  return rows
    .filter(r => r.show)
    .map(r => {
      const label = r.label.trim();
      if ((!label || label === r.name) && !r.width) return r.name;
      const item: LookupColumnItem = { column: r.name };
      if (label && label !== r.name) item.label = label;
      if (r.width) item.width = Number(r.width);
      return item;
    });
}
