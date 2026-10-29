<script setup lang="ts">
/**
 * 角色人员：布局与旧系统角色管理页（`views/_builtin/permission/index.vue`）相同，左边角色列表，右边"人员列表"。
 * 旧页面的角色新增、编辑、删除和"页面权限配置"属于 config 的 `role` 配置项，不在这里。行为都在 role-members.ts。
 */
import { computed, h, onMounted, ref } from 'vue';
import { NButton, NDataTable, NEmpty, NModal, NScrollbar, NSelect, NSpace, NSpin, NTag } from 'naive-ui';
import type { DataTableColumns, SelectOption } from 'naive-ui';
import { RoleMembersModel } from '../role-members';
import type { Account, AdminDeps } from '../shared';

defineOptions({ name: 'RoleMembersPanel' });

const props = defineProps<{ deps: AdminDeps }>();

const model = new RoleMembersModel(props.deps);
const state = model.state;
const showAssign = ref(false);
const assignId = ref<string | null>(null);

/** 角色图标颜色，与旧页面相同 */
const roleColors = ['#10b981', '#f59e0b', '#3b82f6', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'];

const selectedRole = computed(() => model.selectedRole);
const options = computed<SelectOption[]>(() => model.candidates.map(c => ({ label: c.label, value: c.value })));

const columns: DataTableColumns<Account> = [
  { title: '姓名', key: 'displayName', render: row => row.displayName || row.username },
  { title: '用户名', key: 'username' },
  {
    title: '操作',
    key: 'action',
    width: 80,
    render: row =>
      h(
        NButton,
        { text: true, type: 'error', size: 'small', disabled: state.working, onClick: () => model.revoke(row.userId) },
        { default: () => '解除' }
      )
  }
];

function filterOption(pattern: string, option: SelectOption) {
  const keyword = pattern.trim().toLowerCase();
  return !keyword || String(option.label ?? '').toLowerCase().includes(keyword);
}

async function openAssign() {
  assignId.value = null;
  showAssign.value = true;
  await model.loadAccounts();
}

async function submitAssign() {
  if (!assignId.value) return;
  const ok = await model.assign(assignId.value);
  if (ok) showAssign.value = false;
}

onMounted(() => {
  void model.load();
});
</script>

<template>
  <div class="role-members h-full">
    <div class="role-panel">
      <div class="panel-header">
        <span class="panel-title">角色</span>
        <div class="text-12px text-#999">角色的新增、编辑和页面权限在配置管理中维护</div>
      </div>
      <NSpin v-if="state.loading" class="mt-8" />
      <NScrollbar v-else class="role-list">
        <div
          v-for="(role, idx) in state.roles"
          :key="role.code"
          class="role-card"
          :class="{ active: state.selected === role.code }"
          @click="model.select(role.code)"
        >
          <div class="role-icon" :style="{ background: roleColors[idx % roleColors.length] }">
            {{ role.name.charAt(0) || '角' }}
          </div>
          <div class="role-info">
            <div class="role-name">{{ role.name }}</div>
            <div class="role-code">{{ role.code }}</div>
          </div>
        </div>
        <div v-if="state.error" class="p-12px text-12px text-error">{{ state.error }}</div>
        <NEmpty v-else-if="state.roles.length === 0" description="暂无角色" class="mt-8" />
      </NScrollbar>
    </div>
    <div class="panel-divider" />
    <div class="detail-panel">
      <template v-if="selectedRole">
        <div class="detail-header">
          <NTag type="success" size="small">激活角色</NTag>
          <span class="role-title">{{ selectedRole.name }}</span>
        </div>
        <div class="tab-title">人员列表</div>
        <div class="tab-header">
          <NButton type="primary" size="small" @click="openAssign">分配人员</NButton>
        </div>
        <div class="tab-content">
          <NDataTable
            :columns="columns"
            :data="state.members"
            :loading="state.loadingMembers"
            :row-key="(row: Account) => row.userId"
            :bordered="false"
            size="small"
            :pagination="{ pageSize: 10 }"
          />
        </div>
      </template>
      <div v-else class="empty-state">请选择一个角色</div>
    </div>
    <NModal v-model:show="showAssign" preset="card" title="分配人员" class="w-380px">
      <NSelect
        v-model:value="assignId"
        :options="options"
        :filter="filterOption"
        placeholder="请选择用户"
        filterable
        clearable
        size="small"
      />
      <template #footer>
        <NSpace justify="end" size="small">
          <NButton size="small" @click="showAssign = false">取消</NButton>
          <NButton type="primary" size="small" :loading="state.working" :disabled="!assignId" @click="submitAssign">
            确定
          </NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.role-members {
  display: flex;
  background: #f5f7fa;
}

.role-panel {
  width: 280px;
  min-width: 280px;
  background: #fff;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e8e8e8;
}

.panel-header {
  padding: 16px 16px 12px;
  border-bottom: 1px solid #f0f0f0;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.role-list {
  flex: 1;
  padding: 8px;
}

.role-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.role-card:hover {
  background: #f5f5f5;
}

.role-card.active {
  background: #e6f7ff;
  border: 1px solid #91d5ff;
}

.role-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  flex-shrink: 0;
}

.role-info {
  flex: 1;
  min-width: 0;
}

.role-name {
  font-size: 14px;
  font-weight: 500;
  color: #333;
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-code {
  font-size: 12px;
  color: #999;
}

.panel-divider {
  width: 12px;
  background: #f0f0f0;
}

.detail-panel {
  flex: 1;
  background: #fff;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.role-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.tab-title {
  padding: 10px 20px 8px;
  font-size: 14px;
  color: #646cff;
  border-bottom: 2px solid #646cff;
  align-self: flex-start;
  margin-left: 20px;
}

.tab-header {
  display: flex;
  justify-content: flex-end;
  padding: 12px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.tab-content {
  flex: 1;
  padding: 16px 20px;
  overflow: auto;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
}
</style>
