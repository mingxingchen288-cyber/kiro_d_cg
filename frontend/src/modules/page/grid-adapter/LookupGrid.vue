<script setup lang="ts">
/**
 * grid-adapter：Lookup 对话框中的结果表格（客户端行模型）；单选时双击即选定，多选时带复选框（与旧系统 LookupDialog.vue 相同）。
 * 列标题和宽度按 Lookup 配置的显示列（lookup-columns.ts）。
 * 列数随 Lookup 返回的值，测试模式下同主表一样关掉列虚拟化（columns.ts 的 suppressColumnVirtualisation），正式模式不变。
 */
import { computed, shallowRef } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, GridApi, GridReadyEvent, RowDoubleClickedEvent, RowSelectionOptions } from 'ag-grid-community';
import type { FieldValues } from '../../../contracts/command';
import type { LookupColumn } from '../../../contracts/page-view';
import { suppressColumnVirtualisation } from './columns';
import { lookupColumnDefs } from './lookup-columns';

defineOptions({ name: 'LookupGrid' });

const props = withDefaults(defineProps<{ rows: FieldValues[]; multiple: boolean; columns?: LookupColumn[] }>(), {
  columns: () => []
});
const emit = defineEmits<{ (e: 'selection', rows: FieldValues[]): void; (e: 'pick', row: FieldValues): void }>();

const api = shallowRef<GridApi<FieldValues> | null>(null);

/** 列取自 Lookup 配置的显示列（C05 `lookup.columns`，标题和宽度）；没有时取返回值中的列名（C09 第 4 节的 rows[].values） */
const columnDefs = computed<ColDef<FieldValues>[]>(() => lookupColumnDefs(props.columns, props.rows));

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
    :suppress-column-virtualisation="suppressColumnVirtualisation"
    @grid-ready="onGridReady"
    @selection-changed="onSelectionChanged"
    @row-double-clicked="onRowDoubleClicked"
  />
</template>
