<script setup lang="ts">
/**
 * 配置列权限，同旧系统（800px）：按区域分 Tab，每个字段 可见 / 可编辑（表头可全选），C06 另允许增加必填；
 * 页面和实体给出的基线不可见（不可编辑）的字段不能放开。保存时只写比基线收紧的字段。
 */
import { computed, h, ref } from 'vue';
import { NButton, NCheckbox, NDataTable, NModal, NTabPane, NTabs } from 'naive-ui';
import type { PageCatalog } from '../core/catalog';
import type { FieldFlags } from '../core/types';
import { type ColumnRow, columnPolicy, columnRows } from './role-model';

const props = defineProps<{ pageTitle: string; catalog: PageCatalog; value: Record<string, Record<string, FieldFlags>> }>();
const emit = defineEmits<{ close: []; save: [columns: Record<string, Record<string, FieldFlags>>] }>();
const areaKey = (i: number) => (i === 0 ? 'master' : props.catalog.tables[i].entity);
const areaSettings = (i: number) => (i === 0 ? props.catalog.page.master.fields : props.catalog.page.details?.[i - 1]?.fields) ?? {};

function baseOf(i: number): Record<string, FieldFlags> {
  const table = props.catalog.tables[i];
  const defaults = table.content?.fieldDefaults ?? {};
  const page = areaSettings(i);
  return Object.fromEntries(
    table.fields.map(f => [f.name, { visible: defaults[f.name]?.visible !== false && page[f.name]?.visible !== false, editable: defaults[f.name]?.editable !== false && page[f.name]?.editable !== false }])
  );
}

const tabs = ref(props.catalog.tables.map((t, i) => ({ key: areaKey(i), title: t.title, rows: columnRows(t.fields, baseOf(i), props.value[areaKey(i)]) })));
const active = ref(tabs.value[0]?.key);

const header = (label: string, rows: ColumnRow[], key: 'visible' | 'editable' | 'required') =>
  h('div', { class: 'column-header-with-checkbox' }, [
    h(NCheckbox, {
      checked: rows.length > 0 && rows.every(r => r[key]),
      onUpdateChecked: (c: boolean) => rows.forEach(r => (key === 'visible' ? r.baseVisible : key === 'editable' ? r.baseEditable && r.visible : true) && (r[key] = c))
    }),
    h('span', label)
  ]);

const columnsOf = (rows: ColumnRow[]) => [
  { title: '列名', key: 'label', width: 150 },
  { title: '字段', key: 'field', width: 150 },
  { title: () => header('可见', rows, 'visible'), key: 'visible', width: 100, render: (row: ColumnRow) => h(NCheckbox, { checked: row.visible, disabled: !row.baseVisible, onUpdateChecked: (c: boolean) => ((row.visible = c), !c && (row.editable = false)) }) },
  { title: () => header('可编辑', rows, 'editable'), key: 'editable', width: 100, render: (row: ColumnRow) => h(NCheckbox, { checked: row.editable, disabled: !row.baseEditable || !row.visible, onUpdateChecked: (c: boolean) => (row.editable = c) }) },
  { title: () => header('必填', rows, 'required'), key: 'required', width: 100, render: (row: ColumnRow) => h(NCheckbox, { checked: row.required, onUpdateChecked: (c: boolean) => (row.required = c) }) }
];

const result = computed(() => Object.fromEntries(tabs.value.map(t => [t.key, columnPolicy(t.rows)]).filter(([, v]) => Object.keys(v as object).length)));
</script>

<template>
  <NModal :show="true" preset="card" title="配置列权限" style="width: 800px" @update:show="emit('close')">
    <div class="column-modal-header"><span class="page-label">页面：{{ pageTitle }}</span></div>
    <NTabs v-model:value="active" type="line" size="small">
      <NTabPane v-for="tab in tabs" :key="tab.key" :name="tab.key" :tab="tab.title">
        <NDataTable :columns="columnsOf(tab.rows)" :data="tab.rows" :bordered="false" size="small" :max-height="400" />
      </NTabPane>
    </NTabs>
    <template #footer>
      <div class="modal-footer">
        <NButton size="small" @click="emit('close')">取消</NButton>
        <NButton type="primary" size="small" @click="emit('save', result)">确定</NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.column-modal-header { margin-bottom: 8px; }
.page-label { color: #666; font-size: 13px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
:deep(.column-header-with-checkbox) { display: flex; align-items: center; gap: 4px; }
</style>
