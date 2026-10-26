<script setup lang="ts">
import { computed, unref } from 'vue';
import { NButton, NSpace, useDialog } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, GridReadyEvent } from 'ag-grid-community';
import type { PageComponentWithRules, ToolbarRule } from '@/v3/composables/meta-v3/types';
import type { ComponentStateByKey, MetaRuntime } from '@/v3/composables/meta-v3/runtime/types';
import { handleToolbarAction } from '@/v3/composables/meta-v3/useToolbarAction';
import { useMasterGridBindings } from '@/v3/composables/meta-v3/useMasterGridBindings';
import ApprovalActionGroup from '@/v3/components/approval/ApprovalActionGroup.vue';

type GridConfig = {
  width?: string | number;
  height?: string | number;
  className?: string;
};

const props = defineProps<{
  component: PageComponentWithRules;
  runtime: MetaRuntime;
}>();

const dialog = useDialog();
const runtime = props.runtime as any;
const meta = runtime?.meta;
const rowStateApi = runtime?.rowStateApi;
const lookup = runtime?.lookup;
const actions = runtime?.actions;
const gridConfigApi = runtime?.gridConfig;
const customExportConfigs = actions?.customExportConfigs;
const executeCustomExport = actions?.executeCustomExport;
const executeAction = actions?.executeAction;
const save = actions?.save;
const saveGridConfig = gridConfigApi?.saveGridConfig;

function parseGridConfig(config?: string): GridConfig {
  if (!config) return {};
  try {
    return JSON.parse(config) as GridConfig;
  } catch (error) {
    console.warn('[MetaV3] grid config parse failed', error);
    return {};
  }
}

function resolveComponentState(): Record<string, any> {
  const source = runtime?.state?.componentStateByKey;
  const stateByKey = (source && 'value' in source ? source.value : source) as ComponentStateByKey | undefined;
  if (!stateByKey) return {};
  return stateByKey[props.component.componentKey] || {};
}

const state = computed(() => resolveComponentState());
const gridConfig = computed(() => parseGridConfig(props.component.componentConfig));
const masterGridKey = computed(() => unwrap(meta?.masterGridKey) ?? null);
const isMasterGrid = computed(
  () => props.component.componentType === 'GRID' && props.component.componentKey === masterGridKey.value
);

let cachedDataSource: any = null;
function getMasterDataSource() {
  if (!cachedDataSource) {
    const masterGridOptions = unwrap(meta?.masterGridOptions);
    cachedDataSource = runtime?.workingSet?.createServerSideDataSource({
      pageSize: masterGridOptions?.cacheBlockSize || 100
    });
  }
  return cachedDataSource;
}

const masterBindings = useMasterGridBindings({
  deps: {
    masterGridApi: runtime.masterGridApi,
    masterGridKey: meta?.masterGridKey,
    masterCellEditableRules: meta?.masterCellEditableRules,
    masterRowEditableRules: meta?.masterRowEditableRules,
    masterRowClassRules: meta?.masterRowClassRules,
    masterSumFields: meta?.masterSumFields,
    addMasterRow: runtime?.mutations?.addMasterRow,
    deleteMasterRow: runtime?.mutations?.deleteMasterRow,
    copyMasterRow: runtime?.mutations?.copyMasterRow,
    addDetailRow: runtime?.mutations?.addDetailRow,
    deleteDetailRow: runtime?.mutations?.deleteDetailRow,
    copyDetailRow: runtime?.mutations?.copyDetailRow,
    rowStateApi,
    save,
    saveGridConfig,
    customExportConfigs,
    executeCustomExport,
    executeAction,
    onMasterCellValueChanged: runtime?.mutations?.onMasterCellValueChanged,
    onMasterCellClicked: lookup?.onMasterCellClicked
  },
  metaRowClassGetter: unwrap(meta?.masterRowClassGetter),
  gridOptions: unwrap(meta?.masterGridOptions) ?? null,
  columnDefs: meta?.masterColumnDefs,
  contextMenuConfig: unwrap(meta?.masterContextMenu) ?? null,
  dataSource: getMasterDataSource()
});

// 工具栏
const masterToolbar = computed<ToolbarRule | null>(() => {
  const source = meta?.masterToolbar;
  return unwrap(source) ?? null;
});

const toolbarItems = computed(() => {
  const toolbar = masterToolbar.value;
  if (!toolbar?.items) return [];
  return toolbar.items.filter((item: any) => item.visible !== false);
});

const NAIVE_BUTTON_TYPES = new Set(['default', 'primary', 'info', 'success', 'warning', 'error', 'tertiary']);
function toNaiveButtonType(type?: string): 'default' | 'primary' | 'info' | 'success' | 'warning' | 'error' | 'tertiary' {
  if (type && NAIVE_BUTTON_TYPES.has(type)) return type as any;
  return 'default';
}

const canAddRow = computed(() => runtime?.permissions?.hasButton?.('addRow') === true);
const canDeleteRow = computed(() => runtime?.permissions?.hasButton?.('deleteRow') === true);
const canSave = computed(() => runtime?.permissions?.hasButton?.('save') === true);

async function handleToolbarClick(item: any) {
  if (!executeAction) {
    console.warn('[MetaGridV3] executeAction not found in runtime');
    return;
  }

  const api = runtime?.masterGridApi?.value;
  const selectedRows = api?.getSelectedRows?.() || [];
  const selectedRow = selectedRows[0] || null;
  const action = item?.action;

  switch (action) {
    case 'addRow':
      runtime?.mutations?.addMasterRow?.();
      return;
    case 'copyRow':
      if (!selectedRow) {
        window.$message?.warning('请先选择一行');
        return;
      }
      runtime?.mutations?.copyMasterRow?.(selectedRow);
      return;
    case 'deleteRow':
      if (selectedRows.length === 0) {
        window.$message?.warning('请选择要删除的行');
        return;
      }
      selectedRows.forEach((row: any) => runtime?.mutations?.deleteMasterRow?.(row));
      return;
    case 'save':
      await save?.();
      return;
    case 'saveGridConfig':
      if (api) await saveGridConfig?.(masterGridKey.value || props.component.componentKey, api, null);
      return;
    default:
      break;
  }

  await handleToolbarAction(item, {
    getSelectedRow: () => selectedRow,
    executeAction,
    dialog
  });
}

function getSelectedMasterRow() {
  const api = runtime?.masterGridApi?.value;
  const selectedRows = api?.getSelectedRows?.() || [];
  return selectedRows[0] || null;
}

function deleteSelectedMasterRows() {
  const api = runtime?.masterGridApi?.value;
  const selectedRows = api?.getSelectedRows?.() || [];
  if (selectedRows.length === 0) {
    window.$message?.warning('请选择要删除的行');
    return;
  }
  selectedRows.forEach((row: any) => runtime?.mutations?.deleteMasterRow?.(row));
}

function toCssSize(value: string | number | undefined) {
  if (value == null) return undefined;
  return typeof value === 'number' ? `${value}px` : value;
}

function unwrap<T>(value: T) {
  return unref(value as any);
}

const containerStyle = computed(() => ({
  width: toCssSize(gridConfig.value.width) || '100%',
  height: toCssSize(gridConfig.value.height) || '100%'
}));

const gridClass = computed(() => gridConfig.value.className || '');

const status = computed(() => state.value.status || 'ready');
const errorMessage = computed(() => state.value.error?.message || '组件加载失败');
const contextMenuEnabled = computed(() => runtime?.features?.contextMenu !== false);

const columnDefs = computed<ColDef[]>(() =>
  isMasterGrid.value ? unwrap(meta?.masterColumnDefs) ?? [] : unwrap(state.value.columnDefs) ?? []
);
const defaultColDef = computed<ColDef>(() =>
  isMasterGrid.value ? masterBindings.defaultColDef : unwrap(state.value.defaultColDef) || {}
);

const gridOptions = computed(() =>
  isMasterGrid.value ? masterBindings.gridOptions : unwrap(state.value.gridOptions) ?? {}
);
const rowModelType = computed(() => gridOptions.value?.rowModelType);
const dataSource = computed(() => (isMasterGrid.value ? getMasterDataSource() : unwrap(state.value.dataSource)));
const rowData = computed(() => {
  if (rowModelType.value === 'serverSide') return undefined;
  return unwrap(state.value.rowData) ?? [];
});
const rowSelection = computed(() => (isMasterGrid.value ? masterBindings.rowSelection : unwrap(state.value.rowSelection)));
const autoSizeStrategy = computed(() =>
  isMasterGrid.value ? masterBindings.autoSizeStrategy : unwrap(state.value.autoSizeStrategy)
);
const getRowId = computed(() => (isMasterGrid.value ? masterBindings.getRowId : unwrap(state.value.getRowId)));
const getRowClass = computed(() =>
  isMasterGrid.value ? masterBindings.getRowClass : unwrap(state.value.getRowClass)
);
const getRowStyle = computed(() =>
  isMasterGrid.value ? masterBindings.getRowStyle : unwrap(state.value.getRowStyle)
);
const getContextMenuItems = computed(() =>
  isMasterGrid.value
    ? contextMenuEnabled.value
      ? masterBindings.getContextMenuItems
      : undefined
    : unwrap(state.value.getContextMenuItems)
);
const rowHeight = computed(() => (isMasterGrid.value ? masterBindings.rowHeight : unwrap(state.value.rowHeight)));
const headerHeight = computed(() =>
  isMasterGrid.value ? masterBindings.headerHeight : unwrap(state.value.headerHeight)
);

function handleGridReady(params: GridReadyEvent) {
  if (isMasterGrid.value) {
    masterBindings.onGridReady(params);
    return;
  }
  state.value.onGridReady?.(params);
  const ds = dataSource.value;
  if (rowModelType.value === 'serverSide' && ds) {
    params.api.setGridOption('serverSideDatasource', ds);
  }
}

function handleCellValueChanged(event: any) {
  if (isMasterGrid.value) {
    void masterBindings.onCellValueChanged(event);
    return;
  }
  state.value.onCellValueChanged?.(event);
}

function handleCellClicked(event: any) {
  if (isMasterGrid.value) {
    masterBindings.onCellClicked(event);
    return;
  }
  state.value.onCellClicked?.(event);
}

function handleCellEditingStarted(event: any) {
  if (isMasterGrid.value) {
    masterBindings.onCellEditingStarted(event);
    return;
  }
  state.value.onCellEditingStarted?.(event);
}

function handleCellEditingStopped(event: any) {
  if (isMasterGrid.value) {
    masterBindings.onCellEditingStopped(event);
    return;
  }
  state.value.onCellEditingStopped?.(event);
}

function handleFilterChanged() {
  if (isMasterGrid.value) {
    masterBindings.onFilterChanged();
    return;
  }
  state.value.onFilterChanged?.();
}

</script>

<template>
  <div class="meta-grid" :class="gridClass" :style="containerStyle">
    <!-- 工具栏 -->
    <div v-if="isMasterGrid" class="toolbar-container">
      <NSpace>
        <NButton v-if="canAddRow" type="primary" size="small" @click="runtime?.mutations?.addMasterRow?.()">新增</NButton>
        <NButton v-if="canDeleteRow" type="error" size="small" @click="deleteSelectedMasterRows">删除</NButton>
        <NButton v-if="canSave" size="small" @click="save?.()">保存</NButton>
        <ApprovalActionGroup :runtime="runtime" :get-selected-row="getSelectedMasterRow" />
        <NButton
          v-for="item in toolbarItems"
          :key="item.action"
          :type="toNaiveButtonType(item.buttonType)"
          :disabled="item.disabled"
          size="small"
          @click="handleToolbarClick(item)"
        >
          {{ item.label }}
        </NButton>
      </NSpace>
    </div>

    <div v-if="status === 'loading'" class="meta-grid-placeholder">
      <span>加载中...</span>
    </div>
    <div v-else-if="status === 'error'" class="meta-grid-error">
      <div class="meta-grid-error-icon">⚠️</div>
      <div class="meta-grid-error-message">{{ errorMessage }}</div>
    </div>
    <AgGridVue
      v-else
      class="ag-theme-quartz grid-content"
      :row-data="rowData"
      :column-defs="columnDefs"
      :default-col-def="defaultColDef"
      :get-row-id="getRowId"
      :get-row-class="getRowClass"
      :get-row-style="getRowStyle"
      :row-selection="rowSelection"
      :auto-size-strategy="autoSizeStrategy"
      :get-context-menu-items="getContextMenuItems"
      :context="{ rowStateApi }"
      :row-height="rowHeight"
      :header-height="headerHeight"
      v-bind="gridOptions"
      @grid-ready="handleGridReady"
      @cell-value-changed="handleCellValueChanged"
      @cell-clicked="handleCellClicked"
      @cell-editing-started="handleCellEditingStarted"
      @cell-editing-stopped="handleCellEditingStopped"
      @filter-changed="handleFilterChanged"
    />
  </div>
</template>

<style scoped>
.meta-grid {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.toolbar-container {
  padding: 4px 0;
  flex-shrink: 0;
}

.grid-content {
  flex: 1;
  min-height: 0;
  width: 100%;
}

.meta-grid-placeholder,
.meta-grid-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: #666;
  background: #fafafa;
  border: 1px dashed #ddd;
  border-radius: 4px;
}

.meta-grid-error {
  color: #d03050;
  background: #fff2f0;
  border-color: #ffccc7;
}

.meta-grid-error-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.meta-grid-error-message {
  font-size: 14px;
}
</style>
