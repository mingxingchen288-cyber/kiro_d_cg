<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, GridReadyEvent } from 'ag-grid-community';
import { ensureRowKey } from '@/v3/logic/calc-engine';
import type { RowData, TabConfig } from '@/v3/logic/calc-engine';
import type { CellEditableRule, RowEditableRule } from '@/v3/composables/meta-v3/types';
import type { RowStateApi } from '@/v3/composables/meta-v3/useWorkingSetStore';
import {
  type ResolvedGridOptions,
  autoSizeColumnsOnReady,
  buildGridRuntimeOptions
} from '@/v3/composables/meta-v3/grid-options';
import { buildCellEditableCallback, buildRowEditableCallback } from '@/v3/composables/meta-v3/usePageRules';

const props = defineProps<{
  tab: TabConfig;
  rows: RowData[];
  columns: ColDef[];
  rowEditableRules?: RowEditableRule[];
  cellEditableRules?: CellEditableRule[];
  rowClassGetter?: (params: any) => string | undefined;
  gridOptions?: ResolvedGridOptions;
  cellClassRules: ColDef['cellClassRules'];
  contextMenuItems?: (params: any) => any[];
  showTitle?: boolean;
  tabCount?: number;
  refreshDetailRowHeight?: () => void;
  registerDetailGridApi: (tabKey: string, api: any) => void;
  unregisterDetailGridApi?: (tabKey: string, api: any) => void;
  applyGridConfig?: (gridKey: string, api: any, columnApi: any, sourceColumnDefs?: ColDef[]) => void;
  rowStateApi: RowStateApi;
  onCellValueChanged: (event: any) => void;
  onCellClicked: (event: any) => void;
  onCellEditingStarted: () => void;
  onCellEditingStopped: () => void;
  sumFields?: string[];
}>();

const gridApi = ref<any>(null);
const calculatedHeight = ref<number>(120);
const wrappedEditableColumns = new WeakSet<ColDef>();

let cachedCellRules: CellEditableRule[] | null = null;
let cachedRowRules: RowEditableRule[] | null = null;
let cachedEditableCallback: ((params: any) => boolean) | undefined;

function getEditableCallback(): ((params: any) => boolean) | undefined {
  const cellRules = props.cellEditableRules || [];
  const rowRules = props.rowEditableRules || [];
  if (cellRules === cachedCellRules && rowRules === cachedRowRules) {
    return cachedEditableCallback;
  }
  cachedCellRules = cellRules;
  cachedRowRules = rowRules;
  if (cellRules.length > 0) {
    cachedEditableCallback = buildCellEditableCallback(cellRules, rowRules);
  } else if (rowRules.length > 0) {
    cachedEditableCallback = buildRowEditableCallback(rowRules);
  } else {
    cachedEditableCallback = undefined;
  }
  return cachedEditableCallback;
}

function wrapColumnEditable(def: ColDef) {
  if (!def || wrappedEditableColumns.has(def)) return;
  const existing = def.editable;
  def.editable = (params: any) => {
    const base = typeof existing === 'function' ? existing(params) : existing !== false;
    const callback = getEditableCallback();
    if (callback) return base && callback(params);
    return base;
  };
  wrappedEditableColumns.add(def);
}

// 计算grid高度
function calcHeight(): number {
  // 如果没有指定tabCount，说明不是堆叠模式，使用默认高度
  if (!props.tabCount) {
    return 300;
  }

  const rowHeight = 28;
  const headerHeight = 28;
  const minRows = 2;
  const tabCount = props.tabCount;
  const gap = 16;
  const padding = 80; // 增加padding余量

  // 可用总高度（屏幕高度 - 主表行高 - padding - 子表间隙）
  const availableHeight = window.innerHeight - 100 - padding - gap * (tabCount - 1);
  // 每个子表最大可用高度
  const maxHeight = Math.floor(availableHeight / tabCount);
  // 最小高度 = 表头 + 2行
  const minHeight = headerHeight + rowHeight * minRows;

  // 实际内容高度 = 表头 + 数据行 + 少量余量
  const dataRows = props.rows?.length || 0;
  const contentHeight = headerHeight + Math.max(dataRows, minRows) * rowHeight + 20;

  // 限制在最小和最大之间
  return Math.max(minHeight, Math.min(contentHeight, maxHeight));
}

// 监听rows变化，更新高度
watch(
  () => props.rows?.length,
  () => {
    calculatedHeight.value = calcHeight();
  },
  { immediate: true }
);

// 监听gridApi的rowData变化（处理新增/删除行）
function updateHeightFromGrid() {
  if (gridApi.value) {
    const rowCount = gridApi.value.getDisplayedRowCount?.() || 0;
    const rowHeight = 28;
    const headerHeight = 28;
    const minRows = 2;
    const tabCount = props.tabCount || 1;
    const gap = 16;
    const padding = 80;

    const availableHeight = window.innerHeight - 100 - padding - gap * (tabCount - 1);
    const maxHeight = Math.floor(availableHeight / tabCount);
    const minHeight = headerHeight + rowHeight * minRows;
    const contentHeight = headerHeight + Math.max(rowCount, minRows) * rowHeight + 20;

    calculatedHeight.value = Math.max(minHeight, Math.min(contentHeight, maxHeight));

    // 通知主表刷新detail行高度
    props.refreshDetailRowHeight?.();
  }
}

const gridWrapStyle = computed(() => {
  return { height: `${calculatedHeight.value}px` };
});

const rowSelection = { mode: 'multiRow', checkboxes: true, enableClickSelection: true } as const;

const defaultColDef = computed<ColDef>(() => ({
  sortable: true,
  filter: true,
  resizable: true,
  editable: (p: any) => {
    if (p.node?.rowPinned) return false;
    const callback = getEditableCallback();
    if (callback) return callback(p);
    return true;
  },
  wrapHeaderText: true,
  autoHeaderHeight: true,
  cellClassRules: props.cellClassRules,
  suppressHeaderMenuButton: true
}));

const gridRuntimeOptions = computed(() => {
  const opts = buildGridRuntimeOptions(props.gridOptions);
  // 有求和字段时启用 AG Grid 原生底部汇总行
  if (props.sumFields?.length) {
    opts.grandTotalRow = 'bottom';
  }
  return opts;
});

// AG Grid 原生汇总：aggFunc 已通过 applyColumnOverrides 设置在列上
// grandTotalRow 通过 gridRuntimeOptions 注入

function getRowId(params: any) {
  const row = params.data as RowData | undefined;
  if (!row) return '';
  return ensureRowKey(row);
}

function getRowClass(params: any): string | undefined {
  const classes: string[] = [];
  if (props.rowStateApi.isRowDeleted(params.data)) classes.push('row-deleted');
  if (props.rowStateApi.isRowNew(params.data)) classes.push('row-new');
  const metaClass = props.rowClassGetter?.(params);
  if (metaClass) classes.push(metaClass);
  return classes.length > 0 ? classes.join(' ') : undefined;
}

function onGridReady(event: GridReadyEvent) {
  gridApi.value = event.api;
  props.registerDetailGridApi(props.tab.key, event.api);
  event.api.addEventListener('columnVisible', (columnEvent: any) => {
    const colId = String(columnEvent?.column?.getColId?.() ?? '').trim();
    if (!colId) return;
    const lockedByConfig = new Set<string>((event.api as any)?.__lockedHiddenColumns || []);
    const defs = (event.api.getColumnDefs?.() as ColDef[] | undefined) ?? [];
    defs.forEach(def => {
      const field = String(def?.field ?? '').trim();
      if (!field) return;
      if (def.lockVisible === true || (def as any).suppressColumnsToolPanel === true) {
        lockedByConfig.add(field);
      }
    });
    if (!lockedByConfig.has(colId)) return;
    const visible = columnEvent?.visible === true || columnEvent?.column?.isVisible?.() === true;
    if (!visible) return;
    event.api.applyColumnState({
      state: [{ colId, hide: true }],
      applyOrder: false
    });
  });
  props.applyGridConfig?.(props.tab.key, event.api, null, props.columns);

  if (props.tab.initialSort && props.tab.initialSort.length > 0) {
    event.api.applyColumnState({
      state: props.tab.initialSort,
      defaultState: { sort: null }
    });
  }

  const gridOptions = props.gridOptions;
  if (gridOptions?.autoSizeColumns) {
    autoSizeColumnsOnReady(event.api, props.columns, gridOptions);
  }
}

onBeforeUnmount(() => {
  if (gridApi.value) {
    props.unregisterDetailGridApi?.(props.tab.key, gridApi.value);
  }
  gridApi.value = null;
});

function onCellValueChanged(event: any) {
  props.onCellValueChanged(event);
  // 刷新聚合汇总（grandTotalRow 不会自动重算）
  if (props.sumFields?.length) {
    event.api?.refreshClientSideRowModel?.('aggregate');
  }
}

function onCellClicked(event: any) {
  props.onCellClicked(event);
}

function onCellEditingStarted() {
  props.onCellEditingStarted();
}

function onCellEditingStopped() {
  props.onCellEditingStopped();
}

watch(
  () => props.rows,
  rows => {
    if (gridApi.value) {
      gridApi.value.setGridOption('rowData', rows || []);
    }
  },
  { deep: false }
);

watch(
  () => props.columns,
  cols => {
    if (Array.isArray(cols)) {
      cols.forEach(def => wrapColumnEditable(def));
    }
    if (gridApi.value && cols) {
      gridApi.value.setGridOption('columnDefs', cols);
    }
  },
  { deep: false, immediate: true }
);
</script>

<template>
  <div class="detail-grid-wrap" :style="gridWrapStyle">
    <div v-if="showTitle" class="detail-watermark">{{ tab.title }}</div>
    <AgGridVue
      class="ag-theme-quartz"
      style="width: 100%; height: 100%"
      :row-data="rows"
      :context="{ rowStateApi }"
      :column-defs="columns"
      :default-col-def="defaultColDef"
      :get-row-id="getRowId"
      :get-row-class="getRowClass"
      :row-selection="rowSelection"
      :get-context-menu-items="contextMenuItems"
      :row-height="28"
      :header-height="28"
      v-bind="gridRuntimeOptions"
      @grid-ready="onGridReady"
      @row-data-updated="updateHeightFromGrid"
      @cell-value-changed="onCellValueChanged"
      @cell-clicked="onCellClicked"
      @cell-editing-started="onCellEditingStarted"
      @cell-editing-stopped="onCellEditingStopped"
    />
  </div>
</template>

<style scoped>
.detail-grid-wrap {
  min-height: 120px;
  width: 100%;
  display: flex;
  flex-direction: column;
  position: relative;
}

.detail-watermark {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 32px;
  font-weight: 700;
  color: rgba(0, 0, 0, 0.06);
  pointer-events: none;
  z-index: 1;
  white-space: nowrap;
  user-select: none;
}
</style>
