<script setup lang="ts">
/**
 * 成本核算（链路 0）：主表列表、单元格编辑、保存和局部刷新。
 * 列来自页面视图（C05），行来自列表接口（C09 第 4 节），保存提交命令（C02），用命令结果中的行替换表格中的行。
 */
import { computed, onMounted, reactive, ref, shallowRef } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type {
  CellValueChangedEvent,
  ColDef,
  GetRowIdParams,
  GridApi,
  GridReadyEvent,
  IDatasource
} from 'ag-grid-community';
import { type DataRow, type FieldValue, type PageView, listRows, pageView, runCommand } from '@/service/platform';

defineOptions({ name: 'CostPinggu' });

const PAGE_CODE = 'COST_PINGGU';
const ROW_KEY = '__rowKey';

type GridRow = Record<string, FieldValue>;

const view = shallowRef<PageView | null>(null);
const api = shallowRef<GridApi<GridRow> | null>(null);
/** 未保存的修改：行主键 → 字段 → 新值 */
const pending = reactive(new Map<string, Record<string, FieldValue>>());
const saving = ref(false);
const loadError = ref('');

function toGridRow(row: { rowKey: string; values: Record<string, FieldValue> }): GridRow {
  return { ...row.values, [ROW_KEY]: row.rowKey };
}

function isChanged(data: GridRow | undefined, field: string) {
  return Boolean(data && pending.get(String(data[ROW_KEY]))?.[field] !== undefined);
}

const columnDefs = computed<ColDef<GridRow>[]>(() =>
  (view.value?.master.fields ?? [])
    .filter(f => f.visible)
    .map(f => ({
      field: f.name,
      headerName: f.label,
      editable: f.editable,
      pinned: f.pinned ?? undefined,
      width: f.width ?? undefined,
      type: f.type === 'number' ? 'rightAligned' : undefined,
      // 编辑框给出的空文本按空值提交
      valueParser: p => (p.newValue === '' ? null : p.newValue),
      cellClassRules: { 'cell-changed': p => isChanged(p.data, f.name) }
    }))
);

const datasource: IDatasource = {
  getRows(params) {
    const sortModel = params.sortModel.map(s => ({ colId: s.colId, sort: s.sort }));
    listRows(PAGE_CODE, { startRow: params.startRow, endRow: params.endRow, sortModel })
      .then(result => params.successCallback(result.rows.map(toGridRow), result.total))
      .catch((error: Error) => {
        loadError.value = error.message;
        params.failCallback();
      });
  }
};

function getRowId(params: GetRowIdParams<GridRow>) {
  return String(params.data[ROW_KEY]);
}

function onGridReady(event: GridReadyEvent<GridRow>) {
  api.value = event.api;
}

function onCellValueChanged(event: CellValueChangedEvent<GridRow>) {
  if (event.oldValue === event.newValue || !event.colDef.field) return;
  const rowKey = String(event.data[ROW_KEY]);
  pending.set(rowKey, { ...pending.get(rowKey), [event.colDef.field]: event.newValue ?? null });
  event.api.refreshCells({ rowNodes: [event.node], force: true });
}

const canSave = computed(() => Boolean(view.value?.systemButtons.includes('save')));

async function save() {
  const current = view.value;
  api.value?.stopEditing();
  if (!current || pending.size === 0) return;
  saving.value = true;
  try {
    const result = await runCommand({
      requestKey: crypto.randomUUID(),
      page: PAGE_CODE,
      operation: current.saveOperation,
      documents: [...pending.entries()].map(([rowKey, changes]) => ({
        entity: current.master.entity,
        master: { op: 'modify', rowKey, changes },
        details: []
      })),
      params: {}
    });
    pending.clear();
    for (const row of result.rows) {
      api.value?.getRowNode(row.rowKey)?.setData(toGridRow(row as DataRow));
    }
    api.value?.refreshCells({ force: true });
    window.$message?.success(result.outcome === 'saved' ? '已保存' : '没有需要保存的修改');
  } catch (error) {
    window.$message?.error(error instanceof Error ? error.message : String(error));
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try {
    view.value = await pageView(PAGE_CODE);
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error);
  }
});
</script>

<template>
  <div class="h-full flex-col gap-12px">
    <div class="flex-y-center gap-12px">
      <span class="text-16px font-medium">{{ view?.title ?? '成本核算' }}</span>
      <NButton v-if="canSave" type="primary" :disabled="pending.size === 0" :loading="saving" @click="save">
        保存
      </NButton>
      <span v-if="pending.size > 0" class="text-12px text-#999">{{ pending.size }} 行未保存</span>
      <span v-if="loadError" class="text-12px text-error">{{ loadError }}</span>
    </div>
    <AgGridVue
      v-if="view"
      class="min-h-0 flex-1"
      :column-defs="columnDefs"
      :default-col-def="{ sortable: true, resizable: true, minWidth: 90 }"
      row-model-type="infinite"
      :datasource="datasource"
      :cache-block-size="100"
      :get-row-id="getRowId"
      :stop-editing-when-cells-lose-focus="true"
      @grid-ready="onGridReady"
      @cell-value-changed="onCellValueChanged"
    />
  </div>
</template>

<style scoped>
:deep(.cell-changed) {
  background-color: #fff7e6;
}
</style>
