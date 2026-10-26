<script setup lang="ts">
import { provide, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { NTabPane, NTabs } from 'naive-ui';
import UnifiedConfigPage from './panels/unified/UnifiedConfigPage.vue';
import LookupPanel from './panels/LookupPanel.vue';

const route = useRoute();
const activeTab = ref(typeof route.query.tab === 'string' ? route.query.tab : 'unified');

/** 跳转到指定 tab 并携带过滤条件 */
const filterState = ref<{ tab: string; pageCode: string } | null>(null);

function navigateTo(tab: string, pageCode: string) {
  filterState.value = { tab, pageCode };
  activeTab.value = tab;
}

provide('navigateTo', navigateTo);
provide('filterState', filterState);

watch(
  () => route.query.tab,
  tab => {
    if (typeof tab === 'string' && tab) {
      activeTab.value = tab;
    }
  }
);
</script>

<template>
  <div class="meta-config-page">
    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="unified" tab="一体化配置">
        <UnifiedConfigPage />
      </NTabPane>
      <NTabPane name="lookup" tab="Lookup管理">
        <LookupPanel />
      </NTabPane>
    </NTabs>
  </div>
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
