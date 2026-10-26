/** 行数据（含内部状态） */
export interface RowData {
  id: number | null;
  _rowKey?: string;
  [key: string]: any;
}

/**
 * 生成临时 ID（负数，避免与数据库 ID 冲突）
 */
let tempIdCounter = 0;
export function generateTempId(): number {
  return -(Date.now() * 1000 + tempIdCounter++);
}

export function ensureRowKey(row: RowData): string {
  if (!row._rowKey) {
    if (row.id != null && row.id > 0) {
      row._rowKey = `db_${row.id}`;
    } else {
      const uuid =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : Math.random().toString(36).slice(2);
      row._rowKey = `tmp_${uuid}`;
    }
  }
  return row._rowKey;
}

function resolveInternalRowId(row: Record<string, any>, runtimePkColumn?: string | null): number | null {
  const pkField = runtimePkColumn && runtimePkColumn.trim().length > 0 ? runtimePkColumn.trim() : null;
  const candidate = row.id ?? (pkField ? row[pkField] : undefined) ?? row.ID ?? null;
  if (candidate == null || candidate === '') return null;
  const parsed = typeof candidate === 'number' ? candidate : Number(candidate);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * 初始化行数据（添加内部状态字段）
 */
export function initRowData(row: Record<string, any>, isNew = false, runtimePkColumn?: string | null): RowData {
  const nextRow: RowData = {
    ...row,
    id: resolveInternalRowId(row, runtimePkColumn)
  };
  ensureRowKey(nextRow);
  return nextRow;
}
