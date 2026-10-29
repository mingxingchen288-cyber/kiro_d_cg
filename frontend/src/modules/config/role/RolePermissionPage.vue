<script setup lang="ts">
/**
 * 角色权限（C06 第 8 节、FC-04），同旧系统 views/_builtin/permission/index.vue：左侧角色列表（查询、新增、编辑、删除），
 * 右侧"页面权限配置"——功能权限树（菜单配置），勾选页面授权，已授权的页面后面有"配置按钮""配置列""配置行"。
 * 旧系统的"人员列表"（给角色分配人员）在新平台是账号的角色（C09 `/api/admin/accounts` 的 roleCodes），由账号管理编辑。
 */
import { computed, h, onMounted, ref } from 'vue';
import { NButton, NEmpty, NInput, NModal, NPopconfirm, NScrollbar, NSpace, NSwitch, NTag, NTree } from 'naive-ui';
import type { TreeOption } from 'naive-ui';
import { type PageCatalog, loadPageCatalog } from '../core/catalog';
import { useConfigContext } from '../core/context';
import { errorText } from '../core/errors';
import { ItemEditor } from '../core/item-editor';
import type { MenuNode, RolePage } from '../core/types';
import ProblemList from '../components/ProblemList.vue';
import RoleButtonDialog from './RoleButtonDialog.vue';
import RoleColumnDialog from './RoleColumnDialog.vue';
import RoleRowDialog from './RoleRowDialog.vue';

const { store, notify } = useConfigContext();
const editor = new ItemEditor(store, 'role', notify);
const keyword = ref('');
const menus = ref<Array<{ key: string; name: string; content: { items: MenuNode[] } }>>([]);
const showRole = ref(false);
const roleForm = ref({ key: '', name: '' });
const dialog = ref<'' | 'buttons' | 'columns' | 'rows'>('');
const dialogPage = ref<{ code: string; title: string; catalog: PageCatalog; exports: Array<{ key: string; name: string }> } | null>(null);
const role = computed(() => editor.state.current?.content ?? null);
const roles = computed(() => editor.state.items.filter(r => !keyword.value || r.name.includes(keyword.value) || r.key.toLowerCase().includes(keyword.value.toLowerCase())));
const COLORS = ['#2080f0', '#18a058', '#f0a020', '#d03050', '#7c3aed', '#0891b2'];

function pageNodes(items: MenuNode[]): TreeOption[] {
  return items
    .filter(i => i.kind === 'group' || i.kind === 'page')
    .map(i => (i.kind === 'page' ? { key: i.pageCode ?? i.key, label: i.title, isLeaf: true, raw: i } : { key: `group:${i.key}`, label: i.title, children: pageNodes(i.children ?? []), raw: i }));
}
const tree = computed(() => menus.value.flatMap(m => pageNodes(m.content.items)));
const checkedKeys = computed(() => Object.keys(role.value?.pages ?? {}));

function onChecked(keys: Array<string | number>) {
  const current = role.value!;
  const pages: Record<string, RolePage> = {};
  for (const key of keys.map(String).filter(k => !k.startsWith('group:'))) pages[key] = current.pages?.[key] ?? { buttons: ['*'] };
  current.pages = pages;
  editor.markDirty();
}

async function openDialog(kind: 'buttons' | 'columns' | 'rows', code: string, title: string) {
  try {
    const [catalog, exports] = await Promise.all([loadPageCatalog(store, code), store.loadAll('export')]);
    dialogPage.value = { code, title, catalog, exports: exports.filter(e => e.content.page === code).map(e => ({ key: e.key, name: e.name })) };
    dialog.value = kind;
  } catch (error) {
    notify.error(errorText(error));
  }
}

function renderLabel({ option }: { option: TreeOption }) {
  const raw = (option as TreeOption & { raw: MenuNode }).raw;
  const label = h('span', { class: 'tree-node-label' }, option.label as string);
  if (raw.kind !== 'page' || !checkedKeys.value.includes(String(option.key))) return label;
  const code = String(option.key);
  const btn = (text: string, kind: 'buttons' | 'columns' | 'rows') =>
    h(NButton, { text: true, size: 'tiny', type: 'primary', class: 'config-btn', onClick: (e: Event) => (e.stopPropagation(), openDialog(kind, code, raw.title)) }, () => text);
  const page = role.value?.pages?.[code];
  const tags = [page?.buttons?.includes('*') ? '全部按钮' : `${page?.buttons?.length ?? 0} 个按钮`, page?.rows ? '有行权限' : ''].filter(Boolean);
  return h('span', { class: 'tree-node' }, [label, ...tags.map(t => h(NTag, { size: 'tiny', class: 'ml-1' }, () => t)), btn('配置按钮', 'buttons'), btn('配置列', 'columns'), btn('配置行', 'rows')]);
}

function saveDialog(value: Partial<RolePage>) {
  const code = dialogPage.value!.code;
  const page = { ...(role.value!.pages?.[code] ?? {}), ...value };
  if (!page.rows) delete page.rows;
  if (page.columns && !Object.keys(page.columns).length) delete page.columns;
  role.value!.pages = { ...(role.value!.pages ?? {}), [code]: page };
  editor.markDirty();
  dialog.value = '';
}

function openAdd() {
  roleForm.value = { key: '', name: '' };
  showRole.value = true;
}

function createRole() {
  if (!roleForm.value.key.trim()) return notify.warning('请填写角色编码');
  editor.create(roleForm.value.key.trim(), roleForm.value.name.trim() || roleForm.value.key.trim());
  showRole.value = false;
}

async function save() {
  editor.state.current!.content.name = editor.state.current!.name;
  await editor.save();
}

onMounted(async () => {
  await editor.loadList();
  menus.value = await store.loadAll('menu');
});
</script>

<template>
  <div class="permission-page">
    <div class="role-panel">
      <div class="panel-header"><span class="panel-title">角色管理</span></div>
      <div class="panel-toolbar">
        <NInput v-model:value="keyword" size="small" placeholder="查询角色" clearable />
        <NButton type="primary" size="small" @click="openAdd">新增</NButton>
      </div>
      <NScrollbar class="role-list">
        <div v-for="(r, idx) in roles" :key="r.key" class="role-card" :class="{ active: editor.state.current?.key === r.key }" @click="editor.open(r.key)">
          <div class="role-icon" :style="{ background: COLORS[idx % COLORS.length] }">{{ r.name.slice(0, 1) }}</div>
          <div class="role-info">
            <div class="role-name">{{ r.name }}</div>
            <div class="role-code">{{ r.key }} · 版本 {{ r.version }}</div>
          </div>
        </div>
        <NEmpty v-if="!roles.length" description="暂无角色" class="mt-8" />
      </NScrollbar>
    </div>
    <div class="detail-panel">
      <template v-if="role && editor.state.current">
        <div class="detail-header">
          <NSpace align="center" size="small">
            <NTag type="success" size="small">{{ editor.state.current.version === null ? '新角色' : '角色' }}</NTag>
            <NInput v-model:value="editor.state.current.name" size="small" style="width: 200px" @update:value="editor.markDirty()" />
            <span class="hint">{{ editor.state.current.key }}</span>
            <span class="hint">管理员（可以使用配置和管理功能）</span>
            <NSwitch v-model:value="role.admin" size="small" @update:value="editor.markDirty()" />
          </NSpace>
          <NSpace size="small">
            <span class="hint">{{ editor.state.dirty ? '有未保存的修改' : editor.state.status }}</span>
            <NButton size="small" type="primary" :loading="editor.state.busy" @click="save">保存角色</NButton>
            <NPopconfirm @positive-click="editor.remove()">
              <template #trigger><NButton size="small" type="error" quaternary>删除</NButton></template>
              确定删除「{{ editor.state.current.name }}」？仍被审批流等引用时不能删除。
            </NPopconfirm>
          </NSpace>
        </div>
        <ProblemList :problems="editor.state.problems" />
        <div class="section-header">
          <div class="section-title"><span class="title-bar" />功能权限树</div>
          <div class="section-tip">勾选页面授权，点击「配置按钮」「配置列」「配置行」设置权限。给角色分配人员在账号管理中进行。</div>
        </div>
        <div class="tree-container">
          <NTree :data="tree" :checked-keys="checkedKeys" :render-label="renderLabel" checkable cascade selectable expand-on-click default-expand-all @update:checked-keys="onChecked" />
          <NEmpty v-if="!tree.length" description="暂无页面" />
        </div>
      </template>
      <div v-else class="empty-state"><div class="empty-text">请选择一个角色</div></div>
    </div>

    <NModal v-model:show="showRole" preset="card" title="新增角色" style="width: 420px">
      <NSpace vertical>
        <NInput v-model:value="roleForm.key" placeholder="角色编码" />
        <NInput v-model:value="roleForm.name" placeholder="角色名称" />
        <NSpace justify="end">
          <NButton size="small" @click="showRole = false">取消</NButton>
          <NButton size="small" type="primary" @click="createRole">确定</NButton>
        </NSpace>
      </NSpace>
    </NModal>
    <template v-if="dialogPage && role">
      <RoleButtonDialog v-if="dialog === 'buttons'" :page-title="dialogPage.title" :page="dialogPage.catalog.page" :exports="dialogPage.exports" :value="role.pages?.[dialogPage.code]?.buttons ?? []" @close="dialog = ''" @save="buttons => saveDialog({ buttons })" />
      <RoleColumnDialog v-if="dialog === 'columns'" :page-title="dialogPage.title" :catalog="dialogPage.catalog" :value="role.pages?.[dialogPage.code]?.columns ?? {}" @close="dialog = ''" @save="columns => saveDialog({ columns })" />
      <RoleRowDialog v-if="dialog === 'rows'" :page-title="dialogPage.title" :fields="dialogPage.catalog.tables[0]?.fields ?? []" :value="role.pages?.[dialogPage.code]?.rows ?? null" @close="dialog = ''" @save="rows => saveDialog({ rows })" />
    </template>
  </div>
</template>

<style scoped>
.permission-page { display: flex; height: 100%; gap: 0; background: #fff; }
.role-panel { width: 280px; flex-shrink: 0; display: flex; flex-direction: column; border-right: 1px solid #e8e8e8; padding: 12px; }
.panel-title { font-weight: 600; font-size: 15px; }
.panel-toolbar { display: flex; gap: 8px; margin: 10px 0; }
.role-list { flex: 1; }
.role-card { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 6px; cursor: pointer; margin-bottom: 4px; }
.role-card:hover { background: #f5f7fa; }
.role-card.active { background: #e8f2ff; }
.role-icon { width: 32px; height: 32px; border-radius: 50%; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; }
.role-name { font-size: 14px; }
.role-code { font-size: 12px; color: #999; }
.detail-panel { flex: 1; min-width: 0; padding: 12px 16px; overflow-y: auto; }
.detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.section-header { margin: 12px 0 8px; }
.section-title { display: flex; align-items: center; gap: 6px; font-weight: 500; }
.title-bar { width: 3px; height: 14px; background: #2080f0; display: inline-block; }
.section-tip, .hint { color: #999; font-size: 12px; }
.tree-container { border: 1px solid #f0f0f0; border-radius: 4px; padding: 8px; }
.tree-container :deep(.config-btn) { margin-left: 8px; }
.empty-state { height: 300px; display: flex; align-items: center; justify-content: center; color: #999; }
</style>
