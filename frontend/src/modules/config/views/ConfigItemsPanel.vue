<script setup lang="ts">
/**
 * 全部配置项（C09 `GET /api/config/items`）：按类型筛选，列出编码、名称、版本、修改人、修改时间；
 * "打开"跳到对应的编辑界面（页面、实体、审批流等在一体化配置中按页面编辑；Lookup、字典、角色在各自的 Tab），
 * "删除"删除配置项，仍被引用时显示后端返回的明细。
 */
import { onMounted, ref } from 'vue';
import { NButton, NPopconfirm, NSelect, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import { useConfigContext } from '../core/context';
import { type ConfigProblem, errorText } from '../core/errors';
import type { ConfigSummary } from '../core/store';
import { CONFIG_TYPE_LABELS, type ConfigType } from '../core/types';
import ConfigGrid from '../components/ConfigGrid.vue';
import ProblemList from '../components/ProblemList.vue';

const emit = defineEmits<{ open: [tab: string] }>();
const { store, notify } = useConfigContext();
const type = ref<ConfigType | null>(null);
const rows = ref<ConfigSummary[]>([]);
const selected = ref<ConfigSummary[]>([]);
const loading = ref(false);
const problems = ref<ConfigProblem[]>([]);
const typeOptions = (Object.keys(CONFIG_TYPE_LABELS) as ConfigType[]).map(t => ({ label: `${CONFIG_TYPE_LABELS[t]}（${t}）`, value: t }));
const TAB_OF: Partial<Record<ConfigType, string>> = { lookup: 'lookup', dict: 'dict', role: 'permission' };

const columns: ColDef[] = [
  { field: 'type', headerName: '类型', width: 120, editable: false, valueFormatter: p => CONFIG_TYPE_LABELS[p.value as ConfigType] ?? p.value },
  { field: 'key', headerName: '编码', width: 260, editable: false },
  { field: 'name', headerName: '名称', width: 220, editable: false },
  { field: 'version', headerName: '版本', width: 80, editable: false },
  { field: 'updatedBy', headerName: '修改人', width: 100, editable: false },
  { field: 'updatedAt', headerName: '修改时间', flex: 1, editable: false }
];

async function load() {
  loading.value = true;
  try {
    rows.value = await store.list(type.value ?? undefined);
  } catch (error) {
    notify.error(errorText(error));
  } finally {
    loading.value = false;
  }
}

async function remove() {
  problems.value = [];
  for (const row of selected.value) {
    const result = await store.remove(row.type, row.key);
    if (!result.ok) problems.value.push(...result.problems);
  }
  selected.value = [];
  await load();
}

onMounted(load);
</script>

<template>
  <div class="items-panel">
    <NSpace size="small" align="center" class="toolbar">
      <NSelect v-model:value="type" :options="typeOptions" clearable placeholder="全部类型" size="small" style="width: 200px" @update:value="load" />
      <NButton size="small" quaternary :loading="loading" @click="load">刷新</NButton>
      <NButton size="small" :disabled="selected.length !== 1" @click="emit('open', TAB_OF[selected[0].type] ?? 'unified')">打开</NButton>
      <NPopconfirm :disabled="!selected.length" @positive-click="remove">
        <template #trigger><NButton size="small" type="error" quaternary :disabled="!selected.length">删除</NButton></template>
        确定删除选中的 {{ selected.length }} 个配置项？仍被其他配置引用的不能删除。
      </NPopconfirm>
      <span class="hint">共 {{ rows.length }} 项。页面、实体、操作、规则、审批流、导出在"一体化配置"中按页面编辑。</span>
    </NSpace>
    <ProblemList :problems="problems" />
    <ConfigGrid :rows="rows" :columns="columns" :height="560" :loading="loading" multiple @select="selected = $event" />
  </div>
</template>

<style scoped>
.items-panel { padding: 8px 0; }
.toolbar { margin-bottom: 8px; }
.hint { color: #999; font-size: 12px; }
</style>
