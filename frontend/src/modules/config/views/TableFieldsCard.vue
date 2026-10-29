<script setup lang="ts">
/**
 * "表与列"中的一张表，同旧系统 SectionTables.vue 的一个折叠项：视图 / 目标表 / PK 等表信息和"保存表信息"，
 * 列表格（标题、类型、写入列、来源、角色、小数位、显示、编辑、必填、宽度、固定、字典、Lookup、默认值、选项值、对比），
 * 按钮"从视图重新导入""选择视图列添加""删除选中列""上移""下移""保存列"。
 * 保存列：先保存实体（C06 第 2 节），再保存页面的字段设置（第 3 节），都先校验。
 */
import { computed, onMounted, ref } from 'vue';
import { NAlert, NButton, NDataTable, NDescriptions, NDescriptionsItem, NInput, NModal, NRadio, NRadioGroup, NSpace, NSwitch } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { PageTable } from '../core/catalog';
import { useConfigContext } from '../core/context';
import { errorText } from '../core/errors';
import { ItemEditor } from '../core/item-editor';
import type { FieldSetting, PageArea } from '../core/types';
import { BUILTIN_DEFAULTS, compareText } from '../entity/entity-model';
import ConfigGrid from '../components/ConfigGrid.vue';
import ProblemList from '../components/ProblemList.vue';
import { booleanColumn, linkColumn, selectColumn } from '../components/grid-columns';
import CompareDialog from './CompareDialog.vue';
import LookupSettingDialog from './LookupSettingDialog.vue';
import { type FieldRow, type FlagScope, applyRows, fieldRows, newRowsFrom } from './table-fields';

const props = defineProps<{ page: ItemEditor<'page'>; table: PageTable; area: PageArea; dicts: Array<{ label: string; value: string }>; lookups: Array<{ label: string; value: string }> }>();
const emit = defineEmits<{ reload: [] }>();
const { api, store, notify } = useConfigContext();
const entity = new ItemEditor(store, 'entity', notify);
const scope = ref<FlagScope>('page');
const rows = ref<FieldRow[]>([]);
const selected = ref<FieldRow[]>([]);
const grid = ref<InstanceType<typeof ConfigGrid>>();
const showAdd = ref(false);
const candidates = ref<FieldRow[]>([]);
const checkedNames = ref<string[]>([]);
const lookupRow = ref<FieldRow | null>(null);
const compareRow = ref<FieldRow | null>(null);
const showLookup = ref(false);
const showCompare = ref(false);
const content = computed(() => entity.state.current?.content ?? null);

const columns = computed<ColDef[]>(() => [
  { field: 'name', headerName: '字段名', width: 130, editable: false },
  { field: 'label', headerName: '标题', width: 120 },
  selectColumn('type', '类型', ['text', 'number', 'date', 'datetime', 'boolean'].map(v => ({ label: v, value: v })), 90),
  { field: 'column', headerName: '写入列（空为只读）', width: 140 },
  selectColumn('source', '来源', [{ label: '自有', value: 'own' }, { label: 'ERP', value: 'erp' }], 70),
  selectColumn('role', '角色', [{ label: '输入', value: 'input' }, { label: '计算', value: 'calculated' }, { label: '系统', value: 'system' }], 70),
  { field: 'scale', headerName: '小数位', width: 70, cellDataType: 'number' },
  booleanColumn('visible', '显示', 55),
  booleanColumn('editable', '编辑', 55),
  booleanColumn('required', '必填', 55),
  { field: 'width', headerName: '宽度', width: 65, cellDataType: 'number' },
  selectColumn('pinned', '固定', [{ label: '不固定', value: null }, { label: '左', value: 'left' }, { label: '右', value: 'right' }], 70),
  selectColumn('dictType', '字典', [{ label: '（无）', value: null }, ...props.dicts], 110),
  linkColumn('lookup', 'Lookup', 120, (d: FieldRow) => (d.lookup ? `Lookup: ${d.lookup.code}` : '配置Lookup')),
  { field: 'defaultText', headerName: '默认值', width: 130, cellEditor: 'agRichSelectCellEditor', cellEditorParams: { values: ['', ...BUILTIN_DEFAULTS.map(b => b.label)], allowTyping: true, filterList: true } },
  { field: 'optionsText', headerName: '选项值（逗号分隔）', width: 150 },
  linkColumn('compare', '对比', 150, (d: FieldRow) => compareText(d.compare) || '配置对比')
]);

const settings = (): Record<string, FieldSetting> => props.area.fields ?? {};

async function load() {
  await entity.open(props.table.entity);
  if (content.value) rows.value = fieldRows(content.value, settings(), scope.value);
}

function switchScope(value: FlagScope) {
  if (content.value) {
    const applied = applyRows(content.value, settings(), rows.value, scope.value);
    entity.state.current!.content = applied.entity;
    props.area.fields = applied.settings;
    rows.value = fieldRows(applied.entity, applied.settings, value);
  }
  scope.value = value;
}

async function saveTableInfo() {
  if (await entity.save()) emit('reload');
}

async function saveColumns() {
  grid.value?.stopEditing();
  if (!content.value) return;
  const applied = applyRows(content.value, settings(), rows.value, scope.value);
  entity.state.current!.content = applied.entity;
  props.area.fields = applied.settings;
  if ((await entity.save()) === null) return;
  props.page.markDirty();
  if ((await props.page.save()) !== null) {
    rows.value = fieldRows(entity.state.current!.content, settings(), scope.value);
    emit('reload');
  }
}

async function readColumns() {
  const c = content.value!;
  return api.wizardColumns({ readView: c.readView || null, table: c.table });
}

async function reimport() {
  try {
    const added = newRowsFrom((await readColumns()).columns, rows.value);
    rows.value = [...rows.value, ...added];
    notify[added.length ? 'success' : 'warning'](added.length ? `发现 ${added.length} 个新列，请确认后保存` : '没有新列需要导入');
  } catch (error) {
    notify.error(errorText(error));
  }
}

async function openAdd() {
  try {
    candidates.value = newRowsFrom((await readColumns()).columns, rows.value);
    checkedNames.value = [];
    showAdd.value = true;
  } catch (error) {
    notify.error(errorText(error));
  }
}

function addChecked() {
  rows.value = [...rows.value, ...candidates.value.filter(c => checkedNames.value.includes(c.name))];
  showAdd.value = false;
}

function removeSelected() {
  rows.value = rows.value.filter(r => !selected.value.includes(r));
  selected.value = [];
}

function move(offset: number) {
  const index = rows.value.indexOf(selected.value[0]);
  if (selected.value.length !== 1 || index + offset < 0 || index + offset >= rows.value.length) return;
  const next = [...rows.value];
  [next[index], next[index + offset]] = [next[index + offset], next[index]];
  rows.value = next;
}

function onEdit(event: { colDef: ColDef; data: FieldRow }) {
  if (event.colDef.colId === 'lookup') {
    lookupRow.value = event.data;
    showLookup.value = true;
  }
  if (event.colDef.colId === 'compare') {
    compareRow.value = event.data;
    showCompare.value = true;
  }
}

const rowStyle = (p: { data?: FieldRow }) => (p.data && !p.data.column ? { background: '#fffbe6' } : undefined);

onMounted(load);
</script>

<template>
  <div v-if="content">
    <NDescriptions size="small" :column="3" bordered class="table-meta">
      <NDescriptionsItem label="视图"><NInput v-model:value="content.readView" size="small" placeholder="读取视图（可空）" style="width: 220px" /></NDescriptionsItem>
      <NDescriptionsItem label="目标表"><NInput v-model:value="content.table" size="small" style="width: 220px" /></NDescriptionsItem>
      <NDescriptionsItem label="PK"><NInput v-model:value="content.primaryKey" size="small" style="width: 120px" /></NDescriptionsItem>
      <NDescriptionsItem label="可被审批冻结"><NSwitch v-model:value="content.freezable" size="small" /></NDescriptionsItem>
      <NDescriptionsItem label="ERP 行标识" :span="2">
        <NSpace size="small" align="center">
          <template v-if="content.erpRow">
            <NInput v-model:value="content.erpRow.column" size="small" placeholder="列，如 ISERP" style="width: 120px" />
            <NInput v-model:value="content.erpRow.value" size="small" placeholder="ERP 行的值" style="width: 100px" />
            <NInput v-model:value="content.erpRow.localValue" size="small" placeholder="本地行的值" style="width: 100px" />
            <NButton size="tiny" quaternary @click="content.erpRow = null">去掉</NButton>
          </template>
          <NButton v-else size="tiny" @click="content.erpRow = { column: '', value: '1', localValue: '0' }">设置 ERP 行</NButton>
          <span class="hint">没有 ERP 行标识时，ERP 列在所有行上都只读</span>
        </NSpace>
      </NDescriptionsItem>
    </NDescriptions>
    <div class="table-actions">
      <NButton size="tiny" :loading="entity.state.busy" @click="saveTableInfo">保存表信息</NButton>
      <span class="hint">{{ entity.state.status }}</span>
    </div>
    <ProblemList :problems="[...entity.state.problems, ...page.state.problems]" />
    <div class="scope">
      <span class="hint">显示 / 编辑 / 必填：</span>
      <NRadioGroup :value="scope" size="small" @update:value="switchScope">
        <NRadio value="page">本页面</NRadio>
        <NRadio value="entity">实体默认（所有页面）</NRadio>
      </NRadioGroup>
      <span class="hint">下层只能收紧可见、可编辑，必填只能增加；黄色行是视图中有、表中没有的列，只读显示。</span>
    </div>
    <ConfigGrid ref="grid" :rows="rows" :columns="columns" :height="Math.max(250, Math.min(520, rows.length * 29 + 40))" multiple row-key="_id" :row-style="rowStyle" @select="selected = $event" @edit="onEdit" />
    <div class="grid-actions">
      <NSpace size="small" justify="end">
        <NButton size="small" @click="reimport">从视图重新导入</NButton>
        <NButton size="small" @click="openAdd">选择视图列添加</NButton>
        <NButton size="small" :disabled="selected.length !== 1" @click="move(-1)">上移</NButton>
        <NButton size="small" :disabled="selected.length !== 1" @click="move(1)">下移</NButton>
        <NButton size="small" type="error" :disabled="!selected.length" @click="removeSelected">删除选中列</NButton>
        <NButton size="small" type="primary" :loading="entity.state.busy || page.state.busy" @click="saveColumns">保存列</NButton>
      </NSpace>
    </div>
    <NModal v-model:show="showAdd" preset="card" title="选择视图列添加" :style="{ width: '760px' }">
      <div class="add-column-meta">{{ content.readView || content.table }}</div>
      <NDataTable
        v-model:checked-row-keys="checkedNames"
        :columns="[{ type: 'selection', multiple: true }, { title: '字段名', key: 'name', width: 180 }, { title: '标题', key: 'label', width: 180 }, { title: '类型', key: 'type', width: 120 }, { title: '列类型', key: 'column', width: 90, render: (row: FieldRow) => (row.column ? '真实列' : '虚拟列') }]"
        :data="candidates"
        :row-key="(row: FieldRow) => row.name"
        size="small"
        max-height="420"
      />
      <NAlert v-if="!candidates.length" type="info" :bordered="false" class="mt-8">没有新列需要添加</NAlert>
      <NSpace justify="end" class="mt-8">
        <NButton size="small" @click="showAdd = false">取消</NButton>
        <NButton size="small" type="primary" @click="addChecked">添加选中列</NButton>
      </NSpace>
    </NModal>
    <LookupSettingDialog v-if="lookupRow" v-model:show="showLookup" :value="lookupRow.lookup" :lookups="lookups" :fields="rows.map(r => r.name)" @save="v => (lookupRow!.lookup = v, grid?.refresh())" />
    <CompareDialog v-if="compareRow" v-model:show="showCompare" :value="compareRow.compare" :fields="rows.map(r => r.name)" @save="v => (compareRow!.compare = v, grid?.refresh())" />
  </div>
</template>

<style scoped>
.table-meta { margin-bottom: 8px; }
.table-actions { margin: 4px 0 8px; display: flex; gap: 8px; align-items: center; }
.scope { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
.hint { color: #999; font-size: 12px; }
.grid-actions { margin-top: 8px; }
.add-column-meta { color: #666; font-size: 13px; margin-bottom: 8px; }
</style>
