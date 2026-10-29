<script setup lang="ts">
/** grid-adapter：Lookup 对话框中的结果表格（客户端行模型）；单选时双击即选定，多选时带复选框（与旧系统 LookupDialog.vue 相同） */
import { computed, shallowRef } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, GridApi, GridReadyEvent, RowDoubleClickedEvent, RowSelectionOptions } from 'ag-grid-community';
import type { FieldValues } from '../../../contracts/command';

defineOptions({ name: 'LookupGrid' });

const props = defineProps<{ rows: FieldValues[]; multiple: boolean }>();
const emit = defineEmits<{ (e: 'selection', rows: FieldValues[]): void; (e: 'pick', row: FieldValues): void }>();

const api = shallowRef<GridApi<FieldValues> | null>(null);

/** 列取自 Lookup 返回的值（C09 第 4 节的 rows[].values） */
const columnDefs = computed<ColDef<FieldValues>[]>(() => {
  const names = [...new Set(props.rows.flatMap(row => Object.keys(row)))];
  return names.map(name => ({
    field: name,
    headerName: name,
    flex: 1,
    minWidth: 120,
    sortable: true,
    resizable: true
  }));
});

const rowSelection = computed<RowSelectionOptions>(() =>
  props.multiple
    ? { mode: 'multiRow', checkboxes: true, headerCheckbox: true, enableClickSelection: true }
    : { mode: 'singleRow', checkboxes: false, enableClickSelection: true }
);

function onGridReady(event: GridReadyEvent<FieldValues>) {
  api.value = event.api;
}

function onSelectionChanged() {
  emit('selection', api.value?.getSelectedRows() ?? []);
}

function onRowDoubleClicked(event: RowDoubleClickedEvent<FieldValues>) {
  if (!props.multiple && event.data) emit('pick', event.data);
}
</script>

<template>
  <AgGridVue
    class="h-full w-full"
    :row-data="rows"
    :column-defs="columnDefs"
    :row-selection="rowSelection"
    @grid-ready="onGridReady"
    @selection-changed="onSelectionChanged"
    @row-double-clicked="onRowDoubleClicked"
  />
</template>
