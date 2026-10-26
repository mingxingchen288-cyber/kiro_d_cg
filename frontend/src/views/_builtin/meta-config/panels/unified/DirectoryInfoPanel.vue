<script setup lang="ts">
import { computed, h } from 'vue';
import { NDescriptions, NDescriptionsItem, NDataTable } from 'naive-ui';

const props = defineProps<{
  resource: any;
  resources: any[];
}>();

const emit = defineEmits<{
  (e: 'selectPage', id: number): void;
  (e: 'refresh'): void;
}>();

// 子页面列表
const childPages = computed(() => {
  return props.resources.filter(
    r => r.parentId === props.resource.id && r.resourceType === 'PAGE'
  );
});

const columns = [
  {
    title: '页面名称',
    key: 'resourceName',
    render: (row: any) => {
      return h('a', {
        style: 'color: #2080f0; cursor: pointer;',
        onClick: () => emit('selectPage', row.id)
      }, { default: () => row.resourceName });
    }
  },
  { title: 'pageCode', key: 'pageCode' },
  { title: '路由', key: 'route' },
  { title: '排序', key: 'sortOrder', width: 60 }
];
</script>

<template>
  <div class="directory-info-panel">
    <h3 class="panel-title">{{ resource.resourceName }} (目录)</h3>

    <NDescriptions bordered :column="2" size="small" class="info-section">
      <NDescriptionsItem label="名称">{{ resource.resourceName }}</NDescriptionsItem>
      <NDescriptionsItem label="编码">{{ resource.pageCode || '—' }}</NDescriptionsItem>
      <NDescriptionsItem label="图标">{{ resource.icon || '—' }}</NDescriptionsItem>
      <NDescriptionsItem label="排序">{{ resource.sortOrder }}</NDescriptionsItem>
    </NDescriptions>

    <div class="child-pages">
      <h4>子页面 ({{ childPages.length }})</h4>
      <NDataTable
        v-if="childPages.length > 0"
        :columns="columns"
        :data="childPages"
        :row-key="(row: any) => row.id"
        size="small"
        :bordered="false"
        :max-height="400"
      />
      <p v-else class="empty-hint">暂无子页面</p>
    </div>
  </div>
</template>

<style scoped>
.directory-info-panel {
  max-width: 800px;
}
.panel-title {
  margin: 0 0 16px;
  font-size: 18px;
}
.info-section {
  margin-bottom: 24px;
}
.child-pages {
  margin-top: 16px;
}
.child-pages h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.empty-hint {
  color: #999;
  font-size: 13px;
}
</style>
