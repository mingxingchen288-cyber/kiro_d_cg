import type { ColDef, GridApi } from 'ag-grid-community';
import type { GridOptionsRule } from '@/v3/composables/meta-v3/types';

export type ResolvedGridOptions = {
  sideBar?: boolean | Record<string, any>;
  cellSelection?: boolean | Record<string, any>;
  rowModelType?: 'clientSide' | 'serverSide';
  cacheBlockSize?: number;
  maxBlocksInCache?: number;
  /** SSRM: 最大并发请求数 */
  maxConcurrentDatasourceRequests?: number;
  /** SSRM: 请求防抖毫秒数 */
  blockLoadDebounceMillis?: number;
  groupBy?: string[];
  groupColumnName?: string;
  groupDefaultExpanded?: number;
  autoSizeColumns?: boolean;
  autoSizeMode?: 'fitCellContents' | 'fitGridWidth';
};

const DEFAULT_SIDE_BAR = {
  toolPanels: [
    {
      id: 'columns',
      labelDefault: 'Columns',
      labelKey: 'columns',
      iconKey: 'columns',
      toolPanel: 'agColumnsToolPanel',
      minWidth: 180,
      width: 250,
      toolPanelParams: {
        suppressRowGroups: true,
        suppressValues: true,
        suppressPivots: true,
        suppressPivotMode: true,
        suppressColumnFilter: false,
        suppressColumnSelectAll: false,
        suppressColumnExpandAll: false
      }
    },
    {
      id: 'filters',
      labelDefault: 'Filters',
      labelKey: 'filters',
      iconKey: 'filter',
      toolPanel: 'agFiltersToolPanel',
      minWidth: 180,
      width: 250
    }
  ],
  position: 'right' as const,
  defaultToolPanel: ''
};

function normalizeSideBar(value: GridOptionsRule['sideBar'] | GridOptionsRule['enableSidebar']) {
  if (value === true) return DEFAULT_SIDE_BAR;
  if (value === false || value == null) return undefined;
  if (typeof value === 'object') return value;
  return undefined;
}

function normalizeCellSelection(value: GridOptionsRule['cellSelection']) {
  if (value === true || value === false) return value;
  if (typeof value === 'object') return value;
  return undefined;
}

export function normalizeGridOptions(rule?: GridOptionsRule | null): ResolvedGridOptions {
  if (!rule) return {};
  return {
    sideBar: normalizeSideBar(rule.sideBar ?? rule.enableSidebar),
    cellSelection: normalizeCellSelection(rule.cellSelection),
    rowModelType: rule.rowModelType,
    cacheBlockSize: rule.cacheBlockSize,
    maxBlocksInCache: rule.maxBlocksInCache,
    maxConcurrentDatasourceRequests: rule.maxConcurrentDatasourceRequests,
    blockLoadDebounceMillis: rule.blockLoadDebounceMillis,
    groupBy: Array.isArray(rule.groupBy) ? rule.groupBy : undefined,
    groupColumnName: rule.groupColumnName,
    groupDefaultExpanded: rule.groupDefaultExpanded,
    autoSizeColumns: rule.autoSizeColumns,
    autoSizeMode: rule.autoSizeMode
  };
}

export function mergeGridOptions(
  base?: ResolvedGridOptions | null,
  override?: ResolvedGridOptions | null
): ResolvedGridOptions {
  const merged: ResolvedGridOptions = { ...(base || {}) };
  if (!override) return merged;

  const assign = <K extends keyof ResolvedGridOptions>(key: K) => {
    if (override[key] !== undefined) merged[key] = override[key];
  };

  assign('sideBar');
  assign('cellSelection');
  assign('rowModelType');
  assign('cacheBlockSize');
  assign('maxBlocksInCache');
  assign('maxConcurrentDatasourceRequests');
  assign('blockLoadDebounceMillis');
  assign('groupBy');
  assign('groupColumnName');
  assign('groupDefaultExpanded');
  assign('autoSizeColumns');
  assign('autoSizeMode');

  return merged;
}

export function applyGroupByColumns(columns: ColDef[], groupBy?: string[]): ColDef[] {
  if (!groupBy || groupBy.length === 0) return columns;
  const groupSet = new Set(groupBy);
  return columns.map(col => {
    const field = col.field as string | undefined;
    if (!field || !groupSet.has(field)) return col;
    const updated: ColDef = { ...col, rowGroup: true };
    if (updated.hide == null) updated.hide = true;
    return updated;
  });
}

export function buildGridRuntimeOptions(options?: ResolvedGridOptions | null) {
  if (!options) return {};
  const runtimeOptions: Record<string, any> = {};
  if (options.sideBar !== undefined) runtimeOptions.sideBar = options.sideBar;
  if (options.cellSelection !== undefined) runtimeOptions.cellSelection = options.cellSelection;
  if (options.rowModelType) runtimeOptions.rowModelType = options.rowModelType;
  if (options.cacheBlockSize) runtimeOptions.cacheBlockSize = options.cacheBlockSize;
  if (options.maxBlocksInCache != null) runtimeOptions.maxBlocksInCache = options.maxBlocksInCache;
  // SSRM 专用配置
  if (options.rowModelType === 'serverSide') {
    if (options.maxConcurrentDatasourceRequests != null) {
      runtimeOptions.maxConcurrentDatasourceRequests = options.maxConcurrentDatasourceRequests;
    }
    if (options.blockLoadDebounceMillis != null) {
      runtimeOptions.blockLoadDebounceMillis = options.blockLoadDebounceMillis;
    }
  }
  if (options.groupBy && options.groupBy.length > 0) {
    runtimeOptions.autoGroupColumnDef = {
      headerName: options.groupColumnName || '分组',
      minWidth: 200
    };
    runtimeOptions.groupDefaultExpanded = options.groupDefaultExpanded ?? 1;
  }
  return runtimeOptions;
}

export function autoSizeColumnsOnReady(api: GridApi, columns: ColDef[], options?: ResolvedGridOptions | null) {
  if (!options?.autoSizeColumns) return;
  const mode = options.autoSizeMode || 'fitCellContents';
  const hasExplicitWidth = columns.some(col => typeof col.width === 'number' && col.width > 0);
  if (mode === 'fitGridWidth') {
    if (hasExplicitWidth) {
      const colsToAutoSize = columns.filter(col => !col.width && col.field).map(col => col.field as string);
      if (colsToAutoSize.length > 0) {
        api.autoSizeColumns(colsToAutoSize);
      }
      return;
    }
    api.sizeColumnsToFit();
    return;
  }
  const colsToAutoSize = columns.filter(col => !col.width && col.field).map(col => col.field as string);
  if (colsToAutoSize.length > 0) {
    api.autoSizeColumns(colsToAutoSize);
  }
}
