<script setup lang="ts">
/**
 * 审批人弹窗，同旧系统 ApprovalApproverEditor.vue：每行一个审批对象（人员、角色、SQL 选人）。
 * SQL 选人进入该级时执行，只能是查询语句，返回用户编号；绑定变量写成"名称=取值"，每行一个（C06 7.3 的 `binds`）。
 */
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NModal, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { Option } from '../core/catalog';
import type { Approver } from '../core/types';
import ConfigGrid from '../components/ConfigGrid.vue';
import { largeTextColumn, selectColumn } from '../components/grid-columns';

interface Row {
  type: 'user' | 'role' | 'sql';
  userId: string | null;
  role: string | null;
  sql: string;
  binds: string;
}

const props = defineProps<{ show: boolean; nodeName: string; approvers: Approver[]; roles: Option[]; users: Option[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [rows: Approver[]] }>();
const rows = ref<Row[]>([]);
const selected = ref<Row[]>([]);
const grid = ref<InstanceType<typeof ConfigGrid>>();

const columns = computed<ColDef[]>(() => [
  selectColumn('type', '审批对象', [{ label: '人员', value: 'user' }, { label: '角色', value: 'role' }, { label: 'SQL 选人', value: 'sql' }], 110),
  { ...selectColumn('userId', '指定人员', props.users, 200), editable: p => p.data?.type === 'user' },
  { ...selectColumn('role', '指定角色', props.roles, 200), editable: p => p.data?.type === 'role' },
  { ...largeTextColumn('sql', '取人员 ID 的只读 SQL', 360), editable: p => p.data?.type === 'sql', flex: 1 },
  { ...largeTextColumn('binds', '绑定变量（名称=取值，每行一个）', 220), editable: p => p.data?.type === 'sql' }
]);

const toText = (binds: Record<string, string> | undefined) =>
  Object.entries(binds ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');
const toBinds = (text: string) =>
  Object.fromEntries(
    text
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean)
      .map(line => [line.slice(0, line.indexOf('=')).trim(), line.slice(line.indexOf('=') + 1).trim()])
      .filter(([k]) => k)
  );

watch(
  () => props.show,
  show => {
    if (!show) return;
    rows.value = props.approvers.map(a => ({
      type: a.type,
      userId: a.type === 'user' ? a.userId : null,
      role: a.type === 'role' ? a.role : null,
      sql: a.type === 'sql' ? a.sql : '',
      binds: a.type === 'sql' ? toText(a.binds) : ''
    }));
    selected.value = [];
  },
  { immediate: true }
);

function save() {
  grid.value?.stopEditing();
  const approvers: Approver[] = rows.value.map(row => {
    if (row.type === 'user') return { type: 'user', userId: row.userId ?? '' };
    if (row.type === 'role') return { type: 'role', role: row.role ?? '' };
    const binds = toBinds(row.binds);
    return Object.keys(binds).length ? { type: 'sql', sql: row.sql, binds } : { type: 'sql', sql: row.sql };
  });
  emit('save', approvers);
  emit('update:show', false);
}

function remove() {
  rows.value = rows.value.filter(row => !selected.value.includes(row));
  selected.value = [];
}
</script>

<template>
  <NModal :show="show" preset="card" :title="`${nodeName || '审批节点'} · 审批人`" style="width: min(1100px, 95vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSpace size="small">
        <NButton size="small" @click="rows.push({ type: 'role', userId: null, role: null, sql: '', binds: '' })">新增审批对象</NButton>
        <NButton size="small" :disabled="!selected.length" @click="remove">删除选中行</NButton>
      </NSpace>
      <ConfigGrid ref="grid" :rows="rows" :columns="columns" :height="250" multiple @select="selected = $event" />
      <NAlert :bordered="false" type="info">
        同一节点可配置多个人员、角色或 SQL。或签：任一审批人通过即可；会签：每个审批人都要通过，按角色配置时这个角色里任一账号处理就算这个角色处理了。部门限制在节点行配置。
      </NAlert>
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
