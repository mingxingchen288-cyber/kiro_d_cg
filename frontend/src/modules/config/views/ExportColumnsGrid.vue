<script setup lang="ts">
/** 导出的列（C06 第 9 节 `columns`）：字段（SQL 结果的列）、表头（用 / 分隔多级表头）；按顺序导出，可上移下移 */
import { ref } from 'vue';
import { NButton, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { ExportColumn } from '../core/types';
import ConfigGrid from '../components/ConfigGrid.vue';

const props = defineProps<{ columns: ExportColumn[] }>();
const selected = ref<ExportColumn[]>([]);
const grid = ref<InstanceType<typeof ConfigGrid>>();
const defs: ColDef[] = [
  { field: 'field', headerName: '字段（SQL 结果的列）', width: 220 },
  { field: 'header', headerName: '表头（多级用 / 分隔，例如 成本/单价）', flex: 1 }
];

function move(offset: number) {
  grid.value?.stopEditing();
  const cols = props.columns;
  const index = cols.indexOf(selected.value[0]);
  if (selected.value.length !== 1 || index + offset < 0 || index + offset >= cols.length) return;
  [cols[index], cols[index + offset]] = [cols[index + offset], cols[index]];
  grid.value?.refresh();
}

function remove() {
  for (const row of selected.value) props.columns.splice(props.columns.indexOf(row), 1);
  selected.value = [];
}
</script>

<template>
  <div>
    <NSpace size="small" class="mb-4">
      <NButton size="tiny" @click="columns.push({ field: '', header: '' })">新增列</NButton>
      <NButton size="tiny" :disabled="!selected.length" @click="remove">删除选中列</NButton>
      <NButton size="tiny" :disabled="selected.length !== 1" @click="move(-1)">上移</NButton>
      <NButton size="tiny" :disabled="selected.length !== 1" @click="move(1)">下移</NButton>
    </NSpace>
    <ConfigGrid ref="grid" :rows="columns" :columns="defs" :height="180" multiple @select="selected = $event" />
  </div>
</template>
