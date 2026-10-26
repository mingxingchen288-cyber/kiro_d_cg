<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { NButton, NInput, NModal, NSpace } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, GridApi, GridReadyEvent, SelectionChangedEvent } from 'ag-grid-community';
import { fetchLookupConfig } from '@/service/api';
import { request } from '@/service/request';
import SvgIcon from '@/components/custom/svg-icon.vue';

/**
 * Lookup 弹窗组件 Props
 *
 * 筛选相关属性说明：
 * - filterField: 从"当前行数据"取哪个字段的值作为筛选值
 *   生效场景：filterValueFrom 没写或为 'row'
 *   例：filterField: "id" → 用当前行的 rowData.id 作为筛选值
 *
 * - filterColumn: 弹窗数据源里要过滤的列名（SQL 中的列名）
 *   例：filterColumn: "GOODSID" → 最终会拼成 AND GOODSID = <filterValue>
 *
 * - filterValueFrom: 筛选值来源
 *   'row': 用 rowData[filterField]
 *   'cell': 用你点击的单元格的值（不需要 filterField）
 *
 * - filterValue: 直接传入的筛选值（filterValueFrom='cell' 时使用）
 */
const props = withDefaults(
  defineProps<{
    lookupCode: string;
    mapping?: Record<string, string>;
    multiple?: boolean;
    /** 当前行数据，用于 filterValueFrom='row' 时取值 */
    rowData?: Record<string, any>;
    /** 从当前行取哪个字段的值作为筛选值 */
    filterField?: string;
    /** 弹窗数据源的筛选列名（SQL列名） */
    filterColumn?: string;
    /** 筛选值来源：'row' 用行数据字段，'cell' 用点击单元格的值 */
    filterValueFrom?: 'row' | 'cell';
    /** 直接传入的筛选值（filterValueFrom='cell' 时使用） */
    filterValue?: any;
  }>(),
  {
    mapping: () => ({}),
    multiple: false,
    rowData: undefined,
    filterField: undefined,
    filterColumn: undefined,
    filterValueFrom: undefined,
    filterValue: undefined
  }
);
const emit = defineEmits<{
  (e: 'select', data: Record<string, any>): void;
  (e: 'select', data: Record<string, any>[]): void;
  (e: 'cancel'): void;
}>();

const visible = ref(false);
const config = ref<Api.Metadata.LookupConfig | null>(null);
const lastLookupCode = ref('');
const tableRows = ref<Record<string, any>[]>([]);
const searchText = ref('');
const selectedRow = ref<Record<string, any> | null>(null);
const selectedRows = ref<Record<string, any>[]>([]);
let gridApi: GridApi | null = null;
let searchTimer: ReturnType<typeof setTimeout> | null = null;

const dialogWidth = ref(1050);
const dialogHeight = ref(550);
const dialogX = ref(0);
const dialogY = ref(0);
const dialogRef = ref<HTMLElement | null>(null);

const isDragging = ref(false);
const isResizing = ref(false);
const dragStartX = ref(0);
const dragStartY = ref(0);
const startWidth = ref(0);
const startHeight = ref(0);

function normalizeColumnName(name?: string | null): string {
  return String(name || '')
    .trim()
    .toUpperCase();
}

function normalizeFieldToken(name?: string | null): string {
  return String(name || '')
    .trim()
    .replace(/[^a-zA-Z0-9]/g, '')
    .toLowerCase();
}

function resolveRowFieldValue(row: Record<string, any> | null | undefined, field?: string | null) {
  if (!row || !field) return undefined;
  const rawField = String(field).trim();
  if (!rawField) return undefined;
  if (rawField in row) return row[rawField];
  const upperField = normalizeColumnName(rawField);
  if (upperField in row) return row[upperField];
  const token = normalizeFieldToken(rawField);
  if (!token) return undefined;
  const matchedKey = Object.keys(row).find(key => normalizeFieldToken(key) === token);
  return matchedKey ? row[matchedKey] : undefined;
}

const columnDefs = computed<ColDef[]>(() => {
  if (!config.value?.displayColumns) return [];
  return config.value.displayColumns.map(col => ({
    field: normalizeColumnName(col.field),
    headerName: col.header,
    ...(col.width ? { width: col.width } : { flex: 1, minWidth: 120 }),
    sortable: true,
    resizable: true
  }));
});

const defaultColDef: ColDef = { sortable: true, resizable: true, suppressHeaderMenuButton: true };
const rowSelection = computed(() => ({
  mode: props.multiple ? ('multiRow' as const) : ('singleRow' as const),
  enableClickSelection: true,
  checkboxes: props.multiple
}));
const hasMapping = computed(() => props.mapping && Object.keys(props.mapping).length > 0);
const confirmDisabled = computed(() => {
  if (!hasMapping.value) return true;
  return props.multiple ? selectedRows.value.length === 0 : !selectedRow.value;
});

const dialogStyle = computed(() => ({
  width: `${dialogWidth.value}px`,
  height: `${dialogHeight.value}px`,
  transform: `translate(${dialogX.value}px, ${dialogY.value}px)`
}));

const gridHeight = computed(() => dialogHeight.value - 168);

function startDrag(e: MouseEvent) {
  if ((e.target as HTMLElement).closest('button')) return;
  e.preventDefault();
  isDragging.value = true;
  dragStartX.value = e.clientX - dialogX.value;
  dragStartY.value = e.clientY - dialogY.value;
  document.addEventListener('mousemove', onDrag);
  document.addEventListener('mouseup', stopDrag);
}

function onDrag(e: MouseEvent) {
  if (!isDragging.value) return;
  dialogX.value = e.clientX - dragStartX.value;
  dialogY.value = e.clientY - dragStartY.value;
}

function stopDrag() {
  isDragging.value = false;
  document.removeEventListener('mousemove', onDrag);
  document.removeEventListener('mouseup', stopDrag);
}

function startResize(e: MouseEvent) {
  e.preventDefault();
  isResizing.value = true;
  dragStartX.value = e.clientX;
  dragStartY.value = e.clientY;
  startWidth.value = dialogWidth.value;
  startHeight.value = dialogHeight.value;
  document.addEventListener('mousemove', onResize);
  document.addEventListener('mouseup', stopResize);
}

function onResize(e: MouseEvent) {
  if (!isResizing.value) return;
  dialogWidth.value = Math.max(600, Math.min(startWidth.value + e.clientX - dragStartX.value, window.innerWidth - 100));
  dialogHeight.value = Math.max(
    400,
    Math.min(startHeight.value + e.clientY - dragStartY.value, window.innerHeight - 100)
  );
}

function stopResize() {
  isResizing.value = false;
  document.removeEventListener('mousemove', onResize);
  document.removeEventListener('mouseup', stopResize);
  gridApi?.sizeColumnsToFit();
}

async function open() {
  visible.value = true;
  selectedRow.value = null;
  selectedRows.value = [];
  searchText.value = '';
  dialogX.value = 0;
  dialogY.value = 0;
  // lookupCode 变化时重新加载配置，避免复用旧表头
  if (!config.value || lastLookupCode.value !== props.lookupCode) {
    lastLookupCode.value = props.lookupCode;
    config.value = null;
    const { data } = await fetchLookupConfig(props.lookupCode);
    if (data) config.value = data;
  }
  await loadData();
}

/**
 * 加载弹窗数据
 *
 * 筛选逻辑：
 * 1. filterValueFrom='cell' → 直接用 props.filterValue
 * 2. filterValueFrom='row' 或未配置 → 用 rowData[filterField]
 * 3. 有 filterColumn 且 filterValue 不为空时，传给后端做 SQL 筛选
 */
async function loadData() {
  if (!config.value?.lookupCode) return;
  const params: Record<string, any> = { page: 1, pageSize: 500 };

  // 确定筛选值来源
  let filterValue: any = null;
  if (props.filterValueFrom === 'cell') {
    // 'cell' 模式：用点击单元格的值
    filterValue = props.filterValue;
  } else if (props.filterField && props.rowData) {
    // 'row' 模式或默认：用 rowData[filterField]
    filterValue = resolveRowFieldValue(props.rowData, props.filterField);
  }

  // 有筛选列名且筛选值不为空时，传给后端
  if (props.filterColumn && filterValue !== null && filterValue !== undefined) {
    params.filterColumn = props.filterColumn;
    params.filterValue = filterValue;
  }
  const keyword = searchText.value.trim();
  if (keyword) {
    params.keyword = keyword;
  }

  const { data } = await request<{ list: Record<string, any>[] }>({
    url: `/api/lookup/${props.lookupCode}/data`,
    params
  });
  tableRows.value = data?.list || [];
  selectedRow.value = null;
  selectedRows.value = [];
}

function handleSearch() {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
  searchTimer = setTimeout(() => {
    loadData();
  }, 250);
}

function handleCancel() {
  visible.value = false;
  emit('cancel');
}

function handleConfirm() {
  const buildFillData = (row: Record<string, any>) => {
    const fillData: Record<string, any> = {};
    for (const [targetField, sourceField] of Object.entries(props.mapping)) {
      fillData[targetField] = resolveRowFieldValue(row, sourceField);
    }
    return fillData;
  };

  if (props.multiple) {
    if (selectedRows.value.length === 0) return;
    visible.value = false;
    emit(
      'select',
      selectedRows.value.map(row => buildFillData(row))
    );
    return;
  }

  if (!selectedRow.value) return;
  visible.value = false;
  emit('select', buildFillData(selectedRow.value));
}

function onGridReady(params: GridReadyEvent) {
  gridApi = params.api;
  // 数据加载后自动调整列宽
  setTimeout(() => {
    gridApi?.autoSizeAllColumns();
  }, 100);
}
function onRowDoubleClicked() {
  if (props.multiple) return;
  if (selectedRow.value && hasMapping.value) handleConfirm();
}
function onSelectionChanged(event: SelectionChangedEvent) {
  const rows = event.api.getSelectedRows();
  selectedRows.value = rows;
  selectedRow.value = rows.length > 0 ? rows[0] : null;
}

watch(searchText, handleSearch);

onUnmounted(() => {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
  document.removeEventListener('mousemove', onDrag);
  document.removeEventListener('mouseup', stopDrag);
  document.removeEventListener('mousemove', onResize);
  document.removeEventListener('mouseup', stopResize);
});

defineExpose({ open });
</script>

<template>
  <NModal v-model:show="visible" :mask-closable="true" :close-on-esc="true">
    <div ref="dialogRef" class="lookup-dialog" :style="dialogStyle">
      <!-- 标题栏（可拖拽） -->
      <div class="lookup-dialog-header" @mousedown="startDrag">
        <span class="lookup-dialog-title">{{ config?.lookupName || '选择' }}</span>
        <NButton quaternary circle size="small" @click="handleCancel">
          <template #icon><SvgIcon icon="mdi:close" /></template>
        </NButton>
      </div>

      <!-- 内容区 -->
      <div class="lookup-dialog-body">
        <div class="lookup-search">
          <NInput v-model:value="searchText" placeholder="输入关键字搜索" clearable @keyup.enter="handleSearch">
            <template #prefix><SvgIcon icon="mdi:magnify" class="text-icon" /></template>
          </NInput>
        </div>
        <div class="lookup-grid" :style="{ height: gridHeight + 'px' }">
          <AgGridVue
            class="ag-theme-quartz"
            style="width: 100%; height: 100%"
            :row-data="tableRows"
            :column-defs="columnDefs"
            :default-col-def="defaultColDef"
            :row-selection="rowSelection"
            @grid-ready="onGridReady"
            @row-double-clicked="onRowDoubleClicked"
            @selection-changed="onSelectionChanged"
          />
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="lookup-dialog-footer">
        <NSpace justify="end">
          <NButton @click="handleCancel">取消</NButton>
          <NButton type="primary" :disabled="confirmDisabled" @click="handleConfirm">确定</NButton>
        </NSpace>
      </div>

      <!-- 右下角拖拽调整大小手柄 -->
      <div class="resize-handle" @mousedown.stop="startResize"></div>
    </div>
  </NModal>
</template>

<style scoped>
.lookup-dialog {
  background: #fff;
  border-radius: 8px;
  box-shadow:
    0 6px 16px 0 rgba(0, 0, 0, 0.08),
    0 3px 6px -4px rgba(0, 0, 0, 0.12),
    0 9px 28px 8px rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  position: relative;
  min-width: 600px;
  min-height: 400px;
}
.lookup-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  cursor: move;
  user-select: none;
}
.lookup-dialog-title {
  font-size: 16px;
  font-weight: 500;
  color: #333;
}
.lookup-dialog-body {
  flex: 1;
  padding: 16px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.lookup-search {
  margin-bottom: 12px;
  flex-shrink: 0;
}
.lookup-grid {
  flex: 1;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  overflow: hidden;
}
.lookup-dialog-footer {
  padding: 12px 16px;
  border-top: 1px solid #f0f0f0;
}
.resize-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 16px;
  height: 16px;
  cursor: se-resize;
  background: linear-gradient(
    135deg,
    transparent 50%,
    #d9d9d9 50%,
    #d9d9d9 60%,
    transparent 60%,
    transparent 70%,
    #d9d9d9 70%,
    #d9d9d9 80%,
    transparent 80%
  );
  border-radius: 0 0 8px 0;
}
.resize-handle:hover {
  background: linear-gradient(
    135deg,
    transparent 50%,
    #1890ff 50%,
    #1890ff 60%,
    transparent 60%,
    transparent 70%,
    #1890ff 70%,
    #1890ff 80%,
    transparent 80%
  );
}
</style>
