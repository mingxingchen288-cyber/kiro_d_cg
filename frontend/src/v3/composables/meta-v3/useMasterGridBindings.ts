import { type MaybeRef, type Ref, ref, unref, watch } from 'vue';
import type { CellValueChangedEvent, ColDef, GridReadyEvent } from 'ag-grid-community';
import type { CustomExportConfig } from '@/service/api/export-config';
import { useGridContextMenu } from '@/v3/composables/meta-v3/useGridContextMenu';
import type { CellEditableRule, ContextMenuRule, RowClassRule, RowEditableRule } from '@/v3/composables/meta-v3/types';
import {
  buildCellEditableCallback,
  buildRowClassCallback,
  buildRowEditableCallback,
  buildRowStyleCallback,
  computeSumRow
} from '@/v3/composables/meta-v3/usePageRules';
import {
  type ResolvedGridOptions,
  autoSizeColumnsOnReady,
  buildGridRuntimeOptions
} from '@/v3/composables/meta-v3/grid-options';
import { DIRTY_CELL_CLASS_RULES } from '@/v3/composables/meta-v3/cell-style';
import { ensureRowKey } from '@/v3/logic/calc-engine';
import type { RowStateApi } from '@/v3/composables/meta-v3/useWorkingSetStore';

// 用于追踪已包装 editable 的列定义
const wrappedEditableColumns = new WeakSet<ColDef>();

type MasterGridBindingDeps = {
  masterGridApi: Ref<any>;
  masterGridKey: MaybeRef<string | null>;
  masterCellEditableRules?: MaybeRef<CellEditableRule[]>;
  masterRowEditableRules?: MaybeRef<RowEditableRule[]>;
  masterRowClassRules?: MaybeRef<RowClassRule[]>;
  masterSumFields?: MaybeRef<string[]>;
  addMasterRow: () => void;
  deleteMasterRow: (row: any) => void;
  copyMasterRow: (row: any) => void;
  addDetailRow: (masterId: number, tabKey: string, masterRowKey?: string) => void;
  deleteDetailRow: (masterId: number, tabKey: string, row: any, masterRowKey?: string) => void;
  copyDetailRow: (masterId: number, tabKey: string, row: any, masterRowKey?: string) => void;
  save: () => void;
  saveGridConfig?: (gridKey: string, api: any, columnApi: any) => void;
  customExportConfigs?: MaybeRef<CustomExportConfig[]>;
  executeCustomExport?: (exportCode: string, mode: 'all' | 'current') => void;
  executeAction?: (
    actionCode: string,
    options?: { data?: Record<string, any>; selectedRow?: Record<string, any> | null }
  ) => Promise<void>;
  rowStateApi?: RowStateApi;
  onMasterCellValueChanged?: (event: any) => Promise<boolean> | boolean;
  onMasterCellClicked?: (event: any) => void;
};

export function useMasterGridBindings(params: {
  deps: MasterGridBindingDeps;
  isUserEditing?: Ref<boolean>;
  metaRowClassGetter?: (params: any) => string | undefined;
  gridOptions?: ResolvedGridOptions | null;
  columnDefs?: Ref<ColDef[]>;
  onSelectionChanged?: (rows: any[]) => void;
  contextMenuConfig?: ContextMenuRule | null;
  dataSource?: any;
  notifyError?: (message: string) => void;
}) {
  const { deps } = params;
  const isUserEditing = params.isUserEditing ?? ref(false);
  const metaRowClassGetter = params.metaRowClassGetter;
  const gridOptions = params.gridOptions || null;

  const cellClassRules = DIRTY_CELL_CLASS_RULES;

  // 缓存 editable 回调，规则变化时自动重建
  let _cachedCellRules: any = null;
  let _cachedRowRules: any = null;
  let _cachedEditableCallback: ((params: any) => boolean) | undefined;

  function getEditableCallback(): ((params: any) => boolean) | undefined {
    const cellRules = unref(deps.masterCellEditableRules) ?? [];
    const rowRules = unref(deps.masterRowEditableRules) ?? [];
    // 规则引用没变就复用缓存
    if (cellRules === _cachedCellRules && rowRules === _cachedRowRules) {
      return _cachedEditableCallback;
    }
    _cachedCellRules = cellRules;
    _cachedRowRules = rowRules;
    if (cellRules.length > 0) {
      _cachedEditableCallback = buildCellEditableCallback(cellRules, rowRules);
    } else if (rowRules.length > 0) {
      _cachedEditableCallback = buildRowEditableCallback(rowRules);
    } else {
      _cachedEditableCallback = undefined;
    }
    return _cachedEditableCallback;
  }

  // 初始回调（用于 contextMenu 等需要引用的地方）
  const editableCallback = getEditableCallback();

  const defaultColDef: ColDef = {
    sortable: true,
    filter: 'agTextColumnFilter',
    resizable: true,
    editable: (p: any) => {
      // 汇总行不可编辑
      if (p.node?.rowPinned) return false;
      const cb = getEditableCallback();
      if (cb) return cb(p);
      return true;
    },
    wrapHeaderText: true,
    autoHeaderHeight: true,
    cellClassRules,
    suppressHeaderMenuButton: true
  };

  function wrapColumnEditable(def: ColDef) {
    if (!def || wrappedEditableColumns.has(def)) return;
    const existing = def.editable;
    def.editable = (params: any) => {
      const base = typeof existing === 'function' ? existing(params) : existing !== false;
      // 动态获取最新的 editable 回调，确保 WebSocket 推送后规则立即生效
      const cb = getEditableCallback();
      if (cb) return base && cb(params);
      return base;
    };
    wrappedEditableColumns.add(def);
  }

  // 始终 watch columnDefs，因为规则可能通过 WebSocket 动态添加
  if (params.columnDefs) {
    watch(
      params.columnDefs,
      defs => {
        if (!Array.isArray(defs)) return;
        defs.forEach(def => wrapColumnEditable(def));
      },
      { immediate: true }
    );
  }

  const autoSizeStrategy = undefined;
  const rowSelection = {
    mode: 'singleRow' as const,
    enableClickSelection: true,
    hideDisabledCheckboxes: true,
    checkboxes: false
  };
  const rowHeight = 28;
  const headerHeight = 28;

  const getRowId = (params: any) => {
    const row = params.data;
    if (!row) return '';
    ensureRowKey(row);
    const rowKey = String(row._rowKey ?? '');
    return rowKey;
  };

  // Row class/style rules (from GRID_STYLE config).
  // 动态获取最新规则，确保 WebSocket 推送后样式立即生效
  let _cachedStyleRules: any = null;
  let _cachedRowClassCallback: ((params: any) => string | undefined) | undefined;
  let _cachedRowStyleCallback: ((params: any) => Record<string, string> | undefined) | undefined;

  function getLatestRowClassCallback() {
    const rules = unref(deps.masterRowClassRules) ?? [];
    if (rules === _cachedStyleRules) return _cachedRowClassCallback;
    _cachedStyleRules = rules;
    _cachedRowClassCallback = buildRowClassCallback(rules);
    _cachedRowStyleCallback = buildRowStyleCallback(rules);
    return _cachedRowClassCallback;
  }

  function getLatestRowStyleCallback() {
    const rules = unref(deps.masterRowClassRules) ?? [];
    if (rules !== _cachedStyleRules) {
      _cachedStyleRules = rules;
      _cachedRowClassCallback = buildRowClassCallback(rules);
      _cachedRowStyleCallback = buildRowStyleCallback(rules);
    }
    return _cachedRowStyleCallback;
  }

  const dataSource = params.dataSource;
  const sumFields = unref(deps.masterSumFields) ?? [];

  /** 更新主表底部汇总行（从当前已渲染的行数据直接计算） */
  function updatePinnedSumRow() {
    if (!sumFields.length) return;
    const api = deps.masterGridApi.value;
    if (!api) return;
    // SSRM 下 forEachNode 不可靠，改用 getRenderedNodes 取当前已加载的行
    const renderedNodes = api.getRenderedNodes?.() ?? [];
    const allRows: any[] = [];
    for (const node of renderedNodes) {
      if (node.data && !node.rowPinned) allRows.push(node.data);
    }
    const sumRow = computeSumRow(allRows, sumFields);
    api.setGridOption('pinnedBottomRowData', sumRow ? [sumRow] : []);
  }

  function getRowClass(params: any): string | undefined {
    const rowStateApi = params?.context?.rowStateApi as
      | { isRowDeleted?: (row: any) => boolean; isRowNew?: (row: any) => boolean }
      | undefined;
    const classes: string[] = [];
    if (rowStateApi?.isRowDeleted?.(params.data)) classes.push('row-deleted');
    if (rowStateApi?.isRowNew?.(params.data)) classes.push('row-new');
    // 应用 ROW_CLASS 规则（动态获取最新回调）
    const ruleClass = getLatestRowClassCallback()?.(params);
    if (ruleClass) classes.push(ruleClass);
    // 应用元数据样式
    const metaClass = metaRowClassGetter?.(params);
    if (metaClass) classes.push(metaClass);
    return classes.length > 0 ? classes.join(' ') : undefined;
  }

  function getRowStyle(params: any): Record<string, string> | undefined {
    return getLatestRowStyleCallback()?.(params);
  }

  const resolveGridKey = (key?: string | null) => (key && key.trim().length > 0 ? key : 'masterGrid');
  const masterGridKey = resolveGridKey(unref(deps.masterGridKey));

  const { getMasterContextMenuItems } = useGridContextMenu({
    addMasterRow: deps.addMasterRow,
    deleteMasterRow: deps.deleteMasterRow,
    copyMasterRow: deps.copyMasterRow,
    addDetailRow: deps.addDetailRow,
    deleteDetailRow: deps.deleteDetailRow,
    copyDetailRow: deps.copyDetailRow,
    save: deps.save,
    saveGridConfig: deps.saveGridConfig,
    customExportConfigs: deps.customExportConfigs,
    executeCustomExport: deps.executeCustomExport,
    executeAction: deps.executeAction,
    masterGridKey,
    masterMenuConfig: params.contextMenuConfig,
    isRowEditable: editableCallback
      ? (row: any) => editableCallback({ data: row, colDef: {}, context: { rowStateApi: deps.rowStateApi } })
      : undefined,
    notifyError: params.notifyError
  });

  function onGridReady(params: GridReadyEvent) {
    deps.masterGridApi.value = params.api;
    params.api.addEventListener('columnVisible', (event: any) => {
      const colId = String(event?.column?.getColId?.() ?? '').trim();
      if (!colId) return;
      const lockedByConfig = new Set<string>((params.api as any)?.__lockedHiddenColumns || []);
      const defs = (params.api.getColumnDefs?.() as ColDef[] | undefined) ?? [];
      defs.forEach(def => {
        const field = String(def?.field ?? '').trim();
        if (!field) return;
        if (def.lockVisible === true || (def as any).suppressColumnsToolPanel === true) {
          lockedByConfig.add(field);
        }
      });
      if (!lockedByConfig.has(colId)) return;
      const visible = event?.visible === true || event?.column?.isVisible?.() === true;
      if (!visible) return;
      params.api.applyColumnState({
        state: [{ colId, hide: true }],
        applyOrder: false
      });
    });
    // V3 强制使用 SSRM - 每次 grid-ready 都设置 datasource
    console.log('[DEBUG] onGridReady - dataSource:', dataSource ? 'exists' : 'null');
    if (dataSource) {
      params.api.setGridOption('serverSideDatasource', dataSource);
      console.log('[DEBUG] serverSideDatasource set successfully');
    }
    const currentDefs = (params.api.getColumnDefs?.() as ColDef[] | undefined) ?? [];
    const hasExplicitWidth = currentDefs.some(def => typeof def.width === 'number' && def.width > 0);
    if (gridOptions?.autoSizeColumns) {
      autoSizeColumnsOnReady(params.api, currentDefs, gridOptions);
    } else if (!hasExplicitWidth) {
      params.api.sizeColumnsToFit();
    }
    // SSRM 数据加载后更新汇总行
    if (sumFields.length) {
      params.api.addEventListener('modelUpdated', () => updatePinnedSumRow());
    }
  }

  function onCellEditingStarted(_event?: any) {
    isUserEditing.value = true;
  }

  function onCellEditingStopped(_event?: any) {
    isUserEditing.value = false;
  }

  async function onCellValueChanged(event: CellValueChangedEvent) {
    await deps.onMasterCellValueChanged?.(event);

    // 任何单元格变化后都重算汇总（calc 联动可能改了求和字段）
    if (sumFields.length) {
      updatePinnedSumRow();
    }
  }

  function onCellClicked(event: any) {
    // 汇总行不响应点击
    if (event.node?.rowPinned) return;
    deps.onMasterCellClicked?.(event);
  }

  function onSelectionChanged() {
    const rows = deps.masterGridApi.value?.getSelectedRows?.() || [];
    params.onSelectionChanged?.(rows);
  }

  function onFilterChanged() {
    // V3 SSRM: AG Grid 会自动感知 filterModel 变化并触发 getRows
    // 无需手动调用 refreshServerSide，否则会导致双重请求
  }

  return {
    isUserEditing,
    cellClassRules,
    defaultColDef,
    gridOptions: buildGridRuntimeOptions(gridOptions),
    autoSizeStrategy,
    rowSelection,
    rowHeight,
    headerHeight,
    getRowId,
    getRowClass,
    getRowStyle,
    getContextMenuItems: getMasterContextMenuItems,
    onGridReady,
    onCellEditingStarted,
    onCellEditingStopped,
    onCellValueChanged,
    onCellClicked,
    onSelectionChanged,
    onFilterChanged
  };
}
