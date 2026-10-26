import { type RowData } from '@/v3/logic/calc-engine';

export function isSameRowIdentity(candidate: RowData, target: RowData) {
  if (candidate === target) return true;
  if (candidate?._rowKey != null && target?._rowKey != null) {
    return candidate._rowKey === target._rowKey;
  }
  if (candidate?.id != null && target?.id != null) {
    return candidate.id === target.id;
  }
  return false;
}

export function findRowByIdentity(rows: RowData[], target: RowData) {
  return rows.find(row => isSameRowIdentity(row, target)) ?? target;
}
