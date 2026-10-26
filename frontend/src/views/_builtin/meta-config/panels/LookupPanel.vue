<script setup lang="ts">
import { computed, h, inject, onMounted, ref, watch } from 'vue';
import type { Ref } from 'vue';
import {
  NButton,
  NCheckbox,
  NDataTable,
  NEmpty,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSpace,
  useMessage
} from 'naive-ui';
import type { DataTableColumns } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type { CellClickedEvent, CellValueChangedEvent, ColDef, GridApi, GridReadyEvent } from 'ag-grid-community';
import {
  deleteLookupConfig,
  fetchAllLookupConfigs,
  fetchLookupCodesByPageCode,
  fetchViewColumns,
  saveLookupConfig
} from '@/service/api/meta-config';

type DisplayColumnConfig = {
  field: string;
  header: string;
  width?: number;
};

type DisplayColumnDraft = {
  field: string;
  header: string;
  width: number | null;
  checked: boolean;
  missing: boolean;
};

const message = useMessage();
const filterState = inject<Ref<{ tab: string; pageCode: string } | null>>('filterState');
const gridApi = ref<GridApi | null>(null);
const rowData = ref<any[]>([]);
const selectedRow = ref<any>(null);
const showDisplayColumnModal = ref(false);
const loadingDisplayColumns = ref(false);
const savingDisplayColumns = ref(false);
const editingLookupRow = ref<any>(null);
const displayColumnDrafts = ref<DisplayColumnDraft[]>([]);
const LOOKUP_AUDIT_FIELD_KEYS = new Set(['CREATEBY', 'CREATETIME', 'UPDATEBY', 'UPDATETIME', 'DELETED']);

function normalizeColumnName(value: unknown): string {
  return typeof value === 'string' ? value.trim().toUpperCase() : '';
}

function normalizeAuditFieldKey(value: unknown): string {
  return typeof value === 'string'
    ? value
        .trim()
        .toUpperCase()
        .replace(/[^A-Z0-9]/g, '')
    : '';
}

function isAuditField(value: unknown): boolean {
  return LOOKUP_AUDIT_FIELD_KEYS.has(normalizeAuditFieldKey(value));
}

function numberValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function parseDisplayColumns(raw: unknown): DisplayColumnConfig[] {
  let source: unknown[] = [];
  if (Array.isArray(raw)) {
    source = raw;
  } else if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      source = Array.isArray(parsed) ? parsed : [];
    } catch {
      source = [];
    }
  }

  return source
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map(item => {
      const field = typeof item.field === 'string' ? item.field.trim() : '';
      if (!field || isAuditField(field)) return null;
      const header = typeof item.header === 'string' && item.header.trim() ? item.header.trim() : field;
      const width = numberValue(item.width);
      return width !== null ? { field, header, width } : { field, header };
    })
    .filter((item): item is DisplayColumnConfig => Boolean(item));
}

function toCheckedDisplayColumnDrafts(columns: DisplayColumnConfig[]): DisplayColumnDraft[] {
  return columns.map(item => ({
    field: item.field,
    header: item.header,
    width: item.width ?? null,
    checked: true,
    missing: false
  }));
}

function stringifyDisplayColumns(drafts: Array<Pick<DisplayColumnDraft, 'field' | 'header' | 'width' | 'checked'>>) {
  return JSON.stringify(
    drafts
      .filter(item => item.checked)
      .map(item => {
        const result: Record<string, unknown> = {
          field: item.field,
          header: item.header.trim() || item.field
        };
        const width = numberValue(item.width);
        if (width !== null) {
          result.width = width;
        }
        return result;
      })
  );
}

function getViewColumnName(item: Record<string, any>): string {
  if (typeof item?.COLUMN_NAME === 'string') return item.COLUMN_NAME.trim();
  if (typeof item?.columnName === 'string') return item.columnName.trim();
  return '';
}

function markLookupRowDirty(row: Record<string, any> | null | undefined) {
  if (row) Reflect.set(row, '_dirty', true);
}

function isNewLookupRow(row: Record<string, any> | null | undefined): boolean {
  return Boolean(row && Reflect.get(row, '_isNew'));
}

function isLookupRowDirty(row: Record<string, any>): boolean {
  return Boolean(Reflect.get(row, '_dirty') || isNewLookupRow(row));
}

function buildDisplayColumnDrafts(
  currentColumns: DisplayColumnConfig[],
  fetchedColumns: Array<Record<string, any>>
): DisplayColumnDraft[] {
  const currentMap = new Map(currentColumns.map(item => [normalizeColumnName(item.field), item] as const));
  const seen = new Set<string>();

  const drafts = fetchedColumns
    .map(item => {
      const field = getViewColumnName(item);
      if (!field || isAuditField(field)) return null;
      const key = normalizeColumnName(field);
      seen.add(key);
      const current = currentMap.get(key);
      return {
        field,
        header: current?.header || field,
        width: current?.width ?? null,
        checked: Boolean(current),
        missing: false
      };
    })
    .filter((item): item is DisplayColumnDraft => Boolean(item));

  currentColumns.forEach(current => {
    const key = normalizeColumnName(current.field);
    if (key && !isAuditField(current.field) && !seen.has(key)) {
      drafts.push({
        field: current.field,
        header: current.header || current.field,
        width: current.width ?? null,
        checked: true,
        missing: true
      });
    }
  });

  return drafts;
}

function getDisplayColumnsSummary(raw: unknown): string {
  const columns = parseDisplayColumns(raw);
  if (!columns.length) return '点击配置显示列';
  const labels = columns.map(col => col.header || col.field);
  return `已选 ${columns.length} 列：${labels.join('、')}`;
}

const selectedDisplayColumnCount = computed(() => displayColumnDrafts.value.filter(item => item.checked).length);

const displayColumnTableData = computed(() => {
  return [...displayColumnDrafts.value].sort((a, b) => {
    if (a.checked !== b.checked) return a.checked ? -1 : 1;
    if (a.missing !== b.missing) return a.missing ? -1 : 1;
    return a.field.localeCompare(b.field);
  });
});

const displayColumnTableColumns = computed<DataTableColumns<(typeof displayColumnDrafts.value)[number]>>(() => [
  {
    key: 'checked',
    title: () =>
      h(NCheckbox, {
        checked:
          displayColumnDrafts.value.length > 0 && selectedDisplayColumnCount.value === displayColumnDrafts.value.length,
        indeterminate:
          selectedDisplayColumnCount.value > 0 && selectedDisplayColumnCount.value < displayColumnDrafts.value.length,
        'onUpdate:checked': (checked: boolean) => {
          if (checked) {
            handleDisplayColumnSelectAll();
          } else {
            handleDisplayColumnClear();
          }
        }
      }),
    width: 54,
    align: 'center',
    render: row =>
      h(NCheckbox, {
        checked: row.checked,
        'onUpdate:checked': (checked: boolean) => {
          row.checked = checked;
          if (checked && !row.header.trim()) {
            row.header = row.field;
          }
        }
      })
  },
  {
    key: 'field',
    title: '字段',
    width: 240,
    ellipsis: true,
    render: row =>
      h(
        'div',
        {
          class: 'display-column-field-cell',
          style: row.missing
            ? {
                color: '#cf1322',
                fontWeight: 600
              }
            : undefined
        },
        [h('span', { class: 'display-column-field' }, row.field)]
      )
  },
  {
    key: 'header',
    title: '显示标题',
    width: 180,
    render: row =>
      h(NInput, {
        value: row.header,
        size: 'small',
        disabled: !row.checked,
        status: row.missing ? 'error' : undefined,
        placeholder: '显示标题',
        'onUpdate:value': (value: string) => {
          row.header = value;
        }
      })
  },
  {
    key: 'width',
    title: '宽度',
    width: 160,
    render: row =>
      h(NInputNumber, {
        value: row.width,
        size: 'small',
        disabled: !row.checked,
        status: row.missing ? 'error' : undefined,
        clearable: true,
        min: 60,
        step: 10,
        placeholder: '宽度',
        'onUpdate:value': (value: number | null) => {
          row.width = value;
        }
      })
  }
]);

const columnDefs: ColDef[] = [
  { field: 'id', headerName: 'ID', width: 70, editable: false },
  { field: 'lookupCode', headerName: 'lookupCode', width: 140, editable: true },
  { field: 'lookupName', headerName: '名称', width: 140, editable: true },
  { field: 'dataSource', headerName: '数据源', width: 200, editable: true },
  {
    field: 'displayColumns',
    headerName: '显示列',
    flex: 1,
    editable: false,
    valueFormatter: params => getDisplayColumnsSummary(params.value),
    tooltipValueGetter: params => getDisplayColumnsSummary(params.value),
    cellStyle: {
      cursor: 'pointer',
      color: '#5b5bd6'
    }
  }
];

const defaultColDef: ColDef = { sortable: true, resizable: true, flex: 0, suppressHeaderMenuButton: true };

async function loadData() {
  try {
    const res = await fetchAllLookupConfigs();
    rowData.value = res || [];
    setTimeout(() => gridApi.value?.autoSizeAllColumns(), 100);
  } catch {
    message.error('加载Lookup配置失败');
  }
}

function onGridReady(params: GridReadyEvent) {
  gridApi.value = params.api;
  params.api.autoSizeAllColumns();
}

function onSelectionChanged() {
  const rows = gridApi.value?.getSelectedRows() || [];
  selectedRow.value = rows[0] || null;
}

function onRowClicked(event: any) {
  if (event.node?.data) {
    selectedRow.value = event.node.data;
    event.node.setSelected(true, true);
  }
}

async function openDisplayColumnEditor(row: any) {
  if (!row) return;
  const dataSource = typeof row.dataSource === 'string' ? row.dataSource.trim() : '';
  if (!dataSource) {
    message.warning('请先填写数据源，再配置显示列');
    return;
  }

  gridApi.value?.stopEditing();
  loadingDisplayColumns.value = true;

  try {
    const currentColumns = parseDisplayColumns(row.displayColumns);
    const fetchedColumns = await fetchViewColumns(dataSource);
    displayColumnDrafts.value = buildDisplayColumnDrafts(currentColumns, fetchedColumns);
    editingLookupRow.value = row;
    showDisplayColumnModal.value = true;
  } catch {
    message.error('加载数据源列失败');
  } finally {
    loadingDisplayColumns.value = false;
  }
}

function handleDisplayColumnSelectAll() {
  displayColumnDrafts.value.forEach(item => {
    item.checked = true;
    if (!item.header.trim()) {
      item.header = item.field;
    }
  });
}

function handleDisplayColumnClear() {
  displayColumnDrafts.value.forEach(item => {
    item.checked = false;
  });
}

function handleDisplayColumnModalClose() {
  showDisplayColumnModal.value = false;
  editingLookupRow.value = null;
  displayColumnDrafts.value = [];
}

async function sanitizeDisplayColumnsBeforeSave(rows: any[]) {
  const dataSources = [
    ...new Set(rows.map(row => (typeof row.dataSource === 'string' ? row.dataSource.trim() : '')).filter(Boolean))
  ];
  const fetchedEntries = await Promise.all(
    dataSources.map(async dataSource => [dataSource, await fetchViewColumns(dataSource)] as const)
  );
  const dataSourceCache = new Map<string, Array<Record<string, any>>>(fetchedEntries);
  let removedCount = 0;

  for (const row of rows) {
    const currentColumns = parseDisplayColumns(row.displayColumns);
    const dataSource = typeof row.dataSource === 'string' ? row.dataSource.trim() : '';

    if (!dataSource) {
      const sanitized = stringifyDisplayColumns(toCheckedDisplayColumnDrafts(currentColumns));
      if (sanitized !== (row.displayColumns || '[]')) {
        row.displayColumns = sanitized;
        markLookupRowDirty(row);
      }
    } else {
      const fetchedColumns = dataSourceCache.get(dataSource) || [];
      const drafts = buildDisplayColumnDrafts(currentColumns, fetchedColumns);
      const nextColumns = drafts.filter(item => item.checked && !item.missing);
      removedCount += drafts.filter(item => item.checked && item.missing).length;
      const sanitized = stringifyDisplayColumns(nextColumns);

      if (sanitized !== (row.displayColumns || '[]')) {
        row.displayColumns = sanitized;
        markLookupRowDirty(row);
      }
    }
  }

  return removedCount;
}

async function saveLookupRows(rows: any[]) {
  gridApi.value?.stopEditing();
  let removedInvalidColumns = 0;
  try {
    removedInvalidColumns = await sanitizeDisplayColumnsBeforeSave(rows);
  } catch {
    message.error('校验显示列失败');
    return null;
  }

  const dirtyRows = rows.filter((r: any) => isLookupRowDirty(r));
  if (dirtyRows.length === 0) {
    return {
      savedCount: 0,
      removedInvalidColumns
    };
  }

  for (const row of dirtyRows) {
    if (!row.lookupCode || !row.lookupName) {
      message.warning('lookupCode和名称不能为空');
      return null;
    }
  }

  try {
    await Promise.all(dirtyRows.map((r: any) => saveLookupConfig(r)));
    return {
      savedCount: dirtyRows.length,
      removedInvalidColumns
    };
  } catch {
    message.error('保存失败');
    return null;
  }
}

async function handleDisplayColumnConfirm() {
  const row = editingLookupRow.value;
  if (!row || savingDisplayColumns.value) return;

  row.displayColumns = stringifyDisplayColumns(displayColumnDrafts.value);
  markLookupRowDirty(row);
  gridApi.value?.refreshCells({ force: true, columns: ['displayColumns'] });
  savingDisplayColumns.value = true;

  try {
    const result = await saveLookupRows([row]);
    if (!result) return;

    if (result.savedCount > 0) {
      message.success(
        result.removedInvalidColumns > 0
          ? `显示列已保存，自动删除 ${result.removedInvalidColumns} 个失效列`
          : '显示列已保存'
      );
      handleDisplayColumnModalClose();
      await loadData();
    } else {
      handleDisplayColumnModalClose();
    }
  } finally {
    savingDisplayColumns.value = false;
  }
}

function handleAdd() {
  const newRow = {
    _isNew: true,
    id: null,
    lookupCode: '',
    lookupName: '',
    dataSource: '',
    displayColumns: '[]'
  };
  rowData.value = [...rowData.value, newRow];
  setTimeout(() => {
    const idx = rowData.value.length - 1;
    gridApi.value?.ensureIndexVisible(idx);
    gridApi.value?.startEditingCell({ rowIndex: idx, colKey: 'lookupCode' });
  }, 100);
}

async function handleSave() {
  const result = await saveLookupRows(rowData.value);
  if (!result) return;
  if (result.savedCount === 0) {
    message.info('没有需要保存的修改');
    return;
  }

  message.success(
    result.removedInvalidColumns > 0
      ? `已保存 ${result.savedCount} 条记录，自动删除 ${result.removedInvalidColumns} 个失效列`
      : `已保存 ${result.savedCount} 条记录`
  );
  await loadData();
}

async function handleDelete() {
  if (!selectedRow.value) return;
  if (isNewLookupRow(selectedRow.value)) {
    rowData.value = rowData.value.filter(r => r !== selectedRow.value);
    return;
  }
  try {
    await deleteLookupConfig(selectedRow.value.id);
    message.success('删除成功');
    await loadData();
  } catch {
    message.error('删除失败');
  }
}

function markDirty(event: CellValueChangedEvent) {
  markLookupRowDirty(event.data);
}

function onCellClicked(event: CellClickedEvent) {
  if (event.colDef.field !== 'displayColumns') return;
  openDisplayColumnEditor(event.data);
}

onMounted(() => {
  if (filterState?.value?.tab === 'lookup') return;
  loadData();
});

// 从目录管理跳转过来时，按 lookupCode 过滤
watch(
  () => filterState?.value,
  async state => {
    if (!state || state.tab !== 'lookup') return;
    const pageCode = state.pageCode;
    try {
      const [allData, codes] = await Promise.all([fetchAllLookupConfigs(), fetchLookupCodesByPageCode(pageCode)]);
      if (!codes.length) {
        message.warning(`pageCode="${pageCode}" 未关联任何Lookup`);
        return;
      }
      const codeSet = new Set(codes);
      rowData.value = (allData || []).filter((r: any) => codeSet.has(r.lookupCode));
      setTimeout(() => gridApi.value?.autoSizeAllColumns(), 100);
    } catch {
      message.error('查询关联Lookup失败');
    }
  },
  { immediate: true }
);
</script>

<template>
  <div class="panel-container">
    <div class="toolbar">
      <NSpace>
        <NButton size="small" type="primary" @click="handleAdd">新增</NButton>
        <NPopconfirm @positive-click="handleDelete">
          <template #trigger>
            <NButton size="small" type="error" :disabled="!selectedRow">删除</NButton>
          </template>
          确定删除选中记录？
        </NPopconfirm>
        <NButton size="small" @click="handleSave">保存</NButton>
        <NButton size="small" quaternary @click="loadData">刷新</NButton>
      </NSpace>
    </div>
    <div class="grid-wrapper">
      <AgGridVue
        class="ag-theme-quartz"
        style="width: 100%; height: 100%"
        :row-data="rowData"
        :column-defs="columnDefs"
        :default-col-def="defaultColDef"
        :suppress-scroll-on-new-data="true"
        :row-selection="{ mode: 'singleRow', checkboxes: false }"
        :cell-selection="true"
        @grid-ready="onGridReady"
        @selection-changed="onSelectionChanged"
        @row-clicked="onRowClicked"
        @cell-clicked="onCellClicked"
        @cell-value-changed="markDirty"
      />
    </div>

    <NModal
      v-model:show="showDisplayColumnModal"
      preset="card"
      title="配置显示列"
      class="display-columns-modal"
      :mask-closable="false"
      @close="handleDisplayColumnModalClose"
      @after-leave="handleDisplayColumnModalClose"
    >
      <div class="display-columns-toolbar">
        <div class="display-columns-meta">
          <span>数据源：{{ editingLookupRow?.dataSource || '-' }}</span>
          <span>已选 {{ selectedDisplayColumnCount }} 列</span>
        </div>
        <NSpace :size="8">
          <NButton size="small" @click="handleDisplayColumnSelectAll">全选</NButton>
          <NButton size="small" @click="handleDisplayColumnClear">清空</NButton>
        </NSpace>
      </div>

      <div v-if="loadingDisplayColumns" class="display-columns-empty">正在加载列结构...</div>
      <NEmpty
        v-else-if="displayColumnDrafts.length === 0"
        description="当前数据源没有可选列"
        class="display-columns-empty"
      />
      <div v-else class="display-columns-table-wrap">
        <NDataTable
          size="small"
          :columns="displayColumnTableColumns"
          :data="displayColumnTableData"
          :pagination="false"
          :bordered="false"
          :max-height="520"
        />
      </div>

      <template #footer>
        <div class="display-columns-footer">
          <NButton size="small" :disabled="savingDisplayColumns" @click="handleDisplayColumnModalClose">取消</NButton>
          <NButton type="primary" size="small" :loading="savingDisplayColumns" @click="handleDisplayColumnConfirm">
            确定
          </NButton>
        </div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.panel-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 8px;
}
.toolbar {
  flex-shrink: 0;
  padding: 4px 0;
}
.grid-wrapper {
  flex: 1;
  min-height: 0;
}
.display-columns-modal {
  width: min(980px, calc(100vw - 48px));
}
.display-columns-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.display-columns-meta {
  display: flex;
  gap: 16px;
  color: #5b6475;
  font-size: 13px;
}
.display-columns-table-wrap {
  border: 1px solid #e8ebf3;
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}
.display-column-field {
  font-weight: 600;
  color: #222a3a;
}
.display-column-field-cell {
  display: flex;
  align-items: center;
  min-height: 32px;
}
.display-columns-empty {
  padding: 24px 0;
}
.display-columns-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.display-columns-modal :deep(.n-data-table-th) {
  background: #f6f8fc;
  color: #4a5366;
  font-weight: 600;
}
</style>
