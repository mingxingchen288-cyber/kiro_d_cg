<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { NButton, NCollapse, NCollapseItem, NSpace, useDialog, useMessage } from 'naive-ui';
import { useRouter } from 'vue-router';
import { fetchTablesByPageCode, fetchAllPageComponents } from '@/service/api/meta-config';
import { cascadeDeletePage } from '@/service/api/wizard';
import SectionBasicInfo from './sections/SectionBasicInfo.vue';
import SectionTables from './sections/SectionTables.vue';
import SectionBehavior from './sections/SectionBehavior.vue';
import SectionExport from './sections/SectionExport.vue';
import SectionApproval from './sections/SectionApproval.vue';

const props = defineProps<{
  resource: any;
}>();

const emit = defineEmits<{
  (e: 'refresh'): void;
}>();

const router = useRouter();
const message = useMessage();
const dialog = useDialog();
const loading = ref(false);

// 关联数据
const tables = ref<any[]>([]);
const components = ref<any[]>([]);

const pageCode = ref('');

async function loadPageData() {
  loading.value = true;
  pageCode.value = props.resource.pageCode || '';
  try {
    // 加载关联表
    if (pageCode.value) {
      tables.value = await fetchTablesByPageCode(pageCode.value);
      // 加载组件
      const allComps = await fetchAllPageComponents();
      components.value = (allComps || []).filter(
        (c: any) => c.pageCode === pageCode.value && c.componentType !== 'LAYOUT'
      );
    }
  } catch (e: any) {
    message.error(e?.message || '加载页面数据失败');
  } finally {
    loading.value = false;
  }
}

function handlePreview() {
  const route = props.resource.route;
  if (route) {
    window.open(route, '_blank');
  } else {
    message.warning('该页面未配置路由');
  }
}

function handleDelete() {
  const pc = props.resource.pageCode;
  if (!pc) return;
  dialog.warning({
    title: '删除确认',
    content: `确定删除页面「${props.resource.resourceName}」及其所有关联元数据？此操作不可撤销。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await cascadeDeletePage(pc);
        message.success('页面已删除');
        emit('refresh');
      } catch (e: any) {
        message.error(e?.message || '删除失败');
      }
    }
  });
}

onMounted(loadPageData);
</script>

<template>
  <div class="page-config-panel">
    <!-- 头部 -->
    <div class="panel-header">
      <h3 class="panel-title">{{ resource.resourceName }}</h3>
      <NSpace size="small">
        <NButton size="small" @click="handlePreview">预览页面</NButton>
        <NButton size="small" type="error" quaternary @click="handleDelete">删除页面</NButton>
      </NSpace>
    </div>
    <p class="panel-subtitle">pageCode: {{ resource.pageCode }}</p>

    <!-- 可折叠区域 -->
    <NCollapse :default-expanded-names="['basic', 'tables']">
      <!-- 基本信息 -->
      <NCollapseItem title="基本信息" name="basic">
        <template #header-extra>
          <span class="section-summary">{{ resource.route || '未配置路由' }}</span>
        </template>
        <SectionBasicInfo :resource="resource" @refresh="emit('refresh')" />
      </NCollapseItem>

      <!-- 表与列 -->
      <NCollapseItem title="表与列" name="tables">
        <template #header-extra>
          <span class="section-summary">
            {{ tables.length }} 张表
          </span>
        </template>
        <SectionTables :page-code="pageCode" :tables="tables" :components="components" @refresh="loadPageData" />
      </NCollapseItem>

      <!-- 页面行为 -->
      <NCollapseItem title="页面行为" name="behavior">
        <template #header-extra>
          <span class="section-summary">
            {{ components.length }} 个组件
          </span>
        </template>
        <SectionBehavior :page-code="pageCode" :components="components" @refresh="loadPageData" />
      </NCollapseItem>

      <!-- 导出配置 -->
      <NCollapseItem title="导出配置" name="export">
        <SectionExport :page-code="pageCode" :tables="tables" :components="components" />
      </NCollapseItem>

      <!-- 审批流 -->
      <NCollapseItem title="审批流" name="approval">
        <SectionApproval :page-code="pageCode" />
      </NCollapseItem>
    </NCollapse>
  </div>
</template>

<style scoped>
.page-config-panel {
  width: 100%;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.panel-title {
  margin: 0;
  font-size: 18px;
}
.panel-subtitle {
  margin: 0 0 16px;
  color: #999;
  font-size: 13px;
}
.section-summary {
  font-size: 12px;
  color: #999;
}
</style>
