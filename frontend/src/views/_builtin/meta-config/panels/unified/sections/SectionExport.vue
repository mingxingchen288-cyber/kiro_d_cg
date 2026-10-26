<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue';
import type { DataTableColumns } from 'naive-ui';
import {
  NButton,
  NDataTable,
  NDivider,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  useMessage
} from 'naive-ui';
import {
  deleteExportConfig,
  deleteExportConfigDetail,
  fetchAllExportConfigs,
  fetchExportConfigDetails,
  saveExportConfig,
  saveExportConfigDetail
} from '@/service/api/meta-config';

type ExportConfigRow = {
  id?: number | null;
  pageCode: string;
  exportCode: string;
  exportName: string;
  masterSql: string;
  masterTableAlias: string;
  pkColumn: string;
  pageViewAlias: string;
  pageFkColumn: string;
  masterLinkColumn: string;
  columns: string;
  masterSheetName: string;
  fontName: string;
  displayOrder: number | null;
  deleted?: number;
};

type ExportDetailRow = {
  _localKey: string;
  id?: number | null;
  exportConfigId?: number | null;
  tabKey: string;
  sheetName: string;
  detailSql: string;
  masterTableAlias: string;
  detailTableAlias: string;
  detailLinkColumn: string;
  columns: string;
  displayOrder: number | null;
};

type TableMetaRow = Record<string, any>;
type ComponentRow = Record<string, any>;

const props = defineProps<{
  pageCode: string;
  tables: TableMetaRow[];
  components: ComponentRow[];
}>();

const message = useMessage();
const configs = ref<ExportConfigRow[]>([]);
const loading = ref(false);

const editorVisible = ref(false);
const editorSaving = ref(false);
const detailLoading = ref(false);
const editingConfig = ref<ExportConfigRow>({
  id: null,
  pageCode: props.pageCode,
  exportCode: '',
  exportName: '',
  masterSql: '',
  masterTableAlias: 'm',
  pkColumn: '',
  pageViewAlias: 'p',
  pageFkColumn: '',
  masterLinkColumn: '',
  columns: '[]',
  masterSheetName: '主表',
  fontName: 'Calibri',
  displayOrder: null,
  deleted: 0
});
const detailRows = ref<ExportDetailRow[]>([]);
const deletedDetailIds = ref<number[]>([]);

let detailKeySeed = 0;

const detailEditorVisible = ref(false);
const detailEditingIndex = ref(-1);
const detailForm = ref<ExportDetailRow>({
  _localKey: 'draft',
  id: null,
  exportConfigId: null,
  tabKey: '',
  sheetName: '',
  detailSql: '',
  masterTableAlias: 'm',
  detailTableAlias: '',
  detailLinkColumn: '',
  columns: '[]',
  displayOrder: null
});

const editorTitle = computed(() => {
  const name = normalizeText(editingConfig.value.exportName);
  return name ? `导出配置：${name}` : '新增导出配置';
});

const detailEditorTitle = computed(() => (detailEditingIndex.value >= 0 ? '编辑导出明细' : '新增导出明细'));

const masterTable = computed(() => props.tables.find(table => !normalizeText(table.parentTableCode)) || props.tables[0] || null);

const detailTables = computed(() => props.tables.filter(table => normalizeText(table.parentTableCode)));

const fontOptions = [
  { label: 'Calibri', value: 'Calibri' },
  { label: 'Arial', value: 'Arial' },
  { label: 'Times New Roman', value: 'Times New Roman' },
  { label: 'Microsoft YaHei', value: 'Microsoft YaHei' },
  { label: 'SimSun', value: 'SimSun' },
  { label: 'SimHei', value: 'SimHei' },
  { label: 'DengXian', value: 'DengXian' }
];

const detailSourceOptions = computed(() =>
  detailTables.value.map(table => {
    const component = findDetailComponent(table);
    const tabKey = normalizeText(component?.componentKey) || normalizeText(table.tableCode);
    const label = normalizeText(table.tableName)
      ? `${table.tableName}（${table.tableCode || tabKey}）`
      : normalizeText(table.tableCode) || tabKey;

    return {
      label,
      value: tabKey,
      table
    };
  })
);

const columns: DataTableColumns<ExportConfigRow> = [
  {
    title: '导出名称',
    key: 'exportName',
    minWidth: 180,
    render: row =>
      h(
        NButton,
        {
          text: true,
          type: 'primary',
          size: 'small',
          onClick: () => openEditor(row)
        },
        { default: () => row.exportName || '未命名导出' }
      )
  },
  { title: '导出编码', key: 'exportCode', minWidth: 180 },
  { title: '主表Sheet', key: 'masterSheetName', minWidth: 150 },
  {
    title: '字体',
    key: 'fontName',
    minWidth: 120,
    render: row => row.fontName || 'Calibri'
  },
  {
    title: '排序',
    key: 'displayOrder',
    width: 70,
    align: 'center'
  },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    align: 'center',
    render: row =>
      h(
        NPopconfirm,
        {
          onPositiveClick: () => removeConfig(row)
        },
        {
          trigger: () =>
            h(
              NButton,
              {
                text: true,
                type: 'error',
                size: 'small'
              },
              { default: () => '删除' }
            ),
          default: () => `确定删除导出“${row.exportName || row.exportCode || row.id}”？`
        }
      )
  }
];

const detailColumns: DataTableColumns<ExportDetailRow> = [
  { title: 'Sheet名称', key: 'sheetName', minWidth: 150 },
  { title: 'tabKey', key: 'tabKey', minWidth: 130 },
  { title: '关联列', key: 'detailLinkColumn', minWidth: 130 },
  {
    title: '列配置',
    key: 'columns',
    minWidth: 120,
    render: row => summarizeJson(row.columns, '未配置')
  },
  {
    title: '明细SQL',
    key: 'detailSql',
    minWidth: 220,
    ellipsis: { tooltip: true },
    render: row => summarizeText(row.detailSql, '未配置')
  },
  {
    title: '排序',
    key: 'displayOrder',
    width: 70,
    align: 'center'
  },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    align: 'center',
    render: (row, index) =>
      h(
        NSpace,
        { size: 10, justify: 'center' },
        {
          default: () => [
            h(
              NButton,
              {
                text: true,
                type: 'primary',
                size: 'small',
                onClick: () => openDetailEditor(row, index)
              },
              { default: () => '编辑' }
            ),
            h(
              NPopconfirm,
              {
                onPositiveClick: () => removeDetail(row, index)
              },
              {
                trigger: () =>
                  h(
                    NButton,
                    {
                      text: true,
                      type: 'error',
                      size: 'small'
                    },
                    { default: () => '删除' }
                  ),
                default: () => `确定删除明细“${row.sheetName || row.tabKey || index + 1}”？`
              }
            )
          ]
        }
      )
  }
];

function normalizeText(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function toText(value: unknown, fallback = '') {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
}

function toNumber(value: unknown, fallback: number | null) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function summarizeText(value: unknown, emptyLabel = '-') {
  const text = normalizeText(value);
  if (!text) return emptyLabel;
  return text.length > 70 ? `${text.slice(0, 70)}...` : text;
}

function summarizeJson(value: unknown, emptyLabel = '-') {
  const text = normalizeText(value);
  if (!text) return emptyLabel;
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return `${parsed.length} 列`;
    if (parsed && typeof parsed === 'object') return `${Object.keys(parsed).length} 项`;
  } catch {
    // show the raw summary below
  }
  return summarizeText(text, emptyLabel);
}

function findDetailComponent(table: TableMetaRow) {
  const tableCode = normalizeText(table.tableCode);
  return props.components.find(
    component => component.componentType === 'DETAIL_GRID' && normalizeText(component.refTableCode) === tableCode
  );
}

function getObjectName(table: TableMetaRow | null | undefined) {
  return (
    normalizeText(table?.queryView) ||
    normalizeText(table?.targetTable) ||
    normalizeText(table?.tableCode) ||
    ''
  );
}

function getTableLabel(table: TableMetaRow | null | undefined, fallback: string) {
  return normalizeText(table?.tableName) || normalizeText(table?.tableCode) || fallback;
}

function getMasterPkColumn() {
  return (
    normalizeText(masterTable.value?.pkColumn) ||
    normalizeText(detailTables.value[0]?.parentFkColumn) ||
    'DOCID'
  );
}

function getDetailRelationColumn(table: TableMetaRow | null | undefined) {
  return normalizeText(table?.parentFkColumn) || getMasterPkColumn();
}

function buildDefaultSql(table: TableMetaRow | null | undefined, alias = 'm') {
  const objectName = getObjectName(table);
  if (!objectName) return '';
  return `SELECT ${alias}.* FROM ${objectName} ${alias} WHERE ${alias}.DELETED = 0`;
}

function inferAliasFromSql(sql: string) {
  const text = normalizeText(sql);
  if (!text) return '';

  const match = /\bfrom\s+[\w.$"]+\s+("[^"]+"|[\w$#]+)/i.exec(text);
  const alias = match?.[1]?.replace(/^"|"$/g, '') || '';
  const reservedWords = new Set(['WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'FULL', 'ORDER', 'GROUP']);
  return alias && !reservedWords.has(alias.toUpperCase()) ? alias : '';
}

function findDetailOption(tabKey: string) {
  return detailSourceOptions.value.find(option => option.value === tabKey) || null;
}

function findFirstAvailableDetailOption() {
  const usedKeys = new Set(detailRows.value.map(row => normalizeText(row.tabKey)).filter(Boolean));
  return detailSourceOptions.value.find(option => !usedKeys.has(option.value)) || detailSourceOptions.value[0] || null;
}

function applyAutoConfig(config: ExportConfigRow): ExportConfigRow {
  const pkColumn = getMasterPkColumn();
  const masterAlias = inferAliasFromSql(config.masterSql) || 'm';

  return {
    ...config,
    pageCode: props.pageCode,
    masterTableAlias: masterAlias,
    pkColumn,
    pageViewAlias: 'p',
    pageFkColumn: pkColumn,
    masterLinkColumn: pkColumn,
    fontName: normalizeText(config.fontName) || 'Calibri',
    columns: normalizeText(config.columns) || '[]'
  };
}

function applyDetailSourceDefaults(row: ExportDetailRow, tabKey: string, force = false): ExportDetailRow {
  const option = findDetailOption(tabKey);
  if (!option) return row;

  const detailAlias = inferAliasFromSql(row.detailSql) || 'm';
  const nextSheetName = getTableLabel(option.table, row.sheetName || '明细');
  const nextSql = buildDefaultSql(option.table, detailAlias);

  return {
    ...row,
    tabKey: option.value,
    sheetName: force || !normalizeText(row.sheetName) ? nextSheetName : row.sheetName,
    detailLinkColumn: force || !normalizeText(row.detailLinkColumn) ? getDetailRelationColumn(option.table) : row.detailLinkColumn,
    detailSql: force || !normalizeText(row.detailSql) ? nextSql : row.detailSql
  };
}

function nextDetailKey() {
  detailKeySeed += 1;
  return `new-${detailKeySeed}`;
}

function createEmptyConfig(): ExportConfigRow {
  const pkColumn = getMasterPkColumn();
  return {
    id: null,
    pageCode: props?.pageCode || '',
    exportCode: '',
    exportName: '',
    masterSql: buildDefaultSql(masterTable.value),
    masterTableAlias: 'm',
    pkColumn,
    pageViewAlias: 'p',
    pageFkColumn: pkColumn,
    masterLinkColumn: pkColumn,
    columns: '[]',
    masterSheetName: getTableLabel(masterTable.value, '主表'),
    fontName: 'Calibri',
    displayOrder: configs.value.length + 1,
    deleted: 0
  };
}

function createEmptyDetail(): ExportDetailRow {
  const option = findFirstAvailableDetailOption();
  const row = {
    _localKey: nextDetailKey(),
    id: null,
    exportConfigId: editingConfig.value.id || null,
    tabKey: option?.value || '',
    sheetName: option ? getTableLabel(option.table, '明细') : '',
    detailSql: option ? buildDefaultSql(option.table) : '',
    masterTableAlias: editingConfig.value.masterTableAlias || 'm',
    detailTableAlias: '',
    detailLinkColumn: option ? getDetailRelationColumn(option.table) : getMasterPkColumn(),
    columns: '[]',
    displayOrder: detailRows.value.length + 1
  };

  return option ? applyDetailSourceDefaults(row, option.value) : row;
}

function normalizeConfig(row: Partial<ExportConfigRow> = {}): ExportConfigRow {
  return {
    id: row.id ?? null,
    pageCode: props.pageCode,
    exportCode: toText(row.exportCode),
    exportName: toText(row.exportName),
    masterSql: toText(row.masterSql),
    masterTableAlias: toText(row.masterTableAlias, 'm'),
    pkColumn: toText(row.pkColumn),
    pageViewAlias: toText(row.pageViewAlias, 'p'),
    pageFkColumn: toText(row.pageFkColumn),
    masterLinkColumn: toText(row.masterLinkColumn),
    columns: toText(row.columns, '[]'),
    masterSheetName: toText(row.masterSheetName, '主表'),
    fontName: toText(row.fontName, 'Calibri'),
    displayOrder: row.displayOrder ?? null,
    deleted: row.deleted ?? 0
  };
}

function normalizeDetail(row: Partial<ExportDetailRow> = {}): ExportDetailRow {
  return {
    _localKey: row._localKey || (row.id ? `id-${row.id}` : nextDetailKey()),
    id: row.id ?? null,
    exportConfigId: row.exportConfigId ?? editingConfig.value.id ?? null,
    tabKey: toText(row.tabKey),
    sheetName: toText(row.sheetName),
    detailSql: toText(row.detailSql),
    masterTableAlias: toText(row.masterTableAlias, editingConfig.value.masterTableAlias || 'm'),
    detailTableAlias: toText(row.detailTableAlias),
    detailLinkColumn: toText(row.detailLinkColumn),
    columns: toText(row.columns, '[]'),
    displayOrder: row.displayOrder ?? null
  };
}

function sortConfigs(rows: ExportConfigRow[]) {
  return [...rows].sort((a, b) => {
    const orderDiff = (a.displayOrder ?? 0) - (b.displayOrder ?? 0);
    if (orderDiff !== 0) return orderDiff;
    return (a.id ?? 0) - (b.id ?? 0);
  });
}

async function loadConfigs() {
  loading.value = true;
  try {
    const all = await fetchAllExportConfigs();
    configs.value = sortConfigs((all || []).filter((item: any) => item.pageCode === props.pageCode).map(normalizeConfig));
  } catch (e: any) {
    message.error(e?.message || '加载导出配置失败');
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editingConfig.value = createEmptyConfig();
  detailRows.value = [];
  deletedDetailIds.value = [];
  detailLoading.value = false;
  editorVisible.value = true;
}

async function openEditor(row: ExportConfigRow) {
  editingConfig.value = normalizeConfig(row);
  detailRows.value = [];
  deletedDetailIds.value = [];
  editorVisible.value = true;

  if (!row.id) return;
  detailLoading.value = true;
  try {
    const details = await fetchExportConfigDetails(row.id);
    detailRows.value = (details || []).map(normalizeDetail);
  } catch (e: any) {
    message.error(e?.message || '加载导出明细失败');
  } finally {
    detailLoading.value = false;
  }
}

async function removeConfig(row: ExportConfigRow) {
  if (!row.id) return;
  try {
    await deleteExportConfig(row.id);
    message.success('删除导出成功');
    await loadConfigs();
  } catch (e: any) {
    message.error(e?.message || '删除导出失败');
  }
}

function openDetailEditor(row?: ExportDetailRow, index = -1) {
  detailEditingIndex.value = index;
  detailForm.value = normalizeDetail(row || createEmptyDetail());
  detailEditorVisible.value = true;
}

function handleDetailSourceChange(tabKey: string | number | null) {
  detailForm.value = applyDetailSourceDefaults(detailForm.value, tabKey == null ? '' : String(tabKey), true);
}

function validateDetail(row: ExportDetailRow) {
  if (!normalizeText(row.sheetName)) {
    message.warning('明细 Sheet 名称不能为空');
    return false;
  }
  if (!normalizeText(row.detailSql)) {
    message.warning('明细 SQL 不能为空');
    return false;
  }
  return true;
}

function confirmDetailEdit() {
  const nextRow = normalizeDetail(detailForm.value);
  if (!validateDetail(nextRow)) return;

  if (detailEditingIndex.value >= 0) {
    detailRows.value.splice(detailEditingIndex.value, 1, nextRow);
  } else {
    detailRows.value.push(nextRow);
  }
  detailRows.value = detailRows.value.map((row, index) => ({
    ...row,
    displayOrder: row.displayOrder ?? index + 1
  }));
  detailEditorVisible.value = false;
}

function removeDetail(row: ExportDetailRow, index: number) {
  if (row.id) deletedDetailIds.value.push(row.id);
  detailRows.value.splice(index, 1);
  detailRows.value = detailRows.value.map((item, itemIndex) => ({
    ...item,
    displayOrder: item.displayOrder ?? itemIndex + 1
  }));
}

function validateConfig(config: ExportConfigRow) {
  if (!normalizeText(config.exportName)) {
    message.warning('导出名称不能为空');
    return false;
  }
  if (!normalizeText(config.exportCode)) {
    message.warning('导出编码不能为空');
    return false;
  }
  if (!normalizeText(config.masterSheetName)) {
    message.warning('主表 Sheet 不能为空');
    return false;
  }
  if (!normalizeText(config.masterSql)) {
    message.warning('主表 SQL 不能为空');
    return false;
  }
  return true;
}

function buildConfigPayload(config: ExportConfigRow) {
  const autoConfig = applyAutoConfig(config);
  return {
    ...autoConfig,
    pageCode: props.pageCode,
    displayOrder: autoConfig.displayOrder ?? 0,
    deleted: autoConfig.deleted ?? 0
  };
}

function buildDetailPayload(row: ExportDetailRow, exportConfigId: number, config: ExportConfigRow) {
  const normalizedRow = normalizeDetail(row);
  const detailAlias = inferAliasFromSql(normalizedRow.detailSql) || config.masterTableAlias || 'm';
  const { _localKey, ...payload } = {
    ...normalizedRow,
    masterTableAlias: detailAlias,
    detailTableAlias: normalizedRow.detailTableAlias || detailAlias,
    detailLinkColumn: normalizeText(normalizedRow.detailLinkColumn) || config.masterLinkColumn || config.pkColumn
  };

  return {
    ...payload,
    exportConfigId,
    displayOrder: payload.displayOrder ?? 0
  };
}

async function saveEditor() {
  const config = applyAutoConfig(normalizeConfig(editingConfig.value));
  if (!validateConfig(config)) return;

  const invalidDetail = detailRows.value.find(row => !validateDetail(row));
  if (invalidDetail) return;

  editorSaving.value = true;
  try {
    const savedConfig = await saveExportConfig(buildConfigPayload(config));
    const exportConfigId = toNumber(savedConfig?.id ?? config.id, null);
    if (!exportConfigId) {
      message.error('保存导出失败：未返回导出配置 ID');
      return;
    }

    await Promise.all([...new Set(deletedDetailIds.value)].map(id => deleteExportConfigDetail(id)));
    await Promise.all(
      detailRows.value.map((row, index) =>
        saveExportConfigDetail(
          buildDetailPayload(
            {
              ...row,
              displayOrder: row.displayOrder ?? index + 1
            },
            exportConfigId,
            config
          )
        )
      )
    );

    message.success('导出配置已保存');
    editorVisible.value = false;
    await loadConfigs();
  } catch (e: any) {
    message.error(e?.message || '保存导出配置失败');
  } finally {
    editorSaving.value = false;
  }
}

watch(
  () => props.pageCode,
  () => {
    loadConfigs();
  }
);

onMounted(loadConfigs);
</script>

<template>
  <div class="section-export">
    <div class="export-toolbar">
      <NSpace size="small">
        <NButton size="small" type="primary" @click="openCreate">新增导出</NButton>
        <NButton size="small" quaternary :loading="loading" @click="loadConfigs">刷新</NButton>
      </NSpace>
    </div>

    <NDataTable
      :columns="columns"
      :data="configs"
      :row-key="(row: ExportConfigRow) => row.id || row.exportCode"
      size="small"
      :bordered="false"
      :loading="loading"
      :pagination="false"
    />

    <p v-if="!loading && configs.length === 0" class="empty-hint">暂无导出配置</p>

    <NModal
      v-model:show="editorVisible"
      preset="card"
      :title="editorTitle"
      :style="{ width: '1080px', maxWidth: 'calc(100vw - 48px)' }"
      :body-style="{ maxHeight: '78vh', overflow: 'auto' }"
      :mask-closable="false"
    >
      <div class="editor-body">
        <NForm label-placement="top" size="small">
          <NGrid :cols="3" :x-gap="12" :y-gap="4">
            <NGridItem>
              <NFormItem label="页面编码">
                <NInput :value="pageCode" disabled />
              </NFormItem>
            </NGridItem>
            <NGridItem>
              <NFormItem label="导出名称">
                <NInput v-model:value="editingConfig.exportName" placeholder="例如：物料成本核算表导出" />
              </NFormItem>
            </NGridItem>
            <NGridItem>
              <NFormItem label="导出编码">
                <NInput v-model:value="editingConfig.exportCode" placeholder="例如：cost-pinggu-export" />
              </NFormItem>
            </NGridItem>
            <NGridItem>
              <NFormItem label="主表 Sheet">
                <NInput v-model:value="editingConfig.masterSheetName" />
              </NFormItem>
            </NGridItem>
            <NGridItem>
              <NFormItem label="排序">
                <NInputNumber v-model:value="editingConfig.displayOrder" :min="0" style="width: 100%" />
              </NFormItem>
            </NGridItem>
            <NGridItem>
              <NFormItem label="导出字体">
                <NSelect
                  v-model:value="editingConfig.fontName"
                  :options="fontOptions"
                  filterable
                  tag
                  placeholder="Calibri"
                />
              </NFormItem>
            </NGridItem>
            <NGridItem :span="3">
              <NFormItem label="主表列配置(JSON)">
                <NInput v-model:value="editingConfig.columns" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
              </NFormItem>
            </NGridItem>
            <NGridItem :span="3">
              <NFormItem label="主表 SQL">
                <NInput v-model:value="editingConfig.masterSql" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" />
              </NFormItem>
            </NGridItem>
          </NGrid>
        </NForm>

        <NDivider class="detail-divider" />

        <div class="detail-header">
          <div>
            <div class="detail-title">导出明细</div>
            <div class="detail-subtitle">T_COST_EXPORT_CONFIG_DETAIL</div>
          </div>
          <NButton size="small" type="primary" @click="openDetailEditor()">新增明细</NButton>
        </div>

        <NDataTable
          :columns="detailColumns"
          :data="detailRows"
          :row-key="(row: ExportDetailRow) => row._localKey"
          size="small"
          :bordered="false"
          :loading="detailLoading"
          :pagination="false"
          max-height="260"
        />
        <p v-if="!detailLoading && detailRows.length === 0" class="empty-hint">暂无导出明细</p>

        <div class="editor-actions">
          <NSpace justify="end">
            <NButton size="small" @click="editorVisible = false">取消</NButton>
            <NButton size="small" type="primary" :loading="editorSaving" @click="saveEditor">保存导出</NButton>
          </NSpace>
        </div>
      </div>
    </NModal>

    <NModal
      v-model:show="detailEditorVisible"
      preset="card"
      :title="detailEditorTitle"
      :style="{ width: '780px', maxWidth: 'calc(100vw - 48px)' }"
      :mask-closable="false"
    >
      <NForm label-placement="top" size="small">
        <NGrid :cols="3" :x-gap="12" :y-gap="4">
          <NGridItem>
            <NFormItem label="明细表">
              <NSelect
                v-model:value="detailForm.tabKey"
                :options="detailSourceOptions"
                filterable
                tag
                @update:value="handleDetailSourceChange"
              />
            </NFormItem>
          </NGridItem>
          <NGridItem>
            <NFormItem label="Sheet名称">
              <NInput v-model:value="detailForm.sheetName" placeholder="例如：原辅料明细" />
            </NFormItem>
          </NGridItem>
          <NGridItem>
            <NFormItem label="排序">
              <NInputNumber v-model:value="detailForm.displayOrder" :min="0" style="width: 100%" />
            </NFormItem>
          </NGridItem>
          <NGridItem>
            <NFormItem label="明细关联列">
              <NInput v-model:value="detailForm.detailLinkColumn" placeholder="例如：DOCID" />
            </NFormItem>
          </NGridItem>
          <NGridItem :span="3">
            <NFormItem label="明细列配置(JSON)">
              <NInput v-model:value="detailForm.columns" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" />
            </NFormItem>
          </NGridItem>
          <NGridItem :span="3">
            <NFormItem label="明细 SQL">
              <NInput v-model:value="detailForm.detailSql" type="textarea" :autosize="{ minRows: 6, maxRows: 12 }" />
            </NFormItem>
          </NGridItem>
        </NGrid>
      </NForm>
      <div class="editor-actions">
        <NSpace justify="end">
          <NButton size="small" @click="detailEditorVisible = false">取消</NButton>
          <NButton size="small" type="primary" @click="confirmDetailEdit">确定</NButton>
        </NSpace>
      </div>
    </NModal>
  </div>
</template>

<style scoped>
.section-export {
  padding: 8px 0;
}

.export-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.empty-hint {
  color: #8a9099;
  font-size: 13px;
  padding: 10px 0;
}

.editor-body {
  display: flex;
  flex-direction: column;
}

.detail-divider {
  margin: 8px 0 12px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.detail-title {
  color: #222a3a;
  font-size: 14px;
  font-weight: 600;
}

.detail-subtitle {
  color: #8a9099;
  font-size: 12px;
  line-height: 1.4;
}

.editor-actions {
  margin-top: 14px;
}
</style>
