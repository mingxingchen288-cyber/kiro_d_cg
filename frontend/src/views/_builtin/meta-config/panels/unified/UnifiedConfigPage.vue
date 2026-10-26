<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { NButton, NInput, NLayout, NLayoutSider, NTree, useMessage } from 'naive-ui';
import type { TreeOption } from 'naive-ui';
import { fetchAllResources, saveResource } from '@/service/api/meta-config';
import PageConfigPanel from './PageConfigPanel.vue';
import DirectoryInfoPanel from './DirectoryInfoPanel.vue';

const message = useMessage();
const loading = ref(false);
const rawResources = ref<any[]>([]);
const selectedKey = ref<number | null>(null);
const searchText = ref('');

// 构建 NTree 的数据
const treeData = computed<TreeOption[]>(() => {
  const resources = rawResources.value;
  const map = new Map<number, TreeOption & { raw: any }>();

  for (const r of resources) {
    map.set(r.id, {
      key: r.id,
      label: r.resourceName,
      prefix: () => r.resourceType === 'DIRECTORY' ? '📁' : '📄',
      raw: r,
      children: []
    });
  }

  const roots: TreeOption[] = [];
  for (const r of resources) {
    const node = map.get(r.id)!;
    if (r.parentId && map.has(r.parentId)) {
      (map.get(r.parentId)!.children as TreeOption[]).push(node);
    } else {
      roots.push(node);
    }
  }

  // 清理空 children（NTree 不显示展开箭头）
  for (const node of map.values()) {
    if ((node.children as TreeOption[]).length === 0) {
      delete node.children;
    }
  }

  return roots;
});

// 搜索过滤
const filteredTreeData = computed(() => {
  if (!searchText.value.trim()) return treeData.value;
  const keyword = searchText.value.trim().toLowerCase();
  return filterTree(treeData.value, keyword);
});

function filterTree(nodes: TreeOption[], keyword: string): TreeOption[] {
  const result: TreeOption[] = [];
  for (const node of nodes) {
    const label = (node.label || '').toLowerCase();
    const raw = (node as any).raw;
    const pageCode = (raw?.pageCode || '').toLowerCase();
    const match = label.includes(keyword) || pageCode.includes(keyword);

    if (node.children && (node.children as TreeOption[]).length > 0) {
      const filteredChildren = filterTree(node.children as TreeOption[], keyword);
      if (filteredChildren.length > 0 || match) {
        result.push({ ...node, children: filteredChildren.length > 0 ? filteredChildren : node.children });
      }
    } else if (match) {
      result.push(node);
    }
  }
  return result;
}

// 当前选中的资源
const selectedResource = computed(() => {
  if (!selectedKey.value) return null;
  return rawResources.value.find(r => r.id === selectedKey.value) || null;
});

const isPage = computed(() => selectedResource.value?.resourceType === 'PAGE');
const isDirectory = computed(() => selectedResource.value?.resourceType === 'DIRECTORY');

// 加载资源树
async function loadResources() {
  loading.value = true;
  try {
    rawResources.value = await fetchAllResources();
  } catch {
    message.error('加载菜单失败');
  } finally {
    loading.value = false;
  }
}

function handleSelect(keys: Array<string | number>) {
  selectedKey.value = keys.length > 0 ? Number(keys[0]) : null;
}

// 向导弹窗
const showWizard = ref(false);
const wizardParentId = ref<number | null>(null);
const wizardParentName = ref('');

function openWizard() {
  if (selectedResource.value?.resourceType === 'DIRECTORY') {
    wizardParentId.value = selectedResource.value.id;
    wizardParentName.value = selectedResource.value.resourceName || '';
  } else if (selectedResource.value?.parentId) {
    wizardParentId.value = selectedResource.value.parentId;
    const parent = rawResources.value.find(r => r.id === selectedResource.value!.parentId);
    wizardParentName.value = parent?.resourceName || '';
  } else {
    wizardParentId.value = -1;
    wizardParentName.value = '根目录（顶级）';
  }
  showWizard.value = true;
}

function onWizardSuccess() {
  showWizard.value = false;
  loadResources();
}

async function handleTreeDrop({ node, dragNode, dropPosition }: any) {
  // node: 目标节点, dragNode: 被拖拽的节点, dropPosition: 'before'|'inside'|'after'
  const dragId = dragNode.key as number;
  const targetId = node.key as number;
  const dragResource = rawResources.value.find(r => r.id === dragId);
  const targetResource = rawResources.value.find(r => r.id === targetId);
  if (!dragResource || !targetResource) return;

  if (dropPosition === 'inside') {
    // 拖入目标内部 → 改变父级
    dragResource.parentId = targetId;
  } else {
    // before/after → 同级排序，父级和目标一致
    dragResource.parentId = targetResource.parentId;
  }

  // 重算同级排序
  const siblings = rawResources.value
    .filter(r => r.parentId === dragResource.parentId && r.id !== dragId)
    .sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));

  const targetIndex = siblings.findIndex(r => r.id === targetId);
  const insertAt = dropPosition === 'after' ? targetIndex + 1 : targetIndex;
  siblings.splice(insertAt < 0 ? siblings.length : insertAt, 0, dragResource);

  // 更新排序号
  for (let i = 0; i < siblings.length; i++) {
    siblings[i].sortOrder = i;
  }

  // 保存变更的资源
  try {
    await Promise.all(siblings.map(r => saveResource(r)));
    await loadResources();
  } catch {
    message.error('排序保存失败');
  }
}

onMounted(loadResources);
</script>

<template>
  <div class="unified-config">
    <!-- 左侧目录树 -->
    <div class="unified-config__sider">
      <div class="sider-search">
        <NInput v-model:value="searchText" placeholder="搜索菜单..." size="small" clearable />
      </div>
      <div class="sider-tree">
        <NTree
          :data="filteredTreeData"
          :selected-keys="selectedKey ? [selectedKey] : []"
          :loading="loading"
          block-line
          selectable
          draggable
          default-expand-all
          @update:selected-keys="handleSelect"
          @drop="handleTreeDrop"
        />
      </div>
      <div class="sider-footer">
        <NButton type="primary" size="small" block @click="openWizard">+ 新增页面</NButton>
      </div>
    </div>

    <!-- 右侧配置面板 -->
    <div class="unified-config__content">
      <PageConfigPanel
        v-if="isPage && selectedResource"
        :key="selectedResource.id"
        :resource="selectedResource"
        @refresh="loadResources"
      />
      <DirectoryInfoPanel
        v-else-if="isDirectory && selectedResource"
        :key="selectedResource.id"
        :resource="selectedResource"
        :resources="rawResources"
        @select-page="(id: number) => (selectedKey = id)"
        @refresh="loadResources"
      />
      <div v-else class="empty-state">
        <p>请从左侧选择一个页面或目录</p>
      </div>
    </div>

    <!-- 向导弹窗 -->
    <NModal
      v-model:show="showWizard"
      preset="card"
      title="页面创建向导"
      :style="{ width: '900px', maxHeight: '85vh' }"
      :body-style="{ overflow: 'auto' }"
      :mask-closable="false"
    >
      <WizardPanel
        :default-parent-id="wizardParentId"
        :default-parent-name="wizardParentName"
        @success="onWizardSuccess"
      />
    </NModal>
  </div>
</template>

<script lang="ts">
import { NModal } from 'naive-ui';
import WizardPanel from '../WizardPanel.vue';
export default { components: { NModal, WizardPanel } };
</script>

<style scoped>
.unified-config {
  height: 100%;
  display: flex;
  overflow: hidden;
}

.unified-config__sider {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e8e8e8;
  background: #fafafa;
}

.sider-search {
  padding: 12px 12px 8px;
  flex-shrink: 0;
}

.sider-tree {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.sider-footer {
  flex-shrink: 0;
  padding: 8px 12px 12px;
  border-top: 1px solid #e8e8e8;
}

.unified-config__content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  min-width: 0;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 300px;
  color: #999;
  font-size: 14px;
}
</style>
