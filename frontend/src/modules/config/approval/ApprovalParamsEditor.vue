<script setup lang="ts">
/**
 * 审批流参数弹窗（C06 7.1 `params`、FC-08），表格写法同旧系统"审批动作 · 参数映射"（ApprovalActionParamsEditor.vue）：
 * 参数编码、显示名称、类型、必填、参数来源（审批时填写 / 固定值 / SQL 表达式）、填写级别、值。
 * 审批时填写的参数在"填写级别"那一级由审批人填写，留空为最终批准时填写；中途填写的也只在最终批准时使用。
 */
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NModal, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { FlowParam } from '../core/types';
import ConfigGrid from '../components/ConfigGrid.vue';
import { booleanColumn, largeTextColumn, selectColumn } from '../components/grid-columns';

interface Row extends FlowParam {
  _id: string;
}

const props = defineProps<{ show: boolean; params: FlowParam[]; levels: number[]; problems: string[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [rows: FlowParam[]] }>();
const rows = ref<Row[]>([]);
const selected = ref<Row[]>([]);
const grid = ref<InstanceType<typeof ConfigGrid>>();
let sequence = 0;

const columns = computed<ColDef[]>(() => [
  { field: 'name', headerName: '参数编码', width: 150 },
  { field: 'label', headerName: '显示名称', width: 140 },
  selectColumn('type', '类型', [{ label: '文本', value: 'string' }, { label: '数字', value: 'number' }, { label: '是／否', value: 'boolean' }, { label: '日期', value: 'date' }], 100),
  booleanColumn('required', '必填'),
  selectColumn('source', '参数来源', [{ label: '审批时填写', value: 'manual' }, { label: '固定值', value: 'constant' }, { label: 'SQL 表达式', value: 'expression' }], 130),
  {
    ...selectColumn('level', '填写级别', [{ label: '最终批准时', value: null }, ...props.levels.map(l => ({ label: `第 ${l} 级`, value: l }))], 120),
    editable: p => p.data?.source === 'manual'
  },
  { ...largeTextColumn('value', '值 / 表达式', 300), flex: 1, editable: p => p.data?.source !== 'manual' }
]);

watch(
  () => props.show,
  show => {
    if (!show) return;
    rows.value = props.params.map(p => ({ _id: `param-${++sequence}`, ...p }));
    selected.value = [];
  },
  { immediate: true }
);

function save() {
  grid.value?.stopEditing();
  emit(
    'save',
    rows.value.map(({ _id, ...row }) => {
      const param: FlowParam = { name: row.name, label: row.label, type: row.type, source: row.source, required: Boolean(row.required) };
      if (row.source === 'manual' && row.level) param.level = Number(row.level);
      if (row.source !== 'manual' && row.value !== undefined && row.value !== '') param.value = row.value;
      return param;
    })
  );
  emit('update:show', false);
}

function remove() {
  rows.value = rows.value.filter(row => !selected.value.includes(row));
  selected.value = [];
}
</script>

<template>
  <NModal :show="show" preset="card" title="审批流 · 参数" style="width: min(1100px, 95vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSpace size="small">
        <NButton size="small" @click="rows.push({ _id: `param-${++sequence}`, name: '', label: '', type: 'string', required: false, source: 'manual', level: null })">新增参数</NButton>
        <NButton size="small" :disabled="!selected.length" @click="remove">删除选中行</NButton>
      </NSpace>
      <ConfigGrid ref="grid" :rows="rows" :columns="columns" :height="250" multiple row-key="_id" @select="selected = $event" />
      <NAlert v-if="problems.length" type="error" :bordered="false"><div v-for="(p, i) in problems" :key="i">{{ p }}</div></NAlert>
      <NAlert :bordered="false" type="info">取值中用 :params_参数编码 引用。SQL 表达式的写法同取值，只写表达式本身。</NAlert>
      <div class="actions">
        <NButton @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" @click="save">应用到当前草稿</NButton>
      </div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
