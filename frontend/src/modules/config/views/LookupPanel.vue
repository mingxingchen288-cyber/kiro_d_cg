<script setup lang="ts">
/**
 * Lookup管理，同旧系统 LookupPanel.vue：表格列 lookupCode、名称、数据源、显示列，工具栏 新增 / 删除 / 保存 / 刷新；
 * 双击"显示列"打开"配置显示列"（读数据源的列，勾选显示列和关键字搜索列，全选 / 清空）。
 * 每个 Lookup 是一个 `lookup` 配置项（C06 第 9 节）：`keywordColumns` 必须写，不按关键字搜索时为空数组。
 * 旧系统显示列的"显示标题、宽度"在 C06 的 lookup 中没有对应字段，不提供。
 */
import { computed, h, onMounted, ref } from 'vue';
import { NAlert, NButton, NCheckbox, NDataTable, NModal, NPopconfirm, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import { useConfigContext } from '../core/context';
import { type ConfigProblem, errorText } from '../core/errors';
import type { LookupContent } from '../core/types';
import ConfigGrid from '../components/ConfigGrid.vue';
import ProblemList from '../components/ProblemList.vue';
import { linkColumn } from '../components/grid-columns';

interface Row extends LookupContent {
  _id: string;
  key: string;
  name: string;
  version: number | null;
  dirty: boolean;
}

const { api, store, notify } = useConfigContext();
const rows = ref<Row[]>([]);
const selected = ref<Row[]>([]);
const loading = ref(false);
const saving = ref(false);
const problems = ref<ConfigProblem[]>([]);
const editing = ref<Row | null>(null);
const showColumns = ref(false);
const sourceColumns = ref<Array<{ name: string; show: boolean; keyword: boolean }>>([]);
const loadingColumns = ref(false);
let sequence = 0;

const columns = computed<ColDef[]>(() => [
  { field: 'key', headerName: 'lookupCode', width: 160, editable: p => p.data?.version === null },
  { field: 'name', headerName: '名称', width: 160 },
  { field: 'table', headerName: '数据源（表或视图）', width: 220 },
  linkColumn('columns', '显示列', 260, (d: Row) => d.columns.join(', ') || '双击配置显示列'),
  linkColumn('keywordColumns', '关键字搜索列', 200, (d: Row) => d.keywordColumns.join(', ') || '不按关键字搜索'),
  { field: 'orderBy', headerName: '排序', width: 140 },
  { colId: 'state', headerName: '状态', width: 100, editable: false, valueGetter: p => (p.data?.dirty ? '未保存' : `版本 ${p.data?.version}`) }
]);

async function load() {
  loading.value = true;
  try {
    rows.value = (await store.loadAll('lookup')).map(item => ({ _id: `lookup-${++sequence}`, key: item.key, name: item.name, version: item.version, dirty: false, orderBy: null, ...item.content }));
  } catch (error) {
    notify.error(errorText(error));
  } finally {
    loading.value = false;
  }
}

function add() {
  rows.value = [...rows.value, { _id: `lookup-${++sequence}`, key: '', name: '新 Lookup', version: null, dirty: true, table: '', columns: [], keywordColumns: [], orderBy: null }];
}

function content(row: Row): LookupContent {
  const out: LookupContent = { table: row.table.trim(), columns: [...row.columns], keywordColumns: [...row.keywordColumns] };
  if (row.orderBy) out.orderBy = row.orderBy.trim();
  return out;
}

/** 保存改动过的 Lookup：逐个先校验再保存，被拒绝的显示明细 */
async function save() {
  saving.value = true;
  problems.value = [];
  try {
    for (const row of rows.value.filter(r => r.dirty)) {
      const result = await store.save('lookup', row.key, row.name, content(row));
      if (result.ok) Object.assign(row, { version: result.version, dirty: false });
      else problems.value.push(...result.problems);
    }
    if (!problems.value.length) notify.success('Lookup 已保存');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  for (const row of selected.value) {
    if (row.version !== null) {
      const result = await store.remove('lookup', row.key);
      if (!result.ok) {
        problems.value = result.problems;
        continue;
      }
    }
    rows.value = rows.value.filter(r => r !== row);
  }
  selected.value = [];
}

async function onEdit(event: { colDef: ColDef; data: Row }) {
  if (event.colDef.colId !== 'columns' && event.colDef.colId !== 'keywordColumns') return;
  const row = event.data;
  if (!row.table.trim()) return notify.warning('请先填写数据源');
  editing.value = row;
  showColumns.value = true;
  loadingColumns.value = true;
  try {
    const schema = await api.schemaColumns(row.table.trim());
    sourceColumns.value = schema.columns.map(c => ({ name: c.name, show: row.columns.includes(c.name), keyword: row.keywordColumns.includes(c.name) }));
  } catch (error) {
    notify.error(errorText(error));
  } finally {
    loadingColumns.value = false;
  }
}

function applyColumns() {
  const row = editing.value!;
  row.columns = sourceColumns.value.filter(c => c.show).map(c => c.name);
  row.keywordColumns = sourceColumns.value.filter(c => c.keyword).map(c => c.name);
  row.dirty = true;
  showColumns.value = false;
}

onMounted(load);
</script>

<template>
  <div class="lookup-panel">
    <NSpace size="small" class="toolbar">
      <NButton size="small" type="primary" @click="add">新增</NButton>
      <NPopconfirm :disabled="!selected.length" @positive-click="remove">
        <template #trigger><NButton size="small" type="error" :disabled="!selected.length">删除</NButton></template>
        确定删除选中的 Lookup？仍被页面字段引用时不能删除。
      </NPopconfirm>
      <NButton size="small" :loading="saving" @click="save">保存</NButton>
      <NButton size="small" quaternary @click="load">刷新</NButton>
    </NSpace>
    <ProblemList :problems="problems" />
    <ConfigGrid :rows="rows" :columns="columns" :height="520" :loading="loading" multiple row-key="_id" @select="selected = $event" @change="e => (e.data.dirty = true)" @edit="onEdit" />
    <NModal v-model:show="showColumns" preset="card" title="配置显示列" style="width: 640px">
      <NSpace justify="space-between" class="mb-8">
        <span>数据源：{{ editing?.table || '-' }}</span>
        <span>已选 {{ sourceColumns.filter(c => c.show).length }} 列</span>
        <NSpace size="small">
          <NButton size="small" @click="sourceColumns.forEach(c => (c.show = true))">全选</NButton>
          <NButton size="small" @click="sourceColumns.forEach(c => ((c.show = false), (c.keyword = false)))">清空</NButton>
        </NSpace>
      </NSpace>
      <div v-if="loadingColumns" class="empty">正在加载列结构...</div>
      <NAlert v-else-if="!sourceColumns.length" type="warning" :bordered="false">数据源 {{ editing?.table }} 在数据库中不存在或没有列</NAlert>
      <NDataTable
        v-else
        size="small"
        max-height="420"
        :data="sourceColumns"
        :columns="[
          { title: '字段', key: 'name' },
          { title: '显示', key: 'show', width: 80, render: (row: any) => h(NCheckbox, { checked: row.show, onUpdateChecked: (v: boolean) => ((row.show = v), !v && (row.keyword = false)) }) },
          { title: '关键字搜索', key: 'keyword', width: 110, render: (row: any) => h(NCheckbox, { checked: row.keyword, disabled: !row.show, onUpdateChecked: (v: boolean) => (row.keyword = v) }) }
        ]"
      />
      <NSpace justify="end" class="mt-8">
        <NButton size="small" @click="showColumns = false">取消</NButton>
        <NButton size="small" type="primary" @click="applyColumns">确定</NButton>
      </NSpace>
    </NModal>
  </div>
</template>

<style scoped>
.lookup-panel { padding: 8px 0; }
.toolbar { margin-bottom: 8px; }
.empty { color: #999; padding: 12px; }
</style>
