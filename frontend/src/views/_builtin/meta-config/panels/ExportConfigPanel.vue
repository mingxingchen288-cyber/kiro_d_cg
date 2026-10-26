<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue';
import { NButton, NPopconfirm, NSpace, useMessage } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type { CellValueChangedEvent, ColDef, GridApi, GridReadyEvent } from 'ag-grid-community';
import {
  deleteExportConfig,
  deleteExportConfigDetail,
  fetchAllExportConfigs,
  fetchExportConfigDetails,
  saveExportConfig,
  saveExportConfigDetail
} from '@/service/api/meta-config';

const message = useMessage();

const configGridApi = ref<GridApi | null>(null);
const configRows = ref<any[]>([]);
const selectedConfig = ref<any>(null);

const detailGridApi = ref<GridApi | null>(null);
const detailRows = ref<any[]>([]);
const selectedDetail = ref<any>(null);

const topHeight = ref(300);
let startY = 0;
let startHeight = 0;

const largeTextEditorParams = {
  rows: 18,
  cols: 120,
  maxLength: 200000
};

function normalizeText(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function summarizeText(value: unknown, emptyLabel = '双击编辑') {
  const text = normalizeText(value);
  if (!text) return emptyLabel;
  return text.length > 80 ? `${text.slice(0, 80)}...` : text;
}

function summarizeColumns(value: unknown) {
  const text = normalizeText(value);
  if (!text) return '双击编辑列配置';

  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return `列配置(${parsed.length})`;
    }
  } catch {
    // ignore
  }

  return summarizeText(text);
}

function markConfigDirty(row: Record<string, any> | null | undefined) {
  if (row) Reflect.set(row, '_dirty', true);
}

function markDetailDirty(row: Record<string, any> | null | undefined) {
  if (row) Reflect.set(row, '_dirty', true);
}

function isNewRow(row: Record<string, any> | null | undefined) {
  return Boolean(row && Reflect.get(row, '_isNew'));
}

function isDirtyRow(row: Record<string, any> | null | undefined) {
  return Boolean(row && (Reflect.get(row, '_dirty') || Reflect.get(row, '_isNew')));
}

const configColDefs: ColDef[] = [
  { field: 'id', headerName: 'ID', width: 70, editable: false },
  { field: 'pageCode', headerName: '页面编码', width: 160, editable: true },
  { field: 'exportCode', headerName: '导出编码', width: 180, editable: true },
  { field: 'exportName', headerName: '导出名称', width: 180, editable: true },
  { field: 'masterSheetName', headerName: '主Sheet', width: 120, editable: true },
  { field: 'displayOrder', headerName: '排序', width: 80, editable: true, cellDataType: 'number' },
  { field: 'masterTableAlias', headerName: '主表别名', width: 110, editable: true },
  { field: 'pkColumn', headerName: '主键列', width: 120, editable: true },
  { field: 'pageViewAlias', headerName: '页面视图别名', width: 130, editable: true },
  { field: 'pageFkColumn', headerName: '页面关联列', width: 140, editable: true },
  { field: 'masterLinkColumn', headerName: '导出关联列', width: 140, editable: true },
  {
    field: 'columns',
    headerName: '主表列(JSON)',
    width: 160,
    editable: true,
    cellEditor: 'agLargeTextCellEditor',
    cellEditorPopup: true,
    cellEditorParams: largeTextEditorParams,
    valueFormatter: params => summarizeColumns(params.value),
    tooltipValueGetter: params => normalizeText(params.value)
  },
  {
    field: 'masterSql',
    headerName: '主表SQL',
    flex: 1,
    minWidth: 280,
    editable: true,
    cellEditor: 'agLargeTextCellEditor',
    cellEditorPopup: true,
    cellEditorParams: largeTextEditorParams,
    valueFormatter: params => summarizeText(params.value, '双击编辑主表SQL'),
    tooltipValueGetter: params => normalizeText(params.value)
  }
];

const detailColDefs: ColDef[] = [
  { field: 'id', headerName: 'ID', width: 70, editable: false },
  { field: 'tabKey', headerName: 'tabKey', width: 120, editable: true },
  { field: 'sheetName', headerName: 'Sheet名称', width: 140, editable: true },
  { field: 'displayOrder', headerName: '排序', width: 80, editable: true, cellDataType: 'number' },
  { field: 'masterTableAlias', headerName: '主表别名', width: 110, editable: true },
  { field: 'detailTableAlias', headerName: '明细别名', width: 110, editable: true },
  { field: 'detailLinkColumn', headerName: '明细关联列', width: 140, editable: true },
  {
    field: 'columns',
    headerName: '明细列(JSON)',
    width: 160,
    editable: true,
    cellEditor: 'agLargeTextCellEditor',
    cellEditorPopup: true,
    cellEditorParams: largeTextEditorParams,
    valueFormatter: params => summarizeColumns(params.value),
    tooltipValueGetter: params => normalizeText(params.value)
  },
  {
    field: 'detailSql',
    headerName: '明细SQL',
    flex: 1,
    minWidth: 320,
    editable: true,
    cellEditor: 'agLargeTextCellEditor',
    cellEditorPopup: true,
    cellEditorParams: largeTextEditorParams,
    valueFormatter: params => summarizeText(params.value, '双击编辑明细SQL'),
    tooltipValueGetter: params => normalizeText(params.value)
  }
];

const defaultColDef: ColDef = {
  sortable: true,
  resizable: true,
  flex: 0,
  suppressHeaderMenuButton: true
};

async function loadConfigs(target?: { id?: number | null; exportCode?: string | null }) {
  try {
    const res = await fetchAllExportConfigs();
    configRows.value = res || [];
    await nextTick();
    configGridApi.value?.autoSizeAllColumns();

    if (!target) {
      selectedConfig.value = null;
      detailRows.value = [];
      selectedDetail.value = null;
      return;
    }

    const matched =
      configRows.value.find(row => target.id && row.id === target.id) ||
      configRows.value.find(row => target.exportCode && row.exportCode === target.exportCode) ||
      null;

    if (!matched) {
      selectedConfig.value = null;
      detailRows.value = [];
      selectedDetail.value = null;
      return;
    }

    selectedConfig.value = matched;
    configGridApi.value?.forEachNode(node => {
      if (node.data?.id === matched.id) {
        node.setSelected(true, true);
      }
    });
    await loadDetails(matched.id);
  } catch {
    message.error('加载导出配置失败');
  }
}

async function loadDetails(exportConfigId?: number | null) {
  if (!exportConfigId) {
    detailRows.value = [];
    selectedDetail.value = null;
    return;
  }

  try {
    const res = await fetchExportConfigDetails(exportConfigId);
    detailRows.value = res || [];
    selectedDetail.value = null;
    await nextTick();
    detailGridApi.value?.autoSizeAllColumns();
  } catch {
    message.error('加载导出明细失败');
  }
}

function onConfigGridReady(params: GridReadyEvent) {
  configGridApi.value = params.api;
  params.api.autoSizeAllColumns();
}

function onDetailGridReady(params: GridReadyEvent) {
  detailGridApi.value = params.api;
  params.api.autoSizeAllColumns();
}

async function onConfigSelectionChanged() {
  const rows = configGridApi.value?.getSelectedRows() || [];
  selectedConfig.value = rows[0] || null;
  await loadDetails(selectedConfig.value?.id || null);
}

function onDetailSelectionChanged() {
  const rows = detailGridApi.value?.getSelectedRows() || [];
  selectedDetail.value = rows[0] || null;
}

function onConfigRowClicked(event: any) {
  if (event.node?.data) {
    event.node.setSelected(true, true);
  }
}

function onDetailRowClicked(event: any) {
  if (event.node?.data) {
    event.node.setSelected(true, true);
  }
}

function addConfig() {
  const newRow = {
    _isNew: true,
    id: null,
    pageCode: '',
    exportCode: '',
    exportName: '',
    masterSql: '',
    masterTableAlias: '',
    pkColumn: '',
    pageViewAlias: 'p',
    pageFkColumn: '',
    masterLinkColumn: '',
    columns: '[]',
    masterSheetName: 'master',
    displayOrder: 0,
    deleted: 0
  };
  configRows.value = [...configRows.value, newRow];
  selectedConfig.value = newRow;
  detailRows.value = [];
  selectedDetail.value = null;

  nextTick(() => {
    const idx = configRows.value.length - 1;
    configGridApi.value?.ensureIndexVisible(idx);
    configGridApi.value?.startEditingCell({ rowIndex: idx, colKey: 'pageCode' });
  });
}

async function saveConfigs() {
  configGridApi.value?.stopEditing();
  const dirtyRows = configRows.value.filter(row => isDirtyRow(row));
  if (dirtyRows.length === 0) {
    message.info('没有需要保存的导出配置');
    return;
  }

  for (const row of dirtyRows) {
    if (!normalizeText(row.pageCode) || !normalizeText(row.exportCode) || !normalizeText(row.exportName)) {
      message.warning('页面编码、导出编码、导出名称不能为空');
      return;
    }
    if (!normalizeText(row.masterSql)) {
      message.warning('主表SQL不能为空');
      return;
    }
  }

  try {
    const savedRows = await Promise.all(dirtyRows.map(row => saveExportConfig(row)));
    const latest = savedRows[savedRows.length - 1];
    message.success(`已保存 ${savedRows.length} 条导出配置`);
    await loadConfigs({
      id: latest?.id ?? selectedConfig.value?.id ?? null,
      exportCode: latest?.exportCode ?? selectedConfig.value?.exportCode ?? ''
    });
  } catch {
    message.error('保存导出配置失败');
  }
}

async function removeConfig() {
  if (!selectedConfig.value) return;

  if (isNewRow(selectedConfig.value)) {
    configRows.value = configRows.value.filter(row => row !== selectedConfig.value);
    selectedConfig.value = null;
    detailRows.value = [];
    return;
  }

  try {
    await deleteExportConfig(selectedConfig.value.id);
    message.success('删除导出配置成功');
    await loadConfigs();
  } catch {
    message.error('删除导出配置失败');
  }
}

function addDetail() {
  if (!selectedConfig.value) {
    message.warning('请先选中一条导出配置');
    return;
  }
  if (!selectedConfig.value.id || isNewRow(selectedConfig.value)) {
    message.warning('请先保存导出配置，再新增明细');
    return;
  }

  const newRow = {
    _isNew: true,
    id: null,
    exportConfigId: selectedConfig.value.id,
    tabKey: '',
    sheetName: '',
    detailSql: '',
    masterTableAlias: selectedConfig.value.masterTableAlias || '',
    detailTableAlias: '',
    detailLinkColumn: '',
    columns: '[]',
    displayOrder: detailRows.value.length
  };
  detailRows.value = [...detailRows.value, newRow];
  selectedDetail.value = newRow;

  nextTick(() => {
    const idx = detailRows.value.length - 1;
    detailGridApi.value?.ensureIndexVisible(idx);
    detailGridApi.value?.startEditingCell({ rowIndex: idx, colKey: 'tabKey' });
  });
}

async function saveDetails() {
  detailGridApi.value?.stopEditing();
  if (!selectedConfig.value?.id) {
    message.warning('请先选中已保存的导出配置');
    return;
  }

  const dirtyRows = detailRows.value.filter(row => isDirtyRow(row));
  if (dirtyRows.length === 0) {
    message.info('没有需要保存的导出明细');
    return;
  }

  for (const row of dirtyRows) {
    row.exportConfigId = selectedConfig.value.id;
    if (!normalizeText(row.detailSql)) {
      message.warning('明细SQL不能为空');
      return;
    }
  }

  try {
    await Promise.all(dirtyRows.map(row => saveExportConfigDetail(row)));
    message.success(`已保存 ${dirtyRows.length} 条导出明细`);
    await loadDetails(selectedConfig.value.id);
  } catch {
    message.error('保存导出明细失败');
  }
}

async function removeDetail() {
  if (!selectedDetail.value) return;

  if (isNewRow(selectedDetail.value)) {
    detailRows.value = detailRows.value.filter(row => row !== selectedDetail.value);
    selectedDetail.value = null;
    return;
  }

  try {
    await deleteExportConfigDetail(selectedDetail.value.id);
    message.success('删除导出明细成功');
    await loadDetails(selectedConfig.value?.id || null);
  } catch {
    message.error('删除导出明细失败');
  }
}

function markConfigChanged(event: CellValueChangedEvent) {
  markConfigDirty(event.data);
}

function markDetailChanged(event: CellValueChangedEvent) {
  markDetailDirty(event.data);
}

function onResizeStart(event: MouseEvent) {
  startY = event.clientY;
  startHeight = topHeight.value;
  document.addEventListener('mousemove', onResizeMove);
  document.addEventListener('mouseup', onResizeEnd);
  document.body.style.cursor = 'row-resize';
  document.body.style.userSelect = 'none';
}

function onResizeMove(event: MouseEvent) {
  const delta = event.clientY - startY;
  topHeight.value = Math.max(120, startHeight + delta);
}

function onResizeEnd() {
  document.removeEventListener('mousemove', onResizeMove);
  document.removeEventListener('mouseup', onResizeEnd);
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
}

onMounted(() => {
  loadConfigs();
});
</script>

<template>
  <div class="panel-container">
    <div class="section" :style="{ flex: `0 0 ${topHeight}px` }">
      <div class="section-toolbar">
        <NSpace size="small">
          <NButton size="small" type="primary" @click="addConfig">新增导出</NButton>
          <NPopconfirm @positive-click="removeConfig">
            <template #trigger>
              <NButton size="small" type="error" :disabled="!selectedConfig">删除导出</NButton>
            </template>
            确定删除当前导出配置？
          </NPopconfirm>
          <NButton size="small" @click="saveConfigs">保存导出</NButton>
          <NButton size="small" quaternary @click="loadConfigs(selectedConfig)">刷新</NButton>
        </NSpace>
      </div>
      <div class="grid-wrapper">
        <AgGridVue
          class="ag-theme-quartz grid-host"
          :row-data="configRows"
          :column-defs="configColDefs"
          :default-col-def="defaultColDef"
          :suppress-scroll-on-new-data="true"
          :row-selection="{ mode: 'singleRow', checkboxes: false }"
          :cell-selection="true"
          @grid-ready="onConfigGridReady"
          @selection-changed="onConfigSelectionChanged"
          @row-clicked="onConfigRowClicked"
          @cell-value-changed="markConfigChanged"
        />
      </div>
    </div>

    <div class="resizer" @mousedown="onResizeStart" />

    <div class="section fill-section">
      <div class="section-toolbar">
        <NSpace size="small">
          <NButton size="small" type="primary" :disabled="!selectedConfig?.id" @click="addDetail">新增明细</NButton>
          <NPopconfirm @positive-click="removeDetail">
            <template #trigger>
              <NButton size="small" type="error" :disabled="!selectedDetail">删除明细</NButton>
            </template>
            确定删除当前导出明细？
          </NPopconfirm>
          <NButton size="small" @click="saveDetails">保存明细</NButton>
          <NButton size="small" quaternary :disabled="!selectedConfig?.id" @click="loadDetails(selectedConfig?.id)">
            刷新明细
          </NButton>
        </NSpace>
        <div class="detail-hint">
          当前导出：
          <span>{{ selectedConfig?.exportName || '-' }}</span>
        </div>
      </div>
      <div class="grid-wrapper">
        <AgGridVue
          class="ag-theme-quartz grid-host"
          :row-data="detailRows"
          :column-defs="detailColDefs"
          :default-col-def="defaultColDef"
          :suppress-scroll-on-new-data="true"
          :row-selection="{ mode: 'singleRow', checkboxes: false }"
          :cell-selection="true"
          @grid-ready="onDetailGridReady"
          @selection-changed="onDetailSelectionChanged"
          @row-clicked="onDetailRowClicked"
          @cell-value-changed="markDetailChanged"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.section {
  display: flex;
  flex-direction: column;
  min-height: 120px;
  overflow: hidden;
}

.section-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  padding: 4px 0;
}

.grid-wrapper {
  flex: 1;
  min-height: 0;
}

.grid-host {
  width: 100%;
  height: 100%;
}

.fill-section {
  flex: 1;
}

.resizer {
  flex-shrink: 0;
  height: 6px;
  cursor: row-resize;
  background: #e8e8e8;
  border-radius: 3px;
  margin: 2px 0;
  transition: background 0.2s;
}

.resizer:hover {
  background: #4096ff;
}

.detail-hint {
  color: #5b6475;
  font-size: 12px;
  white-space: nowrap;
}

.detail-hint span {
  color: #222a3a;
  font-weight: 600;
}
</style>
