<script setup lang="ts">
/** 部门管理（旧系统 `dept-manage`）：新增、删除先记在表格里，点"保存"一起提交。行为都在 departments.ts */
import { computed, onMounted, ref, shallowRef } from 'vue';
import { NButton, NSpace } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type {
  ColDef,
  GetRowIdParams,
  GridApi,
  GridReadyEvent,
  RowClassParams,
  RowSelectionOptions,
  ValueSetterParams
} from 'ag-grid-community';
import { type DepartmentRow, DepartmentsModel } from '../departments';
import type { AdminDeps } from '../shared';

defineOptions({ name: 'DepartmentsPanel' });

const props = defineProps<{ deps: AdminDeps }>();

const model = new DepartmentsModel(props.deps);
const state = model.state;
const api = shallowRef<GridApi<DepartmentRow> | null>(null);
const selectedIds = ref<string[]>([]);

const dirtyCount = computed(() => model.dirtyCount);
const rowData = computed(() => state.rows.map(row => ({ ...row })));

const columnDefs: ColDef<DepartmentRow>[] = [
  { colId: 'departmentId', headerName: 'ID', field: 'departmentId', width: 110 },
  {
    colId: 'name',
    headerName: '部门名称',
    field: 'name',
    flex: 1,
    minWidth: 200,
    editable: true,
    valueSetter: (params: ValueSetterParams<DepartmentRow>) => {
      model.edit(params.data.id, params.newValue === null || params.newValue === undefined ? '' : String(params.newValue));
      return false;
    }
  }
];

const rowSelection: RowSelectionOptions = { mode: 'multiRow', checkboxes: false, enableClickSelection: true };

const rowClassRules = {
  'admin-row-new': (params: RowClassParams<DepartmentRow>) => Boolean(params.data?.isNew),
  'admin-row-changed': (params: RowClassParams<DepartmentRow>) => Boolean(params.data?.changed)
};

function getRowId(params: GetRowIdParams<DepartmentRow>) {
  return params.data.id;
}

function onGridReady(event: GridReadyEvent<DepartmentRow>) {
  api.value = event.api;
}

function onSelectionChanged() {
  selectedIds.value = (api.value?.getSelectedRows() ?? []).map(row => row.id);
}

function addRow() {
  const id = model.addRow();
  setTimeout(() => {
    const node = api.value?.getRowNode(id);
    if (!node) return;
    node.setSelected(true, true);
    api.value?.startEditingCell({ rowIndex: node.rowIndex ?? 0, colKey: 'name' });
  }, 0);
}

function remove() {
  model.remove(selectedIds.value);
  selectedIds.value = [];
}

async function save() {
  api.value?.stopEditing();
  await model.save();
}

onMounted(() => {
  void model.load();
});
</script>

<template>
  <div class="admin-panel h-full flex-col">
    <div class="admin-panel__toolbar flex-y-center gap-8px">
      <NSpace size="small">
        <NButton size="small" type="primary" :disabled="state.saving" @click="addRow">新增</NButton>
        <NButton size="small" type="error" :disabled="selectedIds.length === 0 || state.saving" @click="remove">
          删除
        </NButton>
        <NButton size="small" :disabled="dirtyCount === 0" :loading="state.saving" @click="save">保存</NButton>
      </NSpace>
      <span v-if="state.deleted.length" class="text-12px text-#999">待删除 {{ state.deleted.length }} 个部门</span>
      <span v-if="dirtyCount > 0" class="text-12px text-#999">{{ dirtyCount }} 处未保存</span>
      <span v-if="state.error" class="text-12px text-error">{{ state.error }}</span>
    </div>
    <div class="min-h-0 flex-1">
      <AgGridVue
        class="h-full"
        :row-data="rowData"
        :column-defs="columnDefs"
        :get-row-id="getRowId"
        :row-selection="rowSelection"
        :row-class-rules="rowClassRules"
        :loading="state.loading"
        :stop-editing-when-cells-lose-focus="true"
        :undo-redo-cell-editing="false"
        @grid-ready="onGridReady"
        @selection-changed="onSelectionChanged"
      />
    </div>
  </div>
</template>

<style scoped>
.admin-panel__toolbar {
  padding: 4px 0 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

:deep(.admin-row-new) {
  font-style: italic;
  background-color: #eef4ff;
}

:deep(.admin-row-changed) {
  background-color: #e8f8e6;
}
</style>
