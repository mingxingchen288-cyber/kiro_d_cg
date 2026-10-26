import type { ColDef } from 'ag-grid-community';
import type {
  ParsedPageConfig,
  RowData,
  SummaryAggConfig,
  SummaryColumnConfig,
  TabConfig
} from '@/v3/logic/calc-engine';

export type SummaryConfig = {
  groupLabelField: string;
  groupLabelHeader: string;
  summaryColumns: SummaryColumnConfig[];
  summaryAggregates: SummaryAggConfig[];
};

const DEFAULT_GROUP_LABEL_FIELD = 'groupLabel';
const DEFAULT_GROUP_LABEL_HEADER = '分类';
const EMPTY_SUMMARY_COLUMNS: SummaryColumnConfig[] = [];
const EMPTY_SUMMARY_AGGS: SummaryAggConfig[] = [];

export function resolveSummaryConfig(pageConfig: ParsedPageConfig | null): SummaryConfig {
  const nested = pageConfig?.nestedConfig;
  return {
    groupLabelField: nested?.groupLabelField || DEFAULT_GROUP_LABEL_FIELD,
    groupLabelHeader: nested?.groupLabelHeader || DEFAULT_GROUP_LABEL_HEADER,
    summaryColumns: nested?.summaryColumns?.length ? nested.summaryColumns : EMPTY_SUMMARY_COLUMNS,
    summaryAggregates: nested?.summaryAggregates?.length ? nested.summaryAggregates : EMPTY_SUMMARY_AGGS
  };
}

export function buildSummaryColumnDefs(summaryConfig: SummaryConfig): ColDef[] {
  const labelField = summaryConfig.groupLabelField || DEFAULT_GROUP_LABEL_FIELD;
  const columns = summaryConfig.summaryColumns.filter(col => col.field && col.field !== labelField);
  return [
    {
      field: labelField,
      headerName: summaryConfig.groupLabelHeader || DEFAULT_GROUP_LABEL_HEADER,
      cellRenderer: 'agGroupCellRenderer',
      minWidth: 150
    },
    ...columns.map(col => ({
      field: col.field,
      headerName: col.headerName,
      width: col.width || 120,
      type: 'numericColumn'
    }))
  ];
}

function calcAggregateValue(agg: SummaryAggConfig, rows: RowData[]): number {
  const values = rows.map(row => Number(row[agg.sourceField]) || 0);
  switch (agg.algorithm) {
    case 'SUM':
      return values.reduce((sum, value) => sum + value, 0);
    case 'AVG':
      return values.length > 0 ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
    case 'COUNT':
      return rows.length;
    case 'MAX':
      return values.length > 0 ? Math.max(...values) : 0;
    case 'MIN':
      return values.length > 0 ? Math.min(...values) : 0;
    default:
      return 0;
  }
}

export function buildSummaryRows(params: {
  masterId: number;
  masterRowKey: string;
  pageConfig: ParsedPageConfig | null;
  detailCache: Map<string, Record<string, RowData[]>>;
  summaryConfig?: SummaryConfig;
  isRowDeleted?: (row: RowData) => boolean;
}): RowData[] {
  const { masterId, masterRowKey, pageConfig, detailCache } = params;
  const summaryConfig = params.summaryConfig || resolveSummaryConfig(pageConfig);
  const cached = detailCache.get(masterRowKey);
  if (!pageConfig || !cached) return [];

  return (pageConfig.tabs || []).map(tab =>
    buildSummaryRow({
      masterId,
      masterRowKey,
      tab,
      rows: cached[tab.key] || [],
      summaryConfig,
      isRowDeleted: params.isRowDeleted
    })
  );
}

export function buildSummaryRow(params: {
  masterId: number;
  masterRowKey: string;
  tab: TabConfig;
  rows: RowData[];
  summaryConfig: SummaryConfig;
  isRowDeleted?: (row: RowData) => boolean;
}): RowData {
  const { masterId, masterRowKey, tab, rows, summaryConfig, isRowDeleted } = params;
  const activeRows = rows.filter(row => !(isRowDeleted ? isRowDeleted(row) : false));
  const aggregates: Record<string, number> = {};
  for (const agg of summaryConfig.summaryAggregates) {
    aggregates[agg.targetField] = calcAggregateValue(agg, activeRows);
  }

  return {
    id: null,
    _tabKey: tab.key,
    _masterId: masterId,
    _masterRowKey: masterRowKey,
    _detailRows: rows,
    [summaryConfig.groupLabelField]: tab.title,
    ...aggregates
  };
}

export function getSummaryRowId(masterRowKey: string, tabKey: string): string {
  return `${masterRowKey}_${tabKey}`;
}

export function applySummaryRowValues(rowNode: any, summaryRow: RowData, summaryConfig: SummaryConfig): void {
  const fields = new Set<string>();
  for (const agg of summaryConfig.summaryAggregates) fields.add(agg.targetField);
  for (const col of summaryConfig.summaryColumns) fields.add(col.field);
  fields.add(summaryConfig.groupLabelField);

  for (const field of fields) {
    if (!field || field.startsWith('_')) continue;
    if (rowNode.data?.[field] !== summaryRow[field]) {
      rowNode.setDataValue(field, summaryRow[field]);
    }
  }

  if (summaryRow._detailRows) {
    rowNode.data._detailRows = summaryRow._detailRows;
  }
}
