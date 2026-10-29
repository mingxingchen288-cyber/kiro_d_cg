<script setup lang="ts">
/**
 * 一体化配置，同旧系统 UnifiedConfigPage.vue：左侧 240px 菜单树（可搜索、可拖动排序），底部"+ 新增页面"打开向导；
 * 右侧选页面时为页面配置，选分组时为目录信息。菜单树来自 `menu` 配置项，拖动后立即保存该菜单配置项（先校验）。
 */
import { computed, h, onMounted, ref } from 'vue';
import { NButton, NInput, NModal, NTree } from 'naive-ui';
import type { TreeDropInfo, TreeOption } from 'naive-ui';
import { useConfigContext } from '../core/context';
import { errorText } from '../core/errors';
import type { TypedItem } from '../core/store';
import WizardPanel from '../wizard/WizardPanel.vue';
import DirectoryInfoPanel from './DirectoryInfoPanel.vue';
import PageConfigPanel from './PageConfigPanel.vue';
import { type TreeNode, buildTree, filterTree, iconOf, moveNode } from './menu-tree';

const { store, notify } = useConfigContext();
const loading = ref(false);
const menus = ref<Array<TypedItem<'menu'>>>([]);
const pages = ref<Array<{ key: string; name: string }>>([]);
const selected = ref<TreeNode | null>(null);
const searchText = ref('');
const showWizard = ref(false);
const wizardParent = ref('');

const tree = computed(() => buildTree(menus.value, pages.value));
const filtered = computed(() => filterTree(tree.value, searchText.value));

function toOption(node: TreeNode): TreeOption {
  return {
    key: node.key,
    label: node.label,
    prefix: () => h('span', iconOf(node.kind)),
    raw: node,
    isLeaf: !node.children,
    children: node.children?.map(toOption)
  };
}
const options = computed(() => filtered.value.map(toOption));

async function load() {
  loading.value = true;
  try {
    const [menuItems, pageItems] = await Promise.all([store.loadAll('menu'), store.list('page')]);
    menus.value = menuItems;
    pages.value = pageItems.map(p => ({ key: p.key, name: p.name }));
    if (selected.value) selected.value = findByKey(tree.value, selected.value.key);
  } catch (error) {
    notify.error(`加载菜单失败：${errorText(error)}`);
  } finally {
    loading.value = false;
  }
}

function findByKey(nodes: TreeNode[], key: string): TreeNode | null {
  for (const node of nodes) {
    if (node.key === key) return node;
    const found = node.children ? findByKey(node.children, key) : null;
    if (found) return found;
  }
  return null;
}

function onSelect(keys: Array<string | number>) {
  selected.value = keys.length ? findByKey(tree.value, String(keys[0])) : null;
}

function openWizard() {
  const node = selected.value;
  wizardParent.value = node?.kind === 'group' ? node.nodeKey ?? '' : '';
  showWizard.value = true;
}

async function onWizardSuccess() {
  showWizard.value = false;
  await load();
}

/** 拖动：只在同一个菜单配置项内移动，移动后保存这个菜单 */
async function onDrop({ node, dragNode, dropPosition }: TreeDropInfo) {
  const target = (node as TreeOption & { raw: TreeNode }).raw;
  const dragged = (dragNode as TreeOption & { raw: TreeNode }).raw;
  if (!target.nodeKey || !dragged.nodeKey || target.menuKey !== dragged.menuKey) {
    notify.warning('只能在同一个菜单内拖动排序');
    return;
  }
  const menu = menus.value.find(m => m.key === target.menuKey);
  if (!menu) return;
  const items = JSON.parse(JSON.stringify(menu.content.items));
  if (!moveNode(items, dragged.nodeKey, target.nodeKey, dropPosition)) {
    notify.warning('只能放进分组，或放在别的菜单项前后');
    return;
  }
  const result = await store.save('menu', menu.key, menu.name, { items });
  if (result.ok) {
    notify.success(`菜单已保存，版本 ${result.version}`);
    await load();
  } else notify.error(`排序保存失败：${result.problems.map(p => p.message).join('；')}`);
}

onMounted(load);
</script>

<template>
  <div class="unified-config">
    <div class="unified-config__sider">
      <div class="sider-search">
        <NInput v-model:value="searchText" placeholder="搜索菜单..." size="small" clearable />
      </div>
      <div class="sider-tree">
        <NTree :data="options" :selected-keys="selected ? [selected.key] : []" block-line selectable draggable default-expand-all @update:selected-keys="onSelect" @drop="onDrop" />
      </div>
      <div class="sider-footer">
        <NButton type="primary" size="small" block @click="openWizard">+ 新增页面</NButton>
      </div>
    </div>
    <div class="unified-config__content">
      <PageConfigPanel v-if="selected?.pageCode" :key="selected.pageCode" :page-code="selected.pageCode" :title="selected.label" @refresh="load" />
      <DirectoryInfoPanel v-else-if="selected && (selected.kind === 'group' || selected.kind === 'menu')" :key="selected.key" :node="selected" :menus="menus" @select="key => (selected = findByKey(tree, key))" @refresh="load" />
      <div v-else class="empty-state"><p>请从左侧选择一个页面或目录</p></div>
    </div>
    <NModal v-model:show="showWizard" preset="card" title="页面创建向导" :style="{ width: '900px', maxHeight: '85vh' }" :body-style="{ overflow: 'auto' }" :mask-closable="false">
      <WizardPanel :default-parent="wizardParent" @success="onWizardSuccess" />
    </NModal>
  </div>
</template>

<style scoped>
.unified-config { height: 100%; display: flex; overflow: hidden; }
.unified-config__sider { width: 240px; flex-shrink: 0; display: flex; flex-direction: column; border-right: 1px solid #e8e8e8; background: #fafafa; }
.sider-search { padding: 12px 12px 8px; flex-shrink: 0; }
.sider-tree { flex: 1; overflow-y: auto; padding: 0 8px; }
.sider-footer { flex-shrink: 0; padding: 8px 12px 12px; border-top: 1px solid #e8e8e8; }
.unified-config__content { flex: 1; overflow-y: auto; padding: 16px 24px; min-width: 0; }
.empty-state { display: flex; align-items: center; justify-content: center; height: 300px; color: #999; font-size: 14px; }
</style>
