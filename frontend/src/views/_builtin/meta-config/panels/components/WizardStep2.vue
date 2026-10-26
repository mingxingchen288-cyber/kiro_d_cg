<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NRadioGroup,
  NRadio,
  NSelect,
  NSpace,
  useMessage
} from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, GridApi } from 'ag-grid-community';
import { fetchViewColumns } from '@/service/api/meta-config';
import { fetchPkColumn } from '@/service/api/wizard';
import { classifyColumns, derivePageCode, deriveTableCode } from '../composables/useWizardState';
import type { WizardStep1State, WizardStep2State, WizardTableState } from '../composables/useWizardState';

const props = defineProps<{
  step1: WizardStep1State;
  step2: WizardStep2State;
}>();

const emit = defineEmits<{
  (e: 'modeChange'): void;
  (e: 'addDetail'): void;
  (e: 'removeDetail', index: number): void;
}>();

const message = useMessage();
const loadingMaster = ref(false);
const loadingDetails = ref<Record<number, boolean>>({});

// Column defs for the AG Grid column configuration
const columnDefs: ColDef[] = [
  { field: 'columnName', headerName: '字段名', width: 130, editable: false },
  { field: 'targetColumn', headerName: 'TARGET_COLUMN', width: 130, editable: true,
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: (params: any) => {
      // 获取当前行所属表的目标表列名列表作为选项
      const tableState = findTableStateForRow(params.data);
      if (!tableState) return { values: [] };
      const cached = targetColumnCache.value.get(tableState.targetTable.toUpperCase());
      const values = cached ? ['', ...Array.from(cached)] : [''];
      return { values };
    }
  },
  { field: 'headerText', headerName: '标题', width: 130, editable: true },
  {
    field: 'dataType',
    headerName: '数据类型',
    width: 100,
    editable: true,
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: ['text', 'number', 'date'] }
  },
  {
    field: 'isVirtual',
    headerName: '真实/虚拟',
    width: 90,
    editable: false,
    valueFormatter: (p: any) => (p.value === 0 ? '真实' : '虚拟')
  },
  {
    field: 'visible',
    headerName: '显示',
    width: 70,
    editable: true,
    cellEditor: 'agCheckboxCellEditor',
    cellRenderer: 'agCheckboxCellRenderer'
  },
  {
    field: 'editable',
    headerName: '编辑',
    width: 70,
    editable: true,
    cellEditor: 'agCheckboxCellEditor',
    cellRenderer: 'agCheckboxCellRenderer'
  },
  {
    field: 'filterable',
    headerName: '查询',
    width: 70,
    editable: true,
    cellEditor: 'agCheckboxCellEditor',
    cellRenderer: 'agCheckboxCellRenderer'
  },
  {
    field: 'widgetType',
    headerName: '控件',
    width: 100,
    editable: true,
    cellEditor: 'agSelectCellEditor',
    cellEditorParams: { values: ['text', 'number', 'date', 'select', 'checkbox'] }
  },
  { field: 'displayOrder', headerName: '排序', width: 70, editable: true, cellDataType: 'number' }
];

const defaultColDef: ColDef = { sortable: true, resizable: true, suppressHeaderMenuButton: true };

// 缓存每个表的目标表列名集合，用于 TARGET_COLUMN 校验
const targetColumnCache = ref<Map<string, Set<string>>>(new Map());

// Load columns for a table state (master or detail)
async function loadTableColumns(tableState: WizardTableState) {
  if (!tableState.queryView || !tableState.targetTable) return;

  try {
    // Fetch view columns
    const viewCols = await fetchViewColumns(tableState.queryView);
    if (!viewCols || viewCols.length === 0) {
      message.error(`视图 ${tableState.queryView} 未找到或无列`);
      return;
    }

    // Fetch target table columns
    const targetCols = await fetchViewColumns(tableState.targetTable);
    if (!targetCols || targetCols.length === 0) {
      message.error(`目标表 ${tableState.targetTable} 未找到或无列`);
      return;
    }

    // Cache target column names for validation
    const targetColumnNames = targetCols.map((c: any) => (c.COLUMN_NAME || c.columnName || '').toUpperCase());
    const targetColSet = new Set(targetColumnNames);
    targetColumnCache.value.set(tableState.targetTable.toUpperCase(), targetColSet);

    // 校验目标表必须包含审计字段
    const AUDIT_FIELDS = ['DELETED', 'CREATE_TIME', 'UPDATE_TIME', 'CREATE_BY', 'UPDATE_BY'];
    const missingAudit = AUDIT_FIELDS.filter(f => !targetColSet.has(f));
    if (missingAudit.length > 0) {
      message.error(`目标表 ${tableState.targetTable} 缺少审计字段: ${missingAudit.join(', ')}，请先补充后再引入`);
      return;
    }

    // 校验视图必须暴露 DELETED 字段（动态查询需要 a.DELETED = 0）
    const viewColNames = new Set(viewCols.map((c: any) => (c.COLUMN_NAME || c.columnName || '').toUpperCase()));
    if (!viewColNames.has('DELETED')) {
      message.error(`视图 ${tableState.queryView} 未暴露 DELETED 字段，动态查询将无法正常工作，请先在视图中加入 DELETED 列`);
      return;
    }

    // Fetch PK column
    const pk = await fetchPkColumn(tableState.targetTable);
    if (!pk) {
      message.error(`目标表 ${tableState.targetTable} 缺少主键定义`);
      return;
    }
    tableState.pkColumn = pk;

    // Auto-derive sequenceName and tableCode
    tableState.sequenceName = `SEQ_${tableState.targetTable.toUpperCase()}`;
    if (!tableState.tableCode) {
      tableState.tableCode = deriveTableCode(tableState.targetTable);
    }
    // 提示用户序列情况（后端生成时会自动创建不存在的序列）
    message.info(`序列 ${tableState.sequenceName} 若不存在，系统将在生成时自动创建`);

    // Classify columns (过滤掉审计字段，不引入到列配置中)
    const AUDIT_FIELD_SET = new Set(['DELETED', 'CREATE_TIME', 'UPDATE_TIME', 'CREATE_BY', 'UPDATE_BY']);
    const viewColumnData = viewCols
      .map((c: any) => ({
        columnName: c.COLUMN_NAME || c.columnName || '',
        dataType: c.DATA_TYPE || c.dataType || 'VARCHAR2',
        comment: c.COLUMN_COMMENT || c.comment || ''
      }))
      .filter((c: any) => !AUDIT_FIELD_SET.has(c.columnName.toUpperCase()));

    tableState.columns = classifyColumns(viewColumnData, targetColumnNames);
    tableState.columnsLoaded = true;
  } catch (e: any) {
    message.error(e?.message || '加载列信息失败');
  }
}

async function loadMasterColumns() {
  loadingMaster.value = true;
  await loadTableColumns(props.step2.masterTable);
  // Auto-derive pageCode
  if (!props.step2.pageCode) {
    props.step2.pageCode = derivePageCode(props.step2.masterTable.queryView, props.step1.resourceCode);
  }
  loadingMaster.value = false;
}

async function loadDetailColumns(index: number) {
  loadingDetails.value[index] = true;
  const detail = props.step2.detailTables[index];
  await loadTableColumns(detail);
  // Auto-infer FK: check if detail has column matching master PK
  if (detail.columnsLoaded && props.step2.masterTable.pkColumn) {
    const masterPk = props.step2.masterTable.pkColumn.toUpperCase();
    const match = detail.columns.find(c => c.columnName.toUpperCase() === masterPk);
    if (match && !detail.parentFkColumn) {
      detail.parentFkColumn = match.columnName;
    }
  }
  loadingDetails.value[index] = false;
}

// FK column options for detail tables
function getFkOptions(detail: WizardTableState) {
  if (!detail.columns || detail.columns.length === 0) return [];
  return detail.columns.map(c => ({ label: c.columnName, value: c.columnName }));
}

// 根据行数据找到所属的 TableState（用于 TARGET_COLUMN 下拉选项）
function findTableStateForRow(_rowData: any): WizardTableState | null {
  // AG Grid 的列配置是直接引用 tableState.columns 数组的元素
  // 先检查主表
  if (props.step2.masterTable.columns.includes(_rowData)) {
    return props.step2.masterTable;
  }
  // 再检查从表
  for (const detail of props.step2.detailTables) {
    if (detail.columns.includes(_rowData)) {
      return detail;
    }
  }
  return props.step2.masterTable; // fallback
}

function handleModeChange(mode: 'single' | 'master-detail') {
  props.step2.mode = mode;
  emit('modeChange');
}
</script>

<template>
  <div class="wizard-step2">
    <!-- Mode selection -->
    <NForm label-placement="left" label-width="100px">
      <NFormItem label="页面模式">
        <NRadioGroup :value="step2.mode" @update:value="handleModeChange">
          <NRadio value="single">单表</NRadio>
          <NRadio value="master-detail">主从</NRadio>
        </NRadioGroup>
      </NFormItem>
    </NForm>

    <!-- Master table config -->
    <div class="table-section">
      <h4 class="section-title">{{ step2.mode === 'single' ? '表配置' : '主表配置' }}</h4>
      <NForm label-placement="left" label-width="100px" inline>
        <NFormItem label="视图名">
          <NInput v-model:value="step2.masterTable.queryView" placeholder="如 V_COST_PINGGU" style="width: 200px" />
        </NFormItem>
        <NFormItem label="目标表">
          <NInput v-model:value="step2.masterTable.targetTable" placeholder="如 T_COST_PINGGU" style="width: 200px" />
        </NFormItem>
        <NFormItem label="表名称">
          <NInput v-model:value="step2.masterTable.tableName" placeholder="中文名" style="width: 150px" />
        </NFormItem>
        <NFormItem>
          <NButton type="primary" size="small" :loading="loadingMaster" @click="loadMasterColumns">
            导入列
          </NButton>
        </NFormItem>
      </NForm>

      <!-- Master columns grid -->
      <div v-if="step2.masterTable.columnsLoaded" class="columns-grid">
        <AgGridVue
          class="ag-theme-quartz"
          style="width: 100%; height: 300px"
          :row-data="step2.masterTable.columns"
          :column-defs="columnDefs"
          :default-col-def="defaultColDef"
          :suppress-scroll-on-new-data="true"
        />
      </div>
    </div>

    <!-- Detail tables (master-detail mode) -->
    <template v-if="step2.mode === 'master-detail'">
      <div v-for="(detail, idx) in step2.detailTables" :key="idx" class="table-section">
        <div class="section-header">
          <h4 class="section-title">从表 {{ idx + 1 }}</h4>
          <NButton v-if="step2.detailTables.length > 1" size="tiny" type="error" quaternary @click="emit('removeDetail', idx)">
            移除
          </NButton>
        </div>
        <NForm label-placement="left" label-width="100px" inline>
          <NFormItem label="视图名">
            <NInput v-model:value="detail.queryView" placeholder="从表视图" style="width: 200px" />
          </NFormItem>
          <NFormItem label="目标表">
            <NInput v-model:value="detail.targetTable" placeholder="从表目标表" style="width: 200px" />
          </NFormItem>
          <NFormItem label="表名称">
            <NInput v-model:value="detail.tableName" placeholder="从表中文名" style="width: 150px" />
          </NFormItem>
          <NFormItem>
            <NButton size="small" :loading="loadingDetails[idx]" @click="loadDetailColumns(idx)">
              导入列
            </NButton>
          </NFormItem>
        </NForm>

        <!-- FK selection -->
        <NForm v-if="detail.columnsLoaded" label-placement="left" label-width="100px" inline>
          <NFormItem label="关联字段" :validation-status="!detail.parentFkColumn ? 'error' : undefined" :feedback="!detail.parentFkColumn ? '请选择关联字段' : ''">
            <NSelect
              v-model:value="detail.parentFkColumn"
              :options="getFkOptions(detail)"
              placeholder="选择从表关联字段"
              style="width: 200px"
            />
          </NFormItem>
          <NFormItem label="主表PK">
            <NInput :value="step2.masterTable.pkColumn" disabled style="width: 150px" />
          </NFormItem>
        </NForm>

        <!-- Detail columns grid -->
        <div v-if="detail.columnsLoaded" class="columns-grid">
          <AgGridVue
            class="ag-theme-quartz"
            style="width: 100%; height: 250px"
            :row-data="detail.columns"
            :column-defs="columnDefs"
            :default-col-def="defaultColDef"
            :suppress-scroll-on-new-data="true"
          />
        </div>
      </div>

      <!-- Add detail button -->
      <NButton v-if="step2.detailTables.length < 5" size="small" dashed @click="emit('addDetail')">
        + 添加从表
      </NButton>
      <span v-if="step2.detailTables.length >= 5" class="warning-text">
        从表数量较多，建议拆分为多个页面
      </span>
    </template>
  </div>
</template>

<style scoped>
.wizard-step2 {
  padding: 8px 0;
}
.table-section {
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid #e8e8e8;
  border-radius: 6px;
}
.section-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 500;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.columns-grid {
  margin-top: 8px;
}
.warning-text {
  color: #f0a020;
  font-size: 12px;
  margin-left: 8px;
}
</style>
