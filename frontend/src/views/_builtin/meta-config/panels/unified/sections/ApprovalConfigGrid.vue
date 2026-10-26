<script setup lang="ts">
import { shallowRef } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { CellDoubleClickedEvent, CellValueChangedEvent, ColDef, GridApi, GridReadyEvent, SelectionChangedEvent } from 'ag-grid-community';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';

withDefaults(defineProps<{
  rows: object[];
  columns: ColDef[];
  height?: number;
  multiple?: boolean;
  loading?: boolean;
  disabled?: boolean;
}>(), { height: 260, multiple: false, loading: false, disabled: false });

const emit = defineEmits<{
  change: [event: CellValueChangedEvent];
  select: [rows: any[]];
  edit: [event: CellDoubleClickedEvent];
}>();
const api = shallowRef<GridApi>();
const defaultColumn: ColDef = {
  editable: true,
  resizable: true,
  minWidth: 65,
  sortable: false,
  filter: false,
  suppressHeaderMenuButton: true,
  suppressHeaderFilterButton: true,
  suppressHeaderContextMenu: true
};
const locale = {
  noRowsToShow: '暂无配置', loadingOoo: '正在读取配置…', filterOoo: '筛选…', contains: '包含',
  notContains: '不包含', equals: '等于', notEqual: '不等于', startsWith: '开头是', endsWith: '结尾是',
  blank: '为空', notBlank: '不为空', andCondition: '且', orCondition: '或', selectAll: '全选'
};
function ready(event: GridReadyEvent) { api.value = event.api; }
function select(event: SelectionChangedEvent) { emit('select', event.api.getSelectedRows()); }
function selectRow(row: object) { api.value?.forEachNode(node => node.setSelected(node.data === row)); }
defineExpose({
  stopEditing: () => api.value?.stopEditing(),
  refresh: () => api.value?.refreshCells({ force: true }),
  selectRow
});
</script>

<template>
  <AgGridVue
    class="ag-theme-quartz approval-config-grid"
    theme="legacy"
    :style="{ height: `${height}px` }"
    :row-data="rows"
    :column-defs="columns"
    :default-col-def="defaultColumn"
    :row-height="28"
    :header-height="28"
    :locale-text="locale"
    :loading="loading"
    :read-only-edit="disabled"
    :suppress-click-edit="disabled"
    :suppress-context-menu="true"
    :row-selection="multiple ? { mode: 'multiRow', checkboxes: true, headerCheckbox: true, enableClickSelection: true } : { mode: 'singleRow', checkboxes: false, enableClickSelection: true }"
    :selection-column-def="{ width: 36, minWidth: 36, maxWidth: 36, suppressHeaderContextMenu: true }"
    :stop-editing-when-cells-lose-focus="true"
    :animate-rows="false"
    @grid-ready="ready"
    @selection-changed="select"
    @cell-value-changed="emit('change', $event)"
    @cell-double-clicked="emit('edit', $event)"
  />
</template>

<style scoped>
.approval-config-grid {
  width: 100%;
  --ag-font-size: 13px;
  --ag-font-family: inherit;
  --ag-row-height: 28px;
  --ag-header-height: 28px;
  --ag-cell-horizontal-padding: 9px;
  --ag-wrapper-border-radius: 0;
  --ag-header-background-color: #f5f7fa;
  --ag-border-color: #dce2e9;
}
.approval-config-grid :deep(.approval-link) { color: #2080f0; cursor: pointer; }
/* The modern theme adds a mask background globally; this legacy grid uses font glyphs. */
.approval-config-grid :deep(.ag-icon::before) { background-color: transparent; }
</style>
