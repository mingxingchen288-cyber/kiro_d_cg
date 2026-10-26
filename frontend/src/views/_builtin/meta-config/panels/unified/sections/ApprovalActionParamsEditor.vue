<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NModal, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { ApprovalActionParam } from '@/service/api/approval-config';
import ApprovalConfigGrid from './ApprovalConfigGrid.vue';
import { booleanColumn, largeTextColumn, selectColumn } from './approval-config-columns';

const props = defineProps<{ show: boolean; params: ApprovalActionParam[]; manual: boolean }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [rows: ApprovalActionParam[]] }>();
const rows = ref<ApprovalActionParam[]>([]);
const selected = ref<ApprovalActionParam[]>([]);
const grid = ref<InstanceType<typeof ApprovalConfigGrid>>();
const columns = computed<ColDef[]>(() => [
  { field: 'name', headerName: '参数编码', width: 150 }, { field: 'label', headerName: '显示名称', width: 140 },
  selectColumn('type', '类型', [{ label: '文本', value: 'STRING' }, { label: '数字', value: 'NUMBER' }, { label: '是／否', value: 'BOOLEAN' }, { label: '日期', value: 'DATE' }], 100),
  booleanColumn('required', '必填'),
  selectColumn('source', '参数来源', [{ label: '固定值', value: 'CONSTANT' }, { label: '字段表达式', value: 'EXPRESSION' }, ...(props.manual ? [{ label: '审批时填写', value: 'MANUAL' }] : [])], 150),
  { ...largeTextColumn('value', '值 / 表达式 / 填写默认值', 300), flex: 1 }
]);
watch(() => props.show, show => { if (show) { rows.value = props.params.map(row => ({ ...row })); selected.value = []; } }, { immediate: true });
function save() { grid.value?.stopEditing(); emit('save', rows.value.map(row => ({ ...row }))); emit('update:show', false); }
function remove() { rows.value = rows.value.filter(row => !selected.value.includes(row)); selected.value = []; }
</script>

<template>
  <NModal :show="show" preset="card" title="审批动作 · 参数映射" style="width: min(1100px, 95vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSpace size="small"><NButton size="small" @click="rows.push({ name: '', label: '', type: 'STRING', required: false, source: manual ? 'MANUAL' : 'CONSTANT', value: '' })">新增参数</NButton><NButton size="small" :disabled="!selected.length" @click="remove">删除选中行</NButton></NSpace>
      <ApprovalConfigGrid ref="grid" :rows="rows" :columns="columns" :height="250" multiple @select="selected = $event" />
      <NAlert :bordered="false" type="info">表达式可引用 {待审值.字段编码}、{原值.字段编码}、{用户.id} 和 {自定义.数据项}。审批时填写的参数必须使用“审批时填写参数”执行方式。</NAlert>
      <div class="actions"><NButton @click="emit('update:show', false)">取消</NButton><NButton type="primary" @click="save">应用到当前草稿</NButton></div>
    </NSpace>
  </NModal>
</template>

<style scoped>.actions { display: flex; justify-content: flex-end; gap: 8px; }</style>
