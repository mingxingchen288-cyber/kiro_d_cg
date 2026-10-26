import type { ColDef } from 'ag-grid-community';
import { attachGroupCellRenderer } from '@/v3/composables/meta-v3/usePageRules';
import { applyGroupByColumns, type ResolvedGridOptions } from '@/v3/composables/meta-v3/grid-options';
import { DIRTY_CELL_CLASS_RULES, mergeCellClassRules } from '@/v3/composables/meta-v3/cell-style';
import { loadTableMeta } from '@/v3/composables/meta-v3/useMetaColumns';
import type { ParsedPageConfig } from '@/v3/logic/calc-engine';

type LoadMetaParams = {
  pageCode: string;
  pageConfig: ParsedPageConfig;
  masterGridKey?: string;
  masterGridOptions: ResolvedGridOptions | null;
  detailGridOptionsByTab: Record<string, ResolvedGridOptions>;
};

type LoadMetaResult = {
  masterColumnDefs: ColDef[];
  masterRowClassGetter?: (params: any) => string | undefined;
  masterColumnMeta: any[];
  masterPkColumn: string;
  masterSumFields: string[];
  detailColumnsByTab: Record<string, ColDef[]>;
  detailRowClassGetterByTab: Record<string, ((params: any) => string | undefined) | undefined>;
  detailColumnMetaByTab: Record<string, any[]>;
  detailFkColumnByTab: Record<string, string>;
  detailPkColumnByTab: Record<string, string>;
  detailSumFieldsByTab: Record<string, string[]>;
};

function resolveRuntimeColumnName(rawColumns: any[], targetColumn?: string | null, fallback = 'ID') {
  const normalizedTarget = String(targetColumn || '').trim().toUpperCase();
  if (normalizedTarget) {
    const byTarget = rawColumns.find(
      col => String(col?.targetColumn || '').trim().toUpperCase() === normalizedTarget
    );
    if (byTarget?.columnName) return String(byTarget.columnName);

    const byColumn = rawColumns.find(
      col => String(col?.columnName || '').trim().toUpperCase() === normalizedTarget
    );
    if (byColumn?.columnName) return String(byColumn.columnName);

    const byQuery = rawColumns.find(
      col => String(col?.queryColumn || '').trim().toUpperCase() === normalizedTarget
    );
    if (byQuery?.columnName) return String(byQuery.columnName);
  }

  return fallback;
}

function extractSumFieldsFromMetadata(columns: Array<{ columnName?: string; rulesConfig?: string }>): string[] {
  const result: string[] = [];
  const seen = new Set<string>();

  for (const col of columns || []) {
    if (!col.columnName || seen.has(col.columnName) || !col.rulesConfig) continue;

    try {
      const config = JSON.parse(col.rulesConfig);
      if (config?.aggFunc === 'sum') {
        result.push(col.columnName);
        seen.add(col.columnName);
      }
    } catch {
      // Ignore invalid rulesConfig.
    }
  }

  return result;
}

export async function loadPageMeta(params: LoadMetaParams): Promise<LoadMetaResult | null> {
  const masterMeta = await loadTableMeta(
    params.pageConfig.masterTableCode,
    params.pageCode,
    params.masterGridKey ?? 'masterGrid'
  );
  if (!masterMeta) {
    return null;
  }

  const masterColumnDefs = mergeCellClassRules(
    attachGroupCellRenderer(applyGroupByColumns(masterMeta.columns, params.masterGridOptions?.groupBy)),
    DIRTY_CELL_CLASS_RULES
  );
  const masterColumnMeta = masterMeta.rawColumns || [];
  const masterPkColumn = resolveRuntimeColumnName(masterColumnMeta, masterMeta.metadata.pkColumn, 'ID');
  const masterSumFields = extractSumFieldsFromMetadata(masterColumnMeta);

  const detailColumnsByTab: Record<string, ColDef[]> = {};
  const detailRowClassGetterByTab: Record<string, ((params: any) => string | undefined) | undefined> = {};
  const detailColumnMetaByTab: Record<string, any[]> = {};
  const detailFkColumnByTab: Record<string, string> = {};
  const detailPkColumnByTab: Record<string, string> = {};
  const detailSumFieldsByTab: Record<string, string[]> = {};

  for (const tab of params.pageConfig.tabs || []) {
    const tableCode = tab.tableCode || params.pageConfig.detailTableCode;
    if (!tableCode) continue;

    const detailMeta = await loadTableMeta(tableCode, params.pageCode, tab.key);
    if (!detailMeta) {
      console.warn(`[load detail meta failed] ${tableCode}`);
      continue;
    }

    const detailColumnMeta = detailMeta.rawColumns || [];
    detailColumnsByTab[tab.key] = mergeCellClassRules(
      applyGroupByColumns(detailMeta.columns, params.detailGridOptionsByTab[tab.key]?.groupBy),
      DIRTY_CELL_CLASS_RULES
    );
    detailRowClassGetterByTab[tab.key] = detailMeta.getRowClass;
    detailColumnMetaByTab[tab.key] = detailColumnMeta;
    detailSumFieldsByTab[tab.key] = extractSumFieldsFromMetadata(detailColumnMeta);

    const fkColumnName = detailMeta.metadata.parentFkColumn;
    detailFkColumnByTab[tab.key] = fkColumnName
      ? detailColumnMeta.find(col => col.columnName.toUpperCase() === fkColumnName.toUpperCase())?.columnName ||
        fkColumnName
      : masterPkColumn;

    detailPkColumnByTab[tab.key] = resolveRuntimeColumnName(detailColumnMeta, detailMeta.metadata.pkColumn, 'ID');
  }

  return {
    masterColumnDefs,
    masterRowClassGetter: masterMeta.getRowClass,
    masterColumnMeta,
    masterPkColumn,
    masterSumFields,
    detailColumnsByTab,
    detailRowClassGetterByTab,
    detailColumnMetaByTab,
    detailFkColumnByTab,
    detailPkColumnByTab,
    detailSumFieldsByTab
  };
}
