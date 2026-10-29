<script setup lang="ts">
/**
 * 审批流通知弹窗（C06 7.1 `notify`）：每行一个事件和通知对象。通知文字由平台按固定格式生成，不在这里配置（approval AP-17）。
 */
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NModal, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { Option } from '../core/catalog';
import type { NotifyRule } from '../core/types';
import ConfigGrid from '../components/ConfigGrid.vue';
import { selectColumn } from '../components/grid-columns';

interface Row {
  _id: string;
  event: NotifyRule['event'];
  to: 'levelApprovers' | 'applicant' | 'users' | 'role';
  role: string | null;
  users: string;
}

const props = defineProps<{ show: boolean; rules: NotifyRule[]; roles: Option[]; problems: string[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [rules: NotifyRule[]] }>();
const rows = ref<Row[]>([]);
const selected = ref<Row[]>([]);
const grid = ref<InstanceType<typeof ConfigGrid>>();
let sequence = 0;

const columns = computed<ColDef[]>(() => [
  selectColumn(
    'event',
    '事件',
    [
      { label: '提交审批', value: 'submitted' },
      { label: '进入下一级', value: 'levelEntered' },
      { label: '审批通过', value: 'passed' },
      { label: '审批驳回', value: 'rejected' },
      { label: '撤回', value: 'withdrawn' }
    ],
    140
  ),
  selectColumn(
    'to',
    '通知对象',
    [
      { label: '本级审批人', value: 'levelApprovers' },
      { label: '申请人', value: 'applicant' },
      { label: '指定人员', value: 'users' },
      { label: '指定角色', value: 'role' }
    ],
    140
  ),
  { ...selectColumn('role', '指定角色', props.roles, 200), editable: p => p.data?.to === 'role' },
  { field: 'users', headerName: '指定人员（人员编号，逗号分隔）', flex: 1, editable: p => p.data?.to === 'users' }
]);

watch(
  () => props.show,
  show => {
    if (!show) return;
    rows.value = props.rules.map(r => ({
      _id: `notify-${++sequence}`,
      event: r.event,
      to: typeof r.to === 'string' ? r.to : 'users' in r.to ? 'users' : 'role',
      role: typeof r.to === 'object' && 'role' in r.to ? r.to.role : null,
      users: typeof r.to === 'object' && 'users' in r.to ? r.to.users.join(',') : ''
    }));
    selected.value = [];
  },
  { immediate: true }
);

function save() {
  grid.value?.stopEditing();
  emit(
    'save',
    rows.value.map(row => {
      if (row.to === 'users') return { event: row.event, to: { users: row.users.split(/[,，]/).map(u => u.trim()).filter(Boolean) } };
      if (row.to === 'role') return { event: row.event, to: { role: row.role ?? '' } };
      return { event: row.event, to: row.to };
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
  <NModal :show="show" preset="card" title="审批流 · 通知" style="width: min(900px, 95vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSpace size="small">
        <NButton size="small" @click="rows.push({ _id: `notify-${++sequence}`, event: 'submitted', to: 'levelApprovers', role: null, users: '' })">新增通知</NButton>
        <NButton size="small" :disabled="!selected.length" @click="remove">删除选中行</NButton>
      </NSpace>
      <ConfigGrid ref="grid" :rows="rows" :columns="columns" :height="220" multiple row-key="_id" @select="selected = $event" />
      <NAlert v-if="problems.length" type="error" :bordered="false"><div v-for="(p, i) in problems" :key="i">{{ p }}</div></NAlert>
      <NAlert :bordered="false" type="info">通知文字由平台按固定格式生成，不在这里配置。</NAlert>
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
