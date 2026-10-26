import type { RowData } from '@/v3/logic/calc-engine';

export function buildCopyExcludedFields(...fields: Array<string | null | undefined>) {
  const excluded = new Set<string>(['id', 'ID']);
  for (const field of fields) {
    if (!field) continue;
    excluded.add(field);
    excluded.add(field.toUpperCase());
    excluded.add(field.toLowerCase());
  }
  return excluded;
}

export function clearCopiedIdentityFields(row: RowData, ...fields: Array<string | null | undefined>) {
  const excluded = buildCopyExcludedFields(...fields);
  excluded.delete('id');
  for (const field of excluded) {
    delete row[field];
  }
}

export function copyRowFields(sourceRow: RowData, targetRow: RowData, excludedFields: Set<string>) {
  for (const [key, value] of Object.entries(sourceRow)) {
    if (!key.startsWith('_') && !excludedFields.has(key)) {
      targetRow[key] = value;
    }
  }
}

export function applyCopiedRowFields(params: {
  sourceRow: RowData;
  targetRow: RowData;
  excludeFields: Array<string | null | undefined>;
  clearFields?: Array<string | null | undefined>;
}) {
  const { sourceRow, targetRow, excludeFields, clearFields = [] } = params;
  const excludedFields = buildCopyExcludedFields(...excludeFields);
  copyRowFields(sourceRow, targetRow, excludedFields);
  if (clearFields.length > 0) {
    clearCopiedIdentityFields(targetRow, ...clearFields);
  }
}
