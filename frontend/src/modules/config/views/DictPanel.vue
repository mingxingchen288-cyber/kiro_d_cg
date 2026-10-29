<script setup lang="ts">
/**
 * 字典管理（C06 第 9 节 `dict`）：左侧字典列表，右侧字典项表格（值、名称、顺序）。
 * 旧系统前端没有字典管理页面（字典类型写在列元数据的 DICT_TYPE 上），这里沿用 Lookup管理的表格写法；
 * 顺序必须写，新增项时按位置预填，上移下移后按位置重排。
 */
import { computed, onMounted, ref } from 'vue';
import { NButton, NInput, NList, NListItem, NPopconfirm, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import { useConfigContext } from '../core/context';
import { ItemEditor } from '../core/item-editor';
import ConfigGrid from '../components/ConfigGrid.vue';
import ProblemList from '../components/ProblemList.vue';

type Item = { value: string; label: string; order: number };
const { store, notify } = useConfigContext();
const editor = new ItemEditor(store, 'dict', notify);
const selected = ref<Item[]>([]);
const grid = ref<InstanceType<typeof ConfigGrid>>();
const newKey = ref('');
const newName = ref('');
const items = computed(() => editor.state.current?.content.items ?? []);
const columns: ColDef[] = [
  { field: 'value', headerName: '值', width: 160 },
  { field: 'label', headerName: '名称', width: 200 },
  { field: 'order', headerName: '顺序', width: 90, cellDataType: 'number' }
];

function create() {
  if (!newKey.value.trim()) return notify.warning('请填写字典编码');
  editor.create(newKey.value.trim(), newName.value.trim() || newKey.value.trim());
  newKey.value = '';
  newName.value = '';
}

function addItem() {
  const list = editor.state.current!.content.items;
  list.push({ value: '', label: '', order: list.length + 1 });
  editor.markDirty();
}

function renumber() {
  editor.state.current!.content.items.forEach((item, i) => (item.order = i + 1));
}

function move(offset: number) {
  grid.value?.stopEditing();
  const list = editor.state.current!.content.items;
  const index = list.indexOf(selected.value[0]);
  if (selected.value.length !== 1 || index + offset < 0 || index + offset >= list.length) return;
  [list[index], list[index + offset]] = [list[index + offset], list[index]];
  renumber();
  editor.markDirty();
  grid.value?.refresh();
}

function removeItems() {
  const current = editor.state.current!;
  current.content.items = current.content.items.filter(i => !selected.value.includes(i));
  selected.value = [];
  editor.markDirty();
}

onMounted(() => editor.loadList());
</script>

<template>
  <div class="dict-panel">
    <div class="dict-list">
      <NList hoverable clickable size="small">
        <NListItem v-for="item in editor.state.items" :key="item.key" :class="{ active: editor.state.current?.key === item.key }" @click="editor.open(item.key)">
          <div>{{ item.name }}</div>
          <div class="hint">{{ item.key }} · 版本 {{ item.version }}</div>
        </NListItem>
      </NList>
      <NSpace vertical size="small" class="mt-8">
        <NInput v-model:value="newKey" size="small" placeholder="字典编码" />
        <NInput v-model:value="newName" size="small" placeholder="字典名称" />
        <NButton size="small" block @click="create">新增字典</NButton>
      </NSpace>
    </div>
    <div v-if="editor.state.current" class="dict-items">
      <NSpace align="center" size="small" class="mb-8">
        <span class="title">{{ editor.state.current.key }}</span>
        <NInput v-model:value="editor.state.current.name" size="small" style="width: 200px" @update:value="editor.markDirty()" />
        <NButton size="small" @click="addItem">新增项</NButton>
        <NButton size="small" :disabled="!selected.length" @click="removeItems">删除选中项</NButton>
        <NButton size="small" :disabled="selected.length !== 1" @click="move(-1)">上移</NButton>
        <NButton size="small" :disabled="selected.length !== 1" @click="move(1)">下移</NButton>
        <NButton size="small" type="primary" :loading="editor.state.busy" @click="editor.save()">保存</NButton>
        <NPopconfirm @positive-click="editor.remove()">
          <template #trigger><NButton size="small" type="error" quaternary>删除字典</NButton></template>
          确定删除这个字典？仍被页面字段引用时不能删除。
        </NPopconfirm>
        <span class="hint">{{ editor.state.status }}</span>
      </NSpace>
      <ProblemList :problems="editor.state.problems" />
      <ConfigGrid ref="grid" :rows="items" :columns="columns" :height="460" multiple @select="selected = $event" @change="editor.markDirty()" />
    </div>
    <div v-else class="dict-items empty">从左侧选择一个字典，或新增字典</div>
  </div>
</template>

<style scoped>
.dict-panel { display: flex; gap: 16px; height: 100%; padding: 8px 0; }
.dict-list { width: 240px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid #e8e8e8; padding-right: 8px; }
.dict-items { flex: 1; min-width: 0; }
.dict-items.empty { color: #999; display: flex; align-items: center; justify-content: center; }
.title { font-weight: 500; }
.hint { color: #999; font-size: 12px; }
.active { background: #e8f2ff; }
</style>
