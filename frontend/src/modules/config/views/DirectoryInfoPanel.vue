<script setup lang="ts">
/**
 * 目录信息，同旧系统 DirectoryInfoPanel.vue（名称、编码、子页面表格）；菜单是 `menu` 配置项（C06 第 9 节），
 * 这里另外可以改分组名称、新增子分组或配置 / 管理入口、删除空分组，改动后保存这个菜单配置项（先校验）。
 */
import { computed, h, ref } from 'vue';
import { NAlert, NButton, NDataTable, NDescriptions, NDescriptionsItem, NInput, NPopconfirm, NSelect, NSpace } from 'naive-ui';
import { useConfigContext } from '../core/context';
import type { ConfigProblem } from '../core/errors';
import type { TypedItem } from '../core/store';
import type { MenuNode } from '../core/types';
import { type TreeNode, findNode, removeNode } from './menu-tree';

const props = defineProps<{ node: TreeNode; menus: Array<TypedItem<'menu'>> }>();
const emit = defineEmits<{ select: [key: string]; refresh: [] }>();
const { store, notify } = useConfigContext();
const menu = computed(() => props.menus.find(m => m.key === props.node.menuKey));
const group = computed(() => (menu.value && props.node.nodeKey ? findNode(menu.value.content.items, props.node.nodeKey) : null));
const title = ref(props.node.label);
const newKey = ref('');
const newTitle = ref('');
const newKind = ref<MenuNode['kind']>('group');
const problems = ref<ConfigProblem[]>([]);
const children = computed(() => props.node.children ?? []);

const columns = [
  {
    title: '名称',
    key: 'label',
    render: (row: TreeNode) => h('a', { style: 'color: #2080f0; cursor: pointer;', onClick: () => emit('select', row.key) }, row.label)
  },
  { title: '类型', key: 'kind', width: 90 },
  { title: 'pageCode', key: 'pageCode' }
];

async function saveMenu(mutate: (items: MenuNode[]) => void, name = menu.value?.name ?? '') {
  if (!menu.value) return;
  const items: MenuNode[] = JSON.parse(JSON.stringify(menu.value.content.items));
  mutate(items);
  const result = await store.save('menu', menu.value.key, name, { items });
  if (result.ok) {
    problems.value = [];
    notify.success(`菜单已保存，版本 ${result.version}`);
    emit('refresh');
  } else problems.value = result.problems;
}

function rename() {
  if (props.node.kind === 'menu') return saveMenu(() => {}, title.value);
  return saveMenu(items => {
    const found = findNode(items, props.node.nodeKey!);
    if (found) found.title = title.value;
  });
}

function addChild() {
  const item: MenuNode = { key: newKey.value.trim(), title: newTitle.value.trim(), kind: newKind.value };
  if (!item.key || !item.title) return notify.warning('请填写编码和名称');
  return saveMenu(items => {
    if (props.node.kind === 'menu') items.push(item);
    else {
      const found = findNode(items, props.node.nodeKey!);
      if (found) found.children = [...(found.children ?? []), item];
    }
  });
}

function removeGroup() {
  return saveMenu(items => removeNode(items, props.node.nodeKey!));
}
</script>

<template>
  <div class="directory-info-panel">
    <h3 class="panel-title">{{ node.label }} ({{ node.kind === 'menu' ? '菜单' : '目录' }})</h3>
    <NDescriptions bordered :column="2" size="small" class="info-section">
      <NDescriptionsItem label="名称">
        <NSpace size="small">
          <NInput v-model:value="title" size="small" style="width: 200px" />
          <NButton size="small" type="primary" @click="rename">保存</NButton>
        </NSpace>
      </NDescriptionsItem>
      <NDescriptionsItem label="编码">{{ node.nodeKey ?? menu?.key }}</NDescriptionsItem>
      <NDescriptionsItem label="菜单配置项">{{ menu?.name }} · {{ menu?.key }} · 版本 {{ menu?.version }}</NDescriptionsItem>
      <NDescriptionsItem label="下级">{{ children.length }} 项</NDescriptionsItem>
    </NDescriptions>

    <div class="child-pages">
      <h4>下级 ({{ children.length }})</h4>
      <NDataTable v-if="children.length" :columns="columns" :data="children" :row-key="(row: TreeNode) => row.key" size="small" :bordered="false" :max-height="400" />
      <p v-else class="empty-hint">暂无下级</p>
    </div>

    <div class="child-pages">
      <h4>新增下级</h4>
      <NSpace size="small">
        <NSelect v-model:value="newKind" size="small" style="width: 140px" :options="[{ label: '分组', value: 'group' }, { label: '配置入口', value: 'config' }, { label: '管理入口', value: 'admin' }]" />
        <NInput v-model:value="newKey" size="small" placeholder="编码" style="width: 160px" />
        <NInput v-model:value="newTitle" size="small" placeholder="名称" style="width: 160px" />
        <NButton size="small" @click="addChild">新增</NButton>
        <NPopconfirm v-if="group && !children.length" @positive-click="removeGroup">
          <template #trigger><NButton size="small" type="error" quaternary>删除这个分组</NButton></template>
          确定删除分组「{{ node.label }}」？
        </NPopconfirm>
      </NSpace>
      <div class="hint">新建页面请用左下角"+ 新增页面"（向导会把页面挂到所选分组下）。</div>
    </div>
    <NAlert v-if="problems.length" type="error" :bordered="false" class="mt-12"><div v-for="(p, i) in problems" :key="i">{{ p.path ? `${p.path}：` : '' }}{{ p.message }}</div></NAlert>
  </div>
</template>

<style scoped>
.directory-info-panel { max-width: 800px; }
.panel-title { margin: 0 0 16px; font-size: 18px; }
.info-section { margin-bottom: 24px; }
.child-pages { margin-top: 16px; }
.child-pages h4 { margin: 0 0 8px; font-size: 14px; }
.empty-hint, .hint { color: #999; font-size: 13px; margin-top: 6px; }
</style>
