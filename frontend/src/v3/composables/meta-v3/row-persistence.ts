import { type RowData } from '@/v3/logic/calc-engine';

export function isPersistedRow(row: RowData | null | undefined) {
  const numericId = typeof row?.id === 'number' ? row.id : Number(row?.id);
  return Number.isFinite(numericId) && numericId > 0;
}
