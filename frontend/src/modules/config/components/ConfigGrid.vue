<script setup lang="ts">
/**
 * 配置用的可编辑表格，同旧系统 ApprovalConfigGrid.vue：单选或多选（复选框），双击单元格发出 edit，改值发出 change。
 * `problemOf` 给出某行某列的校验错误时，该格标红并在悬停时显示错误（FC-02、FC-05 的错误定位）。
 */
import { computed, shallowRef } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type {
  CellClassParams,
  CellDoubleClickedEvent,
  CellValueChangedEvent,
  ColDef,
  GetRowIdParams,
  GridApi,
  GridReadyEvent,
  RowSelectionOptions,
  SelectionChangedEvent
} from 'ag-grid-community';
import { configGridTheme } from './grid-columns';

defineOptions({ name: 'ConfigGrid' });

const props = withDefaults(
  defineProps<{
    rows: object[];
    columns: ColDef[];
    height?: number;
    multiple?: boolean;
    loading?: boolean;
    disabled?: boolean;
    rowKey?: string;
    problemOf?: (row: any, column: string) => string | null;
    rowStyle?: (params: any) => Record<string, string> | undefined;
  }>(),
  { height: 260, multiple: false, loading: false, disabled: false, rowKey: undefined, problemOf: undefined, rowStyle: undefined }
);

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

const locale = { noRowsToShow: '暂无配置', loadingOoo: '正在读取配置…' };

/** 每列加上错误标记：cellClassRules + tooltip 显示错误文字 */
const columnDefs = computed<ColDef[]>(() =>
  props.columns.map(column => {
    const id = column.colId ?? column.field ?? '';
    if (!props.problemOf) return column;
    const check = props.problemOf;
    return {
      ...column,
      cellClassRules: { ...(column.cellClassRules as object), 'config-cell-error': (p: CellClassParams) => Boolean(p.data && check(p.data, id)) },
      tooltipValueGetter: (p: any) =>
        (p.data && check(p.data, id)) ||
        (column.tooltipValueGetter ? column.tooltipValueGetter(p) : column.tooltipField ? p.data?.[column.tooltipField] : undefined)
    } as ColDef;
  })
);

const rowSelection = computed<RowSelectionOptions>(() =>
  props.multiple
    ? { mode: 'multiRow', checkboxes: true, headerCheckbox: true, enableClickSelection: true }
    : { mode: 'singleRow', checkboxes: false, enableClickSelection: true }
);

function getRowId(params: GetRowIdParams) {
  return String((params.data as Record<string, unknown>)[props.rowKey!] ?? '');
}

function ready(event: GridReadyEvent) {
  api.value = event.api;
}

function select(event: SelectionChangedEvent) {
  emit('select', event.api.getSelectedRows());
}

function selectRow(row: object | undefined) {
  api.value?.forEachNode(node => node.setSelected(node.data === row));
}

defineExpose({
  stopEditing: () => api.value?.stopEditing(),
  refresh: () => api.value?.refreshCells({ force: true }),
  selectRow
});
</script>

<template>
  <AgGridVue
    class="config-grid"
    :theme="configGridTheme"
    :style="{ height: `${height}px` }"
    :row-data="rows"
    :column-defs="columnDefs"
    :default-col-def="defaultColumn"
    :get-row-id="rowKey ? getRowId : undefined"
    :get-row-style="rowStyle"
    :locale-text="locale"
    :loading="loading"
    :read-only-edit="disabled"
    :suppress-click-edit="disabled"
    :suppress-context-menu="true"
    :row-selection="rowSelection"
    :selection-column-def="{ width: 36, minWidth: 36, maxWidth: 36, suppressHeaderContextMenu: true }"
    :stop-editing-when-cells-lose-focus="true"
    :animate-rows="false"
    :tooltip-show-delay="300"
    @grid-ready="ready"
    @selection-changed="select"
    @cell-value-changed="emit('change', $event)"
    @cell-double-clicked="emit('edit', $event)"
  />
</template>

<style scoped>
.config-grid {
  width: 100%;
}
.config-grid :deep(.config-link) {
  color: #2080f0;
  cursor: pointer;
}
.config-grid :deep(.config-cell-error) {
  background: #fff1f0;
  box-shadow: inset 0 0 0 1px #d03050;
}
</style>
