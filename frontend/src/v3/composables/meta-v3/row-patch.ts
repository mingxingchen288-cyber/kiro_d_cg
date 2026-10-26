import type { RowData } from '@/v3/logic/calc-engine';

export type RowFieldChange = {
  field: string;
  oldValue: any;
  newValue: any;
};

export function applyRowPatch(row: RowData, patch: Record<string, any>): RowFieldChange[] {
  const changes: RowFieldChange[] = [];

  Object.entries(patch).forEach(([field, value]) => {
    const targetField = String(field || '').trim();
    if (!targetField) return;

    const nextValue = value === undefined ? null : value;
    if (row[targetField] === nextValue) return;

    changes.push({
      field: targetField,
      oldValue: row[targetField],
      newValue: nextValue
    });

    row[targetField] = nextValue;
  });

  return changes;
}
