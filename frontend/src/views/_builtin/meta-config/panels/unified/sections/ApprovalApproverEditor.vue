<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NModal, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { ApprovalApprover, ApprovalCatalog } from '@/service/api/approval-config';
import ApprovalConfigGrid from './ApprovalConfigGrid.vue';
import { largeTextColumn, selectColumn } from './approval-config-columns';

const props = defineProps<{ show: boolean; entryName: string; approvers: ApprovalApprover[]; catalog: ApprovalCatalog }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [rows: ApprovalApprover[]] }>();
const rows = ref<ApprovalApprover[]>([]);
const selected = ref<ApprovalApprover[]>([]);
const grid = ref<InstanceType<typeof ApprovalConfigGrid>>();
const columns = computed<ColDef[]>(() => [
  selectColumn('type', '审批对象', [{ label: '人员', value: 'USER' }, { label: '角色', value: 'ROLE' }, { label: 'SQL 选人', value: 'SQL' }], 110),
  { ...selectColumn('userId', '指定人员', props.catalog.users.map(user => ({ label: `${user.realName || user.username} (${user.id})`, value: Number(user.id) })), 200), editable: params => params.data?.type === 'USER' },
  { ...selectColumn('roleId', '指定角色', props.catalog.roles.map(role => ({ label: `${role.roleName || role.roleCode} (${role.id})`, value: Number(role.id) })), 200), editable: params => params.data?.type === 'ROLE' },
  { ...largeTextColumn('sql', '取人员 ID 的只读 SQL', 360), editable: params => params.data?.type === 'SQL', flex: 1 }
]);
watch(() => props.show, show => { if (show) { rows.value = props.approvers.map(row => ({ ...row })); selected.value = []; } }, { immediate: true });
function save() {
  grid.value?.stopEditing();
  emit('save', rows.value.map(row => ({
    type: row.type, userId: row.type === 'USER' ? row.userId : null,
    roleId: row.type === 'ROLE' ? row.roleId : null, sql: row.type === 'SQL' ? row.sql : ''
  })));
  emit('update:show', false);
}
function remove() { rows.value = rows.value.filter(row => !selected.value.includes(row)); selected.value = []; }
</script>

<template>
  <NModal :show="show" preset="card" :title="`${entryName || '审批入口'} · 审批人`" style="width: min(1100px, 95vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSpace size="small"><NButton size="small" @click="rows.push({ type: 'USER', userId: null, roleId: null, sql: '' })">新增审批对象</NButton><NButton size="small" :disabled="!selected.length" @click="remove">删除选中行</NButton></NSpace>
      <ApprovalConfigGrid ref="grid" :rows="rows" :columns="columns" :height="250" multiple @select="selected = $event" />
      <NAlert :bordered="false" type="info">同一入口可配置多个人员、角色或 SQL。命中的同级入口合并审批人，再按该级的会签／或签方式处理；部门限制在入口行配置。</NAlert>
      <div class="actions"><NButton @click="emit('update:show', false)">取消</NButton><NButton type="primary" @click="save">应用到当前草稿</NButton></div>
    </NSpace>
  </NModal>
</template>

<style scoped>.actions { display: flex; justify-content: flex-end; gap: 8px; }</style>
