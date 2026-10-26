<script setup lang="ts">
import { computed, ref } from 'vue';
import { NAutoComplete, NButton, NCollapse, NCollapseItem, NDataTable, NDescriptions, NDescriptionsItem, NInput, NModal, NSpace, useMessage } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef } from 'ag-grid-community';
import { deleteColumnMeta, fetchColumnsByTableId, fetchDbObjects, fetchViewColumns, saveColumnMeta, saveTableMeta as saveTableMetaApi } from '@/service/api/meta-config';
import LookupConfigEditor from './LookupConfigEditor.vue';

const props = defineProps<{
  pageCode: string;
  tables: any[];
  components: any[];
}>();

const emit = defineEmits<{
  (e: 'refresh'): void;
}>();

const message = useMessage();

// 每张表的列数据（按需加载）
const columnsByTable = ref<Record<number, any[]>>({});
const loadingTable = ref<Record<number, boolean>>({});
const dirtyColumns = ref<Record<number, Set<any>>>({});
const dbObjectOptions = ref<string[]>([]);
const AUDIT_FIELDS = new Set(['DELETED', 'CREATE_TIME', 'UPDATE_TIME', 'CREATE_BY', 'UPDATE_BY']);
const gridApis = ref<Record<number, any>>({});
const LOOKUP_EDITORS = new Set(['lookup', 'lookupMultiple']);
const EDITOR_LABEL_TO_VALUE: Record<string, string> = {
  '(无)': '',
  文本: 'agTextCellEditor',
  大文本: 'agLargeTextCellEditor',
  数字: 'agNumberCellEditor',
  日期: 'datePicker',
  下拉: 'agSelectCellEditor',
  '下拉（可填写）': 'tagSelectCellEditor',
  富文本下拉: 'agRichSelectCellEditor',
  弹窗选择: 'lookup',
  多选弹窗: 'lookupMultiple'
};
const EDITOR_VALUE_TO_LABEL = Object.fromEntries(
  Object.entries(EDITOR_LABEL_TO_VALUE).map(([label, value]) => [value, label])
) as Record<string, string>;
const EDITOR_LABELS = Object.keys(EDITOR_LABEL_TO_VALUE);

// 搜索数据库表/视图
async function searchDbObjects(keyword: string) {
  if (!keyword || keyword.length < 2) {
    dbObjectOptions.value = [];
    return;
  }
  try {
    const results = await fetchDbObjects(keyword);
    dbObjectOptions.value = results.map((r: any) => r.OBJECT_NAME || r.objectName || '');
  } catch {
    dbObjectOptions.value = [];
  }
}

const columnDefs: ColDef[] = [
  { field: 'columnName', headerName: '字段名', width: 130, editable: false, rowDrag: true },
  { field: 'headerText', headerName: '标题', width: 120, editable: true },
  { field: 'dataType', headerName: '类型', width: 90, editable: true,
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: ['text', 'number', 'date', 'select', 'checkbox'] } },
  { field: 'targetColumn', headerName: 'TARGET', width: 130, editable: true },
  { field: 'isVirtual', headerName: '虚拟', width: 55, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => p.data?.isVirtual === 1,
    valueSetter: (p: any) => { p.data.isVirtual = p.newValue ? 1 : 0; return true; } },
  { field: 'visible', headerName: '显示', width: 55, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => p.data?.visible === 1,
    valueSetter: (p: any) => { p.data.visible = p.newValue ? 1 : 0; return true; } },
  { field: 'editable', headerName: '编辑', width: 55, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => p.data?.editable === 1,
    valueSetter: (p: any) => { p.data.editable = p.newValue ? 1 : 0; return true; } },
  { field: 'searchable', headerName: '查询', width: 55, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => p.data?.searchable === 1,
    valueSetter: (p: any) => { p.data.searchable = p.newValue ? 1 : 0; return true; } },
  { field: 'required', headerName: '必填', width: 55, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => p.data?.required === 1,
    valueSetter: (p: any) => { p.data.required = p.newValue ? 1 : 0; return true; } },
  { field: '_aggFunc', headerName: '求和', width: 55, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => getRulesConfigProp(p.data, 'aggFunc') === 'sum',
    valueSetter: (p: any) => { setRulesConfigProp(p.data, 'aggFunc', p.newValue ? 'sum' : ''); return true; } },
  { field: '_precision', headerName: '精度', width: 55, editable: true,
    valueGetter: (p: any) => { const v = getRulesConfigProp(p.data, 'precision'); return v != null ? v : ''; },
    valueSetter: (p: any) => { const val = p.newValue === '' || p.newValue == null ? null : Number(p.newValue); setRulesConfigProp(p.data, 'precision', Number.isFinite(val) ? val : null); return true; } },
  { field: '_roundMode', headerName: '取整', width: 70, editable: true,
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: ['', 'round', 'ceil', 'floor'] },
    valueGetter: (p: any) => getRulesConfigProp(p.data, 'roundMode') || '',
    valueSetter: (p: any) => { setRulesConfigProp(p.data, 'roundMode', p.newValue || null); return true; } },
  { field: '_useGrouping', headerName: '千分位', width: 70, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => getRulesConfigProp(p.data, 'useGrouping') === true,
    valueSetter: (p: any) => { setRulesConfigProp(p.data, 'useGrouping', p.newValue ? true : null); return true; } },
  { field: 'sortable', headerName: '可排序', width: 55, editable: true,
    cellEditor: 'agCheckboxCellEditor', cellRenderer: 'agCheckboxCellRenderer',
    valueGetter: (p: any) => p.data?.sortable === 1,
    valueSetter: (p: any) => { p.data.sortable = p.newValue ? 1 : 0; return true; } },
  { field: 'width', headerName: '宽度', width: 55, editable: true, cellDataType: 'number' },
  { field: 'cellEditor', headerName: '编辑器', width: 120, editable: true,
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: EDITOR_LABELS },
    valueGetter: (p: any) => {
      return EDITOR_VALUE_TO_LABEL[p.data?.cellEditor || ''] || p.data?.cellEditor || '(无)';
    },
    valueSetter: (p: any) => {
      p.data.cellEditor = EDITOR_LABEL_TO_VALUE[p.newValue] ?? '';
      const params = getRulesConfigProp(p.data, 'cellEditorParams');
      if (params && typeof params === 'object' && LOOKUP_EDITORS.has(p.data.cellEditor)) {
        const nextParams = { ...params };
        if (p.data.cellEditor === 'lookupMultiple') {
          nextParams.multiple = true;
        } else {
          delete nextParams.multiple;
        }
        setRulesConfigProp(p.data, 'cellEditorParams', nextParams);
      }
      return true;
    }
  },
  { field: '_editorValues', headerName: '选项值', width: 160,
    editable: (params: any) => !LOOKUP_EDITORS.has(params.data?.cellEditor),
    cellRenderer: (params: any) => {
      const el = document.createElement('span');
      if (LOOKUP_EDITORS.has(params.data?.cellEditor)) {
        // Lookup 类型显示为可点击按钮
        const code = getRulesConfigProp(params.data, 'cellEditorParams')?.lookupCode || '';
        const prefix = params.data?.cellEditor === 'lookupMultiple' ? '多选Lookup' : 'Lookup';
        el.textContent = code ? `${prefix}: ${code}` : '配置Lookup';
        el.style.color = code ? '#2080f0' : '#999';
        el.style.cursor = 'pointer';
        el.addEventListener('click', () => openLookupEditor(params.data));
      } else {
        // 下拉类型显示逗号分隔的值
        const p = getRulesConfigProp(params.data, 'cellEditorParams');
        el.textContent = p?.values && Array.isArray(p.values) ? p.values.join(',') : '';
      }
      return el;
    },
    valueGetter: (p: any) => {
      if (LOOKUP_EDITORS.has(p.data?.cellEditor)) return '';
      const params = getRulesConfigProp(p.data, 'cellEditorParams');
      if (!params || !params.values) return '';
      return Array.isArray(params.values) ? params.values.join(',') : '';
    },
    valueSetter: (p: any) => {
      if (LOOKUP_EDITORS.has(p.data?.cellEditor)) return false;
      const val = (p.newValue || '').trim();
      if (!val) {
        setRulesConfigProp(p.data, 'cellEditorParams', null);
      } else {
        const values = val.split(',').map((s: string) => s.trim()).filter(Boolean);
        setRulesConfigProp(p.data, 'cellEditorParams', { values });
      }
      return true;
    }
  },
  { field: 'defaultValue', headerName: '默认值', width: 130, editable: true,
    cellEditor: 'agRichSelectCellEditor',
    cellEditorParams: {
      values: ['', '当前时间', '当前日期', '当前用户ID', '当前人员名称', '当前部门名称', '当前部门ID'],
      allowTyping: true,
      filterList: true
    },
    valueGetter: (p: any) => {
      const raw = p.data?.defaultValue;
      if (!raw) return '';
      try {
        const config = typeof raw === 'string' ? JSON.parse(raw) : raw;
        if (config.type === 'builtin') {
          const map: Record<string, string> = { currentTime: '当前时间', currentDate: '当前日期', currentUserId: '当前用户ID', currentUserName: '当前人员名称', currentDeptName: '当前部门名称', currentDeptId: '当前部门ID' };
          return map[config.value] || String(config.value);
        }
        return String(config.value || '');
      } catch { return String(raw); }
    },
    valueSetter: (p: any) => {
      const val = (p.newValue || '').trim();
      if (!val) { p.data.defaultValue = null; return true; }
      // 检查是否是固有对象
      const builtinMap: Record<string, string> = { '当前时间': 'currentTime', '当前日期': 'currentDate', '当前用户ID': 'currentUserId', '当前人员名称': 'currentUserName', '当前部门名称': 'currentDeptName', '当前部门ID': 'currentDeptId' };
      if (builtinMap[val]) {
        p.data.defaultValue = JSON.stringify({ type: 'builtin', value: builtinMap[val] });
      } else {
        p.data.defaultValue = JSON.stringify({ type: 'static', value: val });
      }
      return true;
    }
  },
  { field: 'displayOrder', headerName: '序号', width: 55, editable: false }
];

const defaultColDef: ColDef = { sortable: false, resizable: true, suppressHeaderMenuButton: true };
const rowSelection = { mode: 'multiRow' as const };

const addColumnTableColumns = [
  { type: 'selection' as const, multiple: true },
  { title: '字段名', key: 'columnName', width: 180 },
  { title: '标题', key: 'columnComment', width: 180 },
  { title: '类型', key: 'dataType', width: 120 },
  {
    title: '列类型',
    key: 'columnKind',
    width: 90,
    render: (row: any) => (row.isReal ? '真实列' : '虚拟列')
  }
];

// 行样式：虚拟列黄色背景，失效列红色背景
function getRowStyle(params: any) {
  if (!params.data) return undefined;
  if (params.data.isVirtual === 1) {
    return { background: '#fffbe6' }; // 黄色 - 虚拟列
  }
  if (params.data.deleted === 1) {
    return { background: '#fff1f0' }; // 红色 - 失效/已删除
  }
  return undefined;
}

// RULES_CONFIG JSON 读写工具
function getRulesConfigProp(row: any, key: string): any {
  if (!row?.rulesConfig) return null;
  try {
    const config = typeof row.rulesConfig === 'string' ? JSON.parse(row.rulesConfig) : row.rulesConfig;
    return config?.[key] ?? null;
  } catch { return null; }
}

function setRulesConfigProp(row: any, key: string, value: any) {
  let config: any = {};
  if (row.rulesConfig) {
    try { config = typeof row.rulesConfig === 'string' ? JSON.parse(row.rulesConfig) : row.rulesConfig; } catch { config = {}; }
  }
  if (value === null || value === '' || value === undefined) {
    delete config[key];
  } else {
    config[key] = value;
  }
  row.rulesConfig = Object.keys(config).length > 0 ? JSON.stringify(config) : null;
}

function getDbColumnName(column: any) {
  return column?.COLUMN_NAME || column?.columnName || '';
}

function getDbColumnComment(column: any) {
  return column?.COLUMN_COMMENT || column?.columnComment || column?.comment || getDbColumnName(column);
}

function getDbDataType(column: any) {
  return column?.DATA_TYPE || column?.dataType || '';
}

function buildTargetSet(targetCols: any[]) {
  return new Set((targetCols || []).map((c: any) => getDbColumnName(c).toUpperCase()).filter(Boolean));
}

function createColumnMetaFromViewColumn(table: any, viewColumn: any, displayOrder: number, targetSet: Set<string>) {
  const columnName = getDbColumnName(viewColumn);
  const isReal = targetSet.has(columnName.toUpperCase());
  return {
    _isNew: true,
    tableMetadataId: table.id,
    columnName,
    targetColumn: isReal ? columnName : '',
    headerText: getDbColumnComment(viewColumn),
    dataType: mapDataType(getDbDataType(viewColumn)),
    displayOrder,
    isVirtual: isReal ? 0 : 1,
    visible: 1,
    editable: isReal ? 1 : 0,
    searchable: 0,
    sortable: 1,
    filterable: 0
  };
}

function markColumnDirty(tableId: number, row: any) {
  if (!dirtyColumns.value[tableId]) dirtyColumns.value[tableId] = new Set();
  dirtyColumns.value[tableId].add(row);
}

// 找出主表和从表
const masterTable = computed(() => props.tables.find(t => !t.parentTableCode));
const detailTables = computed(() => props.tables.filter(t => t.parentTableCode));

async function loadColumns(tableId: number) {
  if (columnsByTable.value[tableId]) return;
  loadingTable.value[tableId] = true;
  try {
    const cols = await fetchColumnsByTableId(tableId);
    columnsByTable.value[tableId] = cols || [];
  } catch {
    message.error('加载列失败');
  } finally {
    loadingTable.value[tableId] = false;
  }
}

function handleCollapseChange(names: string | string[] | number | number[]) {
  const expanded = Array.isArray(names) ? names : [names];
  for (const name of expanded) {
    const tableId = Number(name);
    if (tableId > 0) loadColumns(tableId);
  }
}

function getTableLabel(table: any) {
  const comp = props.components.find((c: any) => c.refTableCode === table.tableCode);
  const type = comp?.componentType === 'DETAIL_GRID' ? '从表' : '主表';
  return `${type}: ${table.tableCode} (${table.tableName || ''})`;
}

function getTableSummary(table: any) {
  const cols = columnsByTable.value[table.id];
  return cols ? `${cols.length} 列` : '';
}

function markDirty(tableId: number, event: any) {
  if (!dirtyColumns.value[tableId]) {
    dirtyColumns.value[tableId] = new Set();
  }
  if (event.data) {
    dirtyColumns.value[tableId].add(event.data);
  }
}

function onGridReady(tableId: number, event: any) {
  gridApis.value[tableId] = event.api;
}

async function deleteSelectedColumns(tableId: number) {
  const api = gridApis.value[tableId];
  const selectedRows = api?.getSelectedRows?.() || [];
  if (selectedRows.length === 0) {
    message.warning('请选择要删除的列');
    return;
  }

  try {
    const persistedRows = selectedRows.filter((row: any) => row.id != null && !row._isNew);
    await Promise.all(persistedRows.map((row: any) => deleteColumnMeta(row.id)));

    const selectedSet = new Set(selectedRows);
    const remainingRows = (columnsByTable.value[tableId] || []).filter(row => !selectedSet.has(row));
    remainingRows.forEach((row, index) => {
      row.displayOrder = index + 1;
    });
    columnsByTable.value[tableId] = [...remainingRows];

    const dirty = dirtyColumns.value[tableId];
    if (dirty) {
      selectedRows.forEach((row: any) => dirty.delete(row));
      remainingRows.forEach(row => dirty.add(row));
    } else {
      dirtyColumns.value[tableId] = new Set(remainingRows);
    }

    message.success(`已删除 ${selectedRows.length} 列`);
  } catch (e: any) {
    message.error(e?.message || '删除失败');
  }
}

async function saveColumns(tableId: number) {
  const dirty = dirtyColumns.value[tableId];
  if (!dirty || dirty.size === 0) {
    message.info('没有需要保存的修改');
    return;
  }
  try {
    const rows = Array.from(dirty);
    await Promise.all(rows.map((row: any) => saveColumnMeta(row)));
    message.success(`已保存 ${rows.length} 列`);
    dirtyColumns.value[tableId] = new Set();
  } catch (e: any) {
    message.error(e?.message || '保存失败');
  }
}

async function saveTableMeta(table: any) {
  try {
    await saveTableMetaApi(table);
    message.success('表信息已保存');
  } catch (e: any) {
    message.error(e?.message || '保存失败');
  }
}

function onRowDragEnd(tableId: number, event: any) {
  const api = event.api;
  if (!api) return;
  const rows: any[] = [];
  api.forEachNode((node: any) => { if (node.data) rows.push(node.data); });
  rows.forEach((row, idx) => { row.displayOrder = idx + 1; });
  if (!dirtyColumns.value[tableId]) dirtyColumns.value[tableId] = new Set();
  rows.forEach(row => dirtyColumns.value[tableId].add(row));
  api.refreshCells({ force: true });
}

async function reimportColumns(table: any) {
  if (!table.queryView) {
    message.warning('请先配置视图名');
    return;
  }
  try {
    const viewCols = await fetchViewColumns(table.queryView);
    if (!viewCols || viewCols.length === 0) {
      message.error('视图未找到或无列');
      return;
    }
    // 获取目标表列用于对比虚拟/真实
    const targetCols = table.targetTable ? await fetchViewColumns(table.targetTable) : [];
    const targetSet = buildTargetSet(targetCols || []);

    const existingCols = columnsByTable.value[table.id] || [];
    const existingMap = new Map(existingCols.map((c: any) => [c.columnName?.toUpperCase(), c]));

    // 找出新列（视图中有但列元数据中没有的）
    let addedCount = 0;
    for (const vc of viewCols) {
      const colName = getDbColumnName(vc).toUpperCase();
      if (!colName || AUDIT_FIELDS.has(colName)) continue;
      if (existingMap.has(colName)) continue;
      const newCol = createColumnMetaFromViewColumn(table, vc, existingCols.length + addedCount + 1, targetSet);
      existingCols.push(newCol);
      addedCount++;
    }

    columnsByTable.value[table.id] = [...existingCols];
    if (addedCount > 0) {
      message.success(`发现 ${addedCount} 个新列，请确认后保存`);
      // 标记新列为脏
      existingCols.filter((c: any) => c._isNew).forEach((c: any) => markColumnDirty(table.id, c));
    } else {
      message.info('没有新列需要导入');
    }
  } catch (e: any) {
    message.error(e?.message || '导入失败');
  }
}

function mapDataType(oracleType: string): string {
  const upper = (oracleType || '').toUpperCase();
  if (upper.includes('NUMBER') || upper.includes('FLOAT')) return 'number';
  if (upper.includes('DATE') || upper.includes('TIMESTAMP')) return 'date';
  return 'text';
}

// ==================== 选择视图列添加 ====================
const showAddColumnModal = ref(false);
const addColumnLoading = ref(false);
const addColumnTable = ref<any>(null);
const availableViewColumns = ref<any[]>([]);
const selectedViewColumnKeys = ref<string[]>([]);
const addColumnTargetSet = ref<Set<string>>(new Set());

async function openAddColumnModal(table: any) {
  if (!table.queryView) {
    message.warning('请先配置视图名');
    return;
  }
  addColumnTable.value = table;
  selectedViewColumnKeys.value = [];
  availableViewColumns.value = [];
  addColumnLoading.value = true;
  showAddColumnModal.value = true;
  try {
    if (!columnsByTable.value[table.id]) {
      await loadColumns(table.id);
    }
    const viewCols = await fetchViewColumns(table.queryView);
    if (!viewCols || viewCols.length === 0) {
      message.error('视图未找到或无列');
      showAddColumnModal.value = false;
      return;
    }
    const targetCols = table.targetTable ? await fetchViewColumns(table.targetTable) : [];
    addColumnTargetSet.value = buildTargetSet(targetCols || []);
    const existingNames = new Set((columnsByTable.value[table.id] || []).map((c: any) => c.columnName?.toUpperCase()).filter(Boolean));
    availableViewColumns.value = viewCols
      .map((vc: any) => {
        const columnName = getDbColumnName(vc);
        const upperName = columnName.toUpperCase();
        return {
          raw: vc,
          key: upperName,
          columnName,
          columnComment: getDbColumnComment(vc),
          dataType: getDbDataType(vc),
          isReal: addColumnTargetSet.value.has(upperName)
        };
      })
      .filter((vc: any) => vc.columnName && !AUDIT_FIELDS.has(vc.key) && !existingNames.has(vc.key));
  } catch (e: any) {
    message.error(e?.message || '加载视图列失败');
    showAddColumnModal.value = false;
  } finally {
    addColumnLoading.value = false;
  }
}

function addSelectedViewColumns() {
  const table = addColumnTable.value;
  if (!table) return;
  if (selectedViewColumnKeys.value.length === 0) {
    message.warning('请选择要添加的列');
    return;
  }
  const existingCols = columnsByTable.value[table.id] || [];
  const selectedKeys = new Set(selectedViewColumnKeys.value);
  const selectedColumns = availableViewColumns.value.filter((vc: any) => selectedKeys.has(vc.key));
  selectedColumns.forEach((vc: any, index: number) => {
    const newCol = createColumnMetaFromViewColumn(table, vc.raw, existingCols.length + index + 1, addColumnTargetSet.value);
    existingCols.push(newCol);
    markColumnDirty(table.id, newCol);
  });
  columnsByTable.value[table.id] = [...existingCols];
  message.success(`已添加 ${selectedColumns.length} 列，请确认后保存`);
  showAddColumnModal.value = false;
}

// ==================== Lookup 配置弹窗 ====================
const showLookupEditor = ref(false);
const lookupEditingRow = ref<any>(null);
const lookupConfig = ref<any>({});
const lookupAvailableFields = ref<string[]>([]);

function openLookupEditor(row: any) {
  lookupEditingRow.value = row;
  lookupConfig.value = getRulesConfigProp(row, 'cellEditorParams') || {};
  // 收集当前表所有字段名作为 mapping 可选项
  const tableId = findTableIdForRow(row);
  if (tableId) {
    lookupAvailableFields.value = (columnsByTable.value[tableId] || []).map((c: any) => c.columnName);
  }
  showLookupEditor.value = true;
}

function onLookupSave(config: any) {
  if (!lookupEditingRow.value) return;
  const nextConfig = { ...config };
  if (lookupEditingRow.value.cellEditor === 'lookupMultiple') {
    nextConfig.multiple = true;
  } else {
    delete nextConfig.multiple;
  }
  setRulesConfigProp(lookupEditingRow.value, 'cellEditorParams', nextConfig);
  // 标记脏
  const tableId = findTableIdForRow(lookupEditingRow.value);
  if (tableId) {
    if (!dirtyColumns.value[tableId]) dirtyColumns.value[tableId] = new Set();
    dirtyColumns.value[tableId].add(lookupEditingRow.value);
  }
  showLookupEditor.value = false;
}

function findTableIdForRow(row: any): number | null {
  for (const [tableId, cols] of Object.entries(columnsByTable.value)) {
    if ((cols as any[]).includes(row)) return Number(tableId);
  }
  return null;
}
</script>

<template>
  <div class="section-tables">
    <NCollapse @update:expanded-names="handleCollapseChange">
      <!-- 主表 -->
      <NCollapseItem v-if="masterTable" :title="getTableLabel(masterTable)" :name="masterTable.id">
        <template #header-extra>
          <span class="col-count">{{ getTableSummary(masterTable) }}</span>
        </template>
        <NDescriptions size="small" :column="3" bordered class="table-meta">
          <NDescriptionsItem label="视图">
            <NAutoComplete
              v-model:value="masterTable.queryView"
              :options="dbObjectOptions"
              placeholder="搜索视图..."
              size="small"
              style="width: 220px"
              @update:value="searchDbObjects"
            />
          </NDescriptionsItem>
          <NDescriptionsItem label="目标表">
            <NAutoComplete
              v-model:value="masterTable.targetTable"
              :options="dbObjectOptions"
              placeholder="搜索表..."
              size="small"
              style="width: 220px"
              @update:value="searchDbObjects"
            />
          </NDescriptionsItem>
          <NDescriptionsItem label="PK">
            <NInput v-model:value="masterTable.pkColumn" size="small" style="width: 120px" />
          </NDescriptionsItem>
        </NDescriptions>
        <div class="table-actions">
          <NButton size="tiny" @click="saveTableMeta(masterTable)">保存表信息</NButton>
        </div>
        <div v-if="columnsByTable[masterTable.id]" class="columns-grid">
          <AgGridVue
            class="ag-theme-quartz"
            style="width: 100%"
            :style="{ height: Math.max(350, Math.min(600, (columnsByTable[masterTable.id]?.length || 5) * 35 + 50)) + 'px' }"
            :row-data="columnsByTable[masterTable.id]"
            :column-defs="columnDefs"
            :default-col-def="defaultColDef"
            :get-row-style="getRowStyle"
            :row-selection="rowSelection"
            :row-drag-managed="true"
            :animate-rows="true"
            @grid-ready="(e: any) => onGridReady(masterTable.id, e)"
            @cell-value-changed="(e: any) => markDirty(masterTable.id, e)"
            @row-drag-end="(e: any) => onRowDragEnd(masterTable.id, e)"
          />
          <div class="grid-actions">
            <NSpace size="small">
              <NButton size="small" @click="reimportColumns(masterTable)">从视图重新导入</NButton>
              <NButton size="small" @click="openAddColumnModal(masterTable)">选择视图列添加</NButton>
              <NButton size="small" type="error" @click="deleteSelectedColumns(masterTable.id)">删除选中列</NButton>
              <NButton size="small" type="primary" @click="saveColumns(masterTable.id)">保存列</NButton>
            </NSpace>
          </div>
        </div>
        <div v-else-if="loadingTable[masterTable.id]" class="loading-hint">加载中...</div>
      </NCollapseItem>

      <!-- 从表 -->
      <NCollapseItem v-for="detail in detailTables" :key="detail.id" :title="getTableLabel(detail)" :name="detail.id">
        <template #header-extra>
          <span class="col-count">FK: {{ detail.parentFkColumn }} | {{ getTableSummary(detail) }}</span>
        </template>
        <NDescriptions size="small" :column="3" bordered class="table-meta">
          <NDescriptionsItem label="视图">
            <NAutoComplete
              v-model:value="detail.queryView"
              :options="dbObjectOptions"
              placeholder="搜索视图..."
              size="small"
              style="width: 220px"
              @update:value="searchDbObjects"
            />
          </NDescriptionsItem>
          <NDescriptionsItem label="目标表">
            <NAutoComplete
              v-model:value="detail.targetTable"
              :options="dbObjectOptions"
              placeholder="搜索表..."
              size="small"
              style="width: 220px"
              @update:value="searchDbObjects"
            />
          </NDescriptionsItem>
          <NDescriptionsItem label="PK">
            <NInput v-model:value="detail.pkColumn" size="small" style="width: 120px" />
          </NDescriptionsItem>
        </NDescriptions>
        <div class="table-actions">
          <NButton size="tiny" @click="saveTableMeta(detail)">保存表信息</NButton>
        </div>
        <div v-if="columnsByTable[detail.id]" class="columns-grid">
          <AgGridVue
            class="ag-theme-quartz"
            style="width: 100%"
            :style="{ height: Math.max(250, Math.min(500, (columnsByTable[detail.id]?.length || 5) * 35 + 50)) + 'px' }"
            :row-data="columnsByTable[detail.id]"
            :column-defs="columnDefs"
            :default-col-def="defaultColDef"
            :get-row-style="getRowStyle"
            :row-selection="rowSelection"
            :row-drag-managed="true"
            :animate-rows="true"
            @grid-ready="(e: any) => onGridReady(detail.id, e)"
            @cell-value-changed="(e: any) => markDirty(detail.id, e)"
            @row-drag-end="(e: any) => onRowDragEnd(detail.id, e)"
          />
          <div class="grid-actions">
            <NSpace size="small">
              <NButton size="small" @click="reimportColumns(detail)">从视图重新导入</NButton>
              <NButton size="small" @click="openAddColumnModal(detail)">选择视图列添加</NButton>
              <NButton size="small" type="error" @click="deleteSelectedColumns(detail.id)">删除选中列</NButton>
              <NButton size="small" type="primary" @click="saveColumns(detail.id)">保存列</NButton>
            </NSpace>
          </div>
        </div>
        <div v-else-if="loadingTable[detail.id]" class="loading-hint">加载中...</div>
      </NCollapseItem>
    </NCollapse>

    <!-- Lookup 配置弹窗 -->
    <NModal v-model:show="showLookupEditor" preset="card" title="弹窗选择配置" :style="{ width: '650px' }">
      <LookupConfigEditor
        :config="lookupConfig"
        :available-fields="lookupAvailableFields"
        @save="onLookupSave"
        @close="showLookupEditor = false"
      />
    </NModal>

    <NModal
      v-model:show="showAddColumnModal"
      preset="card"
      title="选择视图列添加"
      :style="{ width: '760px' }"
    >
      <div class="add-column-modal">
        <div class="add-column-meta">
          {{ addColumnTable?.queryView || '' }}
        </div>
        <NDataTable
          v-model:checked-row-keys="selectedViewColumnKeys"
          :columns="addColumnTableColumns"
          :data="availableViewColumns"
          :loading="addColumnLoading"
          :row-key="(row: any) => row.key"
          size="small"
          max-height="420"
        />
        <div class="add-column-actions">
          <NSpace justify="end">
            <NButton size="small" @click="showAddColumnModal = false">取消</NButton>
            <NButton size="small" type="primary" @click="addSelectedViewColumns">添加选中列</NButton>
          </NSpace>
        </div>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.section-tables {
  padding: 8px 0;
}
.table-meta {
  margin-bottom: 8px;
}
.table-actions {
  margin-top: 4px;
  margin-bottom: 8px;
}
.columns-grid {
  margin-top: 8px;
}
.col-count {
  font-size: 12px;
  color: #999;
}
.loading-hint {
  padding: 12px;
  color: #999;
  font-size: 13px;
}
.grid-actions {
  margin-top: 8px;
  text-align: right;
}
.add-column-modal {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.add-column-meta {
  color: #666;
  font-size: 13px;
}
.add-column-actions {
  margin-top: 2px;
}
</style>
