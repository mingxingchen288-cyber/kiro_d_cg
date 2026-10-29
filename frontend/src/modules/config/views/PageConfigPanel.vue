<script setup lang="ts">
/**
 * 页面配置，同旧系统 PageConfigPanel.vue：标题、"预览页面""删除页面"，pageCode 副标题，折叠区
 * 基本信息、表与列、页面行为、表单布局、导出配置、审批流。页面配置项（C06 第 3 节）由本组件读取，各区共用；
 * 实体、规则、操作、导出、审批流是各自的配置项，由各区读取和保存。
 */
import { computed, onMounted, ref } from 'vue';
import { NAlert, NButton, NCollapse, NCollapseItem, NPopconfirm, NSpace, NSpin } from 'naive-ui';
import SectionApproval from '../approval/SectionApproval.vue';
import { type PageCatalog, loadPageCatalog } from '../core/catalog';
import { useConfigContext } from '../core/context';
import { errorText } from '../core/errors';
import { ItemEditor } from '../core/item-editor';
import SectionFormLayout from '../layout/SectionFormLayout.vue';
import ProblemList from '../components/ProblemList.vue';
import SectionBasicInfo from './SectionBasicInfo.vue';
import SectionBehavior from './SectionBehavior.vue';
import SectionExport from './SectionExport.vue';
import SectionTables from './SectionTables.vue';

const props = defineProps<{ pageCode: string; title: string }>();
const emit = defineEmits<{ refresh: [] }>();
const { shell, store, notify } = useConfigContext();
const page = new ItemEditor(store, 'page', notify);
const catalog = ref<PageCatalog | null>(null);
const loadError = ref('');
const content = computed(() => page.state.current?.content ?? null);

async function load() {
  loadError.value = '';
  await page.open(props.pageCode);
  try {
    catalog.value = await loadPageCatalog(store, props.pageCode);
  } catch (error) {
    loadError.value = `页面表格读取失败：${errorText(error)}`;
  }
}

function preview() {
  shell.tabs.open(`/page/${props.pageCode}`, content.value?.title ?? props.title);
}

async function removePage() {
  if (await page.remove()) emit('refresh');
}

onMounted(load);
</script>

<template>
  <div class="page-config-panel">
    <div class="panel-header">
      <h3 class="panel-title">{{ content?.title ?? title }}</h3>
      <NSpace size="small">
        <NButton size="small" @click="preview">预览页面</NButton>
        <NPopconfirm @positive-click="removePage">
          <template #trigger><NButton size="small" type="error" quaternary>删除页面</NButton></template>
          确定删除页面配置「{{ content?.title ?? title }}」？仍被菜单、角色、审批流等引用时不能删除，会列出引用它的配置。
        </NPopconfirm>
      </NSpace>
    </div>
    <p class="panel-subtitle">pageCode: {{ pageCode }}<span v-if="page.state.current"> · 版本 {{ page.state.current.version }}</span></p>
    <NAlert v-if="loadError" type="error" :bordered="false" class="mb-8">{{ loadError }}</NAlert>
    <ProblemList :problems="page.state.problems" />
    <NSpin :show="page.state.loading">
      <NCollapse v-if="content" :default-expanded-names="['basic', 'tables']">
        <NCollapseItem title="基本信息" name="basic">
          <template #header-extra><span class="section-summary">/page/{{ pageCode }}</span></template>
          <SectionBasicInfo :page="page" @saved="emit('refresh')" />
        </NCollapseItem>
        <NCollapseItem title="表与列" name="tables">
          <template #header-extra><span class="section-summary">{{ catalog?.tables.length ?? 0 }} 张表</span></template>
          <SectionTables v-if="catalog" :page="page" :catalog="catalog" @reload="load" />
        </NCollapseItem>
        <NCollapseItem title="页面行为" name="behavior">
          <template #header-extra><span class="section-summary">{{ catalog?.tables.length ?? 0 }} 个区域</span></template>
          <SectionBehavior v-if="catalog" :page="page" :catalog="catalog" />
        </NCollapseItem>
        <NCollapseItem title="表单布局" name="layout">
          <SectionFormLayout v-if="catalog" :page="page" :catalog="catalog" />
        </NCollapseItem>
        <NCollapseItem title="导出配置" name="export">
          <SectionExport :page-code="pageCode" />
        </NCollapseItem>
        <NCollapseItem title="审批流" name="approval">
          <SectionApproval :page-code="pageCode" />
        </NCollapseItem>
      </NCollapse>
    </NSpin>
  </div>
</template>

<style scoped>
.page-config-panel { width: 100%; }
.panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.panel-title { margin: 0; font-size: 18px; }
.panel-subtitle { margin: 0 0 16px; color: #999; font-size: 13px; }
.section-summary { font-size: 12px; color: #999; }
</style>
