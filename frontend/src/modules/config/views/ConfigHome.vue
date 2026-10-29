<script setup lang="ts">
/**
 * `/config` 的路由组件，同旧系统 meta-config/index.vue：NTabs 切换各配置界面，`?tab=` 指定打开哪一个。
 * 旧系统有"一体化配置""Lookup管理"两个 Tab，角色权限是单独的页面（views/_builtin/permission）；
 * 新平台配置只有 `/config` 一个入口（C11），所以把角色权限、字典和全部配置项也放在这里。
 * FC-01：非管理员只显示提示，不读取配置。
 */
import { ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { NResult, NTabPane, NTabs } from 'naive-ui';
import { canConfigure, useConfigShell } from '../index';
import UnifiedConfigPage from './UnifiedConfigPage.vue';
import LookupPanel from './LookupPanel.vue';
import DictPanel from './DictPanel.vue';
import ConfigItemsPanel from './ConfigItemsPanel.vue';
import RolePermissionPage from '../role/RolePermissionPage.vue';

defineOptions({ name: 'ConfigHome' });

const shell = useConfigShell();
const route = useRoute();
const tabs = ['unified', 'lookup', 'permission', 'dict', 'items'];
const fromQuery = () => (typeof route.query.tab === 'string' && tabs.includes(route.query.tab) ? route.query.tab : 'unified');
const activeTab = ref(fromQuery());
watch(
  () => route.query.tab,
  () => (activeTab.value = fromQuery())
);
</script>

<template>
  <div v-if="canConfigure(shell.session)" class="meta-config-page">
    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="unified" tab="一体化配置" display-directive="show:lazy">
        <UnifiedConfigPage />
      </NTabPane>
      <NTabPane name="lookup" tab="Lookup管理" display-directive="show:lazy">
        <LookupPanel />
      </NTabPane>
      <NTabPane name="permission" tab="角色权限" display-directive="show:lazy">
        <RolePermissionPage />
      </NTabPane>
      <NTabPane name="dict" tab="字典管理" display-directive="show:lazy">
        <DictPanel />
      </NTabPane>
      <NTabPane name="items" tab="全部配置项" display-directive="show:lazy">
        <ConfigItemsPanel @open="(tab: string) => (activeTab = tab)" />
      </NTabPane>
    </NTabs>
  </div>
  <NResult v-else status="403" title="只有管理员角色可以使用配置功能" description="请切换到管理员角色后再打开配置。" class="mt-16" />
</template>

<style scoped>
.meta-config-page {
  height: 100%;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  background: #f5f7fb;
}
.meta-config-page :deep(.n-tabs) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.meta-config-page :deep(.n-tabs .n-tabs-pane-wrapper) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.meta-config-page :deep(.n-tabs .n-tab-pane) {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
