<script setup lang="ts">
/**
 * `/admin` 和 `/admin/<key>` 的路由组件，`section` 由 index.ts 的路由固定传入。
 * - FM-01：当前角色不是管理员时只显示提示，不创建各功能、不调用接口。
 * - 给出 `section` 时只显示这个功能；没有时用 Tab 显示全部功能。
 */
import { computed } from 'vue';
import { NTabPane, NTabs } from 'naive-ui';
import { ADMIN_SECTIONS, type AdminSection, adminSection, canUseAdmin, useAdminShell } from '../index';
import { createAdminDeps } from '../shared';
import AccountsPanel from './AccountsPanel.vue';
import CommandReviewPanel from './CommandReviewPanel.vue';
import DeliveriesPanel from './DeliveriesPanel.vue';
import DepartmentsPanel from './DepartmentsPanel.vue';
import RoleMembersPanel from './RoleMembersPanel.vue';
import { useConfirm } from './confirm';

defineOptions({ name: 'AdminRoute' });

const props = defineProps<{ section?: string }>();
const section = adminSection(props.section);

const shell = useAdminShell();
const deps = createAdminDeps(shell, useConfirm());
const allowed = computed(() => canUseAdmin(shell.session.role.value));

const PANELS = {
  accounts: AccountsPanel,
  departments: DepartmentsPanel,
  'role-members': RoleMembersPanel,
  deliveries: DeliveriesPanel,
  'command-review': CommandReviewPanel
} satisfies Record<AdminSection, unknown>;
</script>

<template>
  <div class="h-full">
    <div v-if="!allowed" class="h-full flex-center text-#999">只有管理员角色可以使用系统管理</div>
    <component :is="PANELS[section]" v-else-if="section" :deps="deps" />
    <NTabs v-else type="line" animated class="admin-tabs h-full" pane-class="admin-tabs__pane">
      <NTabPane
        v-for="item in ADMIN_SECTIONS"
        :key="item.key"
        :name="item.key"
        :tab="item.title"
        display-directive="show:lazy"
      >
        <component :is="PANELS[item.key]" :deps="deps" />
      </NTabPane>
    </NTabs>
  </div>
</template>

<style scoped>
.admin-tabs {
  display: flex;
  flex-direction: column;
}

:deep(.admin-tabs__pane) {
  flex: 1;
  min-height: 0;
}
</style>
