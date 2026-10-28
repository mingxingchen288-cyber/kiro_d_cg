<script setup lang="ts">
/**
 * 成本核算（链路 0、1）：主表列表（无限行模型）；选中主表的一行后，在下方页签中显示这张单据的明细（客户端行模型）；
 * 单元格编辑、保存和局部刷新。列来自页面视图（C05），行来自列表和单据加载接口（C09 第 4 节），保存提交命令（C02），
 * 用命令结果中的行更新表格中的行：主表用 setData，明细用 applyTransaction（FP-06）。
 */
import { computed, onMounted, ref, shallowRef } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type {
  CellValueChangedEvent,
  ColDef,
  GetRowIdParams,
  GridApi,
  GridReadyEvent,
  IDatasource,
  RowSelectionOptions,
  SelectionChangedEvent
} from 'ag-grid-community';
import {
  type CommandResult,
  type FieldValue,
  type PageView,
  type ViewDetail,
  type ViewField,
  listRows,
  loadRecord,
  pageView,
  runCommand
} from '@/service/platform';
import { EditBuffer } from './edit-buffer';

defineOptions({ name: 'CostPinggu' });

const PAGE_CODE = 'COST_PINGGU';
const ROW_KEY = '__rowKey';

type GridRow = Record<string, FieldValue>;

const view = shallowRef<PageView | null>(null);
const masterApi = shallowRef<GridApi<GridRow> | null>(null);
const detailApis = new Map<string, GridApi<GridRow>>();
let buffer = new EditBuffer('');
/** 编辑缓冲中有修改的行数（编辑缓冲本身不是响应式的，改动后更新这个计数） */
const pendingCount = ref(0);
const saving = ref(false);
const loadError = ref('');
/** 选中的主表行（单据）；明细区显示它的明细 */
const recordKey = ref<string | null>(null);
const activeDetail = ref('');
/** 当前单据各明细实体的行，绑定到明细表格 */
const detailData = shallowRef<Record<string, GridRow[]>>({});
let loadToken = 0;

function toGridRow(entity: string, row: { rowKey: string; values: Record<string, FieldValue> }): GridRow {
  return { ...buffer.overlay(entity, row.rowKey, row.values), [ROW_KEY]: row.rowKey };
}

function columnsOf(entity: string, fields: ViewField[]): ColDef<GridRow>[] {
  return fields
    .filter(f => f.visible)
    .map(f => {
      const column: ColDef<GridRow> = {
        field: f.name,
        headerName: f.label,
        editable: f.editable,
        pinned: f.pinned ?? undefined,
        width: f.width ?? undefined,
        cellClassRules: {
          'cell-changed': p => Boolean(p.data && buffer.isChanged(entity, String(p.data[ROW_KEY]), f.name))
        }
      };
      if (f.type === 'boolean') {
        // 复选框：勾选即修改（C01：JSON 中为 true/false）
        return { ...column, cellDataType: 'boolean' };
      }
      return {
        ...column,
        type: f.type === 'number' ? 'rightAligned' : undefined,
        // 编辑框给出的空文本按空值提交
        valueParser: p => (p.newValue === '' ? null : p.newValue)
      };
    });
}

const masterColumns = computed(() => (view.value ? columnsOf(view.value.master.entity, view.value.master.fields) : []));
const detailColumns = computed<Record<string, ColDef<GridRow>[]>>(() =>
  Object.fromEntries((view.value?.details ?? []).map(d => [d.entity, columnsOf(d.entity, d.fields)]))
);

const datasource: IDatasource = {
  getRows(params) {
    const sortModel = params.sortModel.map(s => ({ colId: s.colId, sort: s.sort }));
    listRows(PAGE_CODE, { startRow: params.startRow, endRow: params.endRow, sortModel })
      .then(result => {
        const entity = view.value?.master.entity ?? '';
        params.successCallback(
          result.rows.map(r => toGridRow(entity, r)),
          result.total
        );
      })
      .catch((error: Error) => {
        loadError.value = error.message;
        params.failCallback();
      });
  }
};

const rowSelection: RowSelectionOptions = { mode: 'singleRow', checkboxes: false, enableClickSelection: true };

function getRowId(params: GetRowIdParams<GridRow>) {
  return String(params.data[ROW_KEY]);
}

function onMasterReady(event: GridReadyEvent<GridRow>) {
  masterApi.value = event.api;
}

function onDetailReady(entity: string, event: GridReadyEvent<GridRow>) {
  detailApis.set(entity, event.api);
}

async function openRecord(key: string) {
  const current = view.value;
  if (!current?.details.length) return;
  recordKey.value = key;
  loadToken += 1;
  const token = loadToken;
  try {
    const record = await loadRecord(PAGE_CODE, key);
    if (token !== loadToken) return; // 期间又选了别的单据
    detailData.value = Object.fromEntries(
      current.details.map(d => [d.entity, (record.details[d.entity] ?? []).map(r => toGridRow(d.entity, r))])
    );
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error);
  }
}

function onSelectionChanged(event: SelectionChangedEvent<GridRow>) {
  const row = event.api.getSelectedRows()[0];
  if (row) openRecord(String(row[ROW_KEY]));
}

function bufferChange(entity: string, recordOf: string, event: CellValueChangedEvent<GridRow>) {
  if (event.oldValue === event.newValue || !event.colDef.field) return;
  buffer.set(
    { entity, rowKey: String(event.data[ROW_KEY]), recordKey: recordOf },
    event.colDef.field,
    event.newValue ?? null
  );
  pendingCount.value = buffer.size;
  event.api.refreshCells({ rowNodes: [event.node], force: true });
}

function onMasterChanged(event: CellValueChangedEvent<GridRow>) {
  bufferChange(view.value?.master.entity ?? '', String(event.data[ROW_KEY]), event);
}

function onDetailChanged(detail: ViewDetail, event: CellValueChangedEvent<GridRow>) {
  bufferChange(detail.entity, String(event.data[detail.parentKey]), event);
}

/** 用命令结果中的行替换表格中的行 */
function applyResult(result: CommandResult) {
  const masterEntity = view.value?.master.entity;
  for (const row of result.rows) {
    const gridRow = toGridRow(row.entity, row);
    const rows = detailData.value[row.entity] ?? [];
    const index = rows.findIndex(r => r[ROW_KEY] === row.rowKey);
    if (row.entity === masterEntity) {
      masterApi.value?.getRowNode(row.rowKey)?.setData(gridRow);
    } else if (index >= 0) {
      // 明细只更新当前显示的单据中的行；其他单据的明细下次打开时重新读取
      rows[index] = gridRow;
      detailApis.get(row.entity)?.applyTransaction({ update: [gridRow] });
    }
  }
  masterApi.value?.refreshCells({ force: true });
  for (const api of detailApis.values()) api.refreshCells({ force: true });
}

const canSave = computed(() => Boolean(view.value?.systemButtons.includes('save')));

async function save() {
  const current = view.value;
  masterApi.value?.stopEditing();
  for (const api of detailApis.values()) api.stopEditing();
  if (!current || buffer.size === 0) return;
  saving.value = true;
  try {
    const result = await runCommand({
      requestKey: crypto.randomUUID(),
      page: PAGE_CODE,
      operation: current.saveOperation,
      documents: buffer.documents(),
      params: {}
    });
    buffer.clear();
    pendingCount.value = 0;
    applyResult(result);
    window.$message?.success(result.outcome === 'saved' ? '已保存' : '没有需要保存的修改');
  } catch (error) {
    window.$message?.error(error instanceof Error ? error.message : String(error));
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try {
    const loaded = await pageView(PAGE_CODE);
    buffer = new EditBuffer(loaded.master.entity);
    activeDetail.value = loaded.details[0]?.entity ?? '';
    view.value = loaded;
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error);
  }
});
</script>

<template>
  <div class="h-full flex-col gap-12px">
    <div class="flex-y-center gap-12px">
      <span class="text-16px font-medium">{{ view?.title ?? '成本核算' }}</span>
      <NButton v-if="canSave" type="primary" :disabled="pendingCount === 0" :loading="saving" @click="save">
        保存
      </NButton>
      <span v-if="pendingCount > 0" class="text-12px text-#999">{{ pendingCount }} 行未保存</span>
      <span v-if="loadError" class="text-12px text-error">{{ loadError }}</span>
    </div>
    <div v-if="view" data-testid="master-grid" class="master-area min-h-0">
      <AgGridVue
        class="h-full"
        :column-defs="masterColumns"
        :default-col-def="{ sortable: true, resizable: true, minWidth: 90 }"
        row-model-type="infinite"
        :datasource="datasource"
        :cache-block-size="100"
        :get-row-id="getRowId"
        :row-selection="rowSelection"
        :stop-editing-when-cells-lose-focus="true"
        @grid-ready="onMasterReady"
        @selection-changed="onSelectionChanged"
        @cell-value-changed="onMasterChanged"
      />
    </div>
    <div v-if="view && view.details.length > 0" class="detail-area min-h-0 flex-col">
      <NTabs v-model:value="activeDetail" type="line" size="small">
        <NTab v-for="d in view.details" :key="d.entity" :name="d.entity" :tab="d.title" />
      </NTabs>
      <template v-if="recordKey">
        <div
          v-for="d in view.details"
          v-show="d.entity === activeDetail"
          :key="d.entity"
          :data-testid="`detail-${d.entity}`"
          class="min-h-0 flex-1"
        >
          <AgGridVue
            class="h-full"
            :column-defs="detailColumns[d.entity]"
            :default-col-def="{ sortable: true, resizable: true, minWidth: 90 }"
            :row-data="detailData[d.entity] ?? []"
            :get-row-id="getRowId"
            :stop-editing-when-cells-lose-focus="true"
            @grid-ready="(e: GridReadyEvent<GridRow>) => onDetailReady(d.entity, e)"
            @cell-value-changed="(e: CellValueChangedEvent<GridRow>) => onDetailChanged(d, e)"
          />
        </div>
      </template>
      <div v-else class="flex-center flex-1 text-12px text-#999">选中主表的一行后显示这张单据的明细</div>
    </div>
  </div>
</template>

<style scoped>
.master-area {
  flex: 3 1 0;
}

.detail-area {
  flex: 2 1 0;
}

:deep(.cell-changed) {
  background-color: #fff7e6;
}
</style>
