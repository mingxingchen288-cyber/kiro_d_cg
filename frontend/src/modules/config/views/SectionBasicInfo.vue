<script setup lang="ts">
/**
 * 基本信息，同旧系统 SectionBasicInfo.vue（页面名称、页面编码、路由、图标、保存）；路由固定为 `/page/{pageCode}`（C11）。
 * 另有页面的审计、明细显示方式（C06 第 3 节必须写的两项）和保存操作。旧系统的排序属于菜单资源，新平台顺序即排序，
 * 在左侧树中拖动。
 * 图标（FC-16）：旧系统的图标存在菜单资源上（`T_COST_RESOURCE.ICON`），新平台存在这个页面所在的菜单项上
 * （`menu` 配置项的 `icon`，C06 v26）。点"保存"时先保存页面，图标改了再保存菜单配置项；页面没有挂在菜单下时不能选图标。
 */
import { computed, onMounted, ref } from 'vue';
import { NButton, NForm, NFormItem, NInput, NSelect, NSwitch } from 'naive-ui';
import { useConfigContext } from '../core/context';
import type { ItemEditor } from '../core/item-editor';
import type { TypedItem } from '../core/store';
import type { MenuNode } from '../core/types';
import { iconOfNode, iconOptions, menuItemOfPage, setNodeIcon } from './menu-tree';

const props = defineProps<{ page: ItemEditor<'page'>; menus: Array<TypedItem<'menu'>> }>();
const emit = defineEmits<{ saved: [] }>();
const { store, notify } = useConfigContext();
const content = computed(() => props.page.state.current!.content);
const operations = ref<Array<{ label: string; value: string }>>([]);

const place = computed(() => menuItemOfPage(props.menus, props.page.state.current!.key));
const menu = computed(() => (place.value ? props.menus.find(m => m.key === place.value!.menuKey) : undefined));
const savedIcon = computed(() => (menu.value && place.value ? iconOfNode(menu.value.content.items, place.value.nodeKey) : null));
const icon = ref<string | null>(savedIcon.value);

async function saveIcon() {
  if (!menu.value || !place.value || (icon.value || null) === savedIcon.value) return true;
  const items: MenuNode[] = JSON.parse(JSON.stringify(menu.value.content.items));
  setNodeIcon(items, place.value.nodeKey, icon.value);
  const result = await store.save('menu', menu.value.key, menu.value.name, { items });
  if (!result.ok) notify.error(`图标保存失败：${result.problems.map(p => p.message).join('；')}`);
  return result.ok;
}

async function save() {
  props.page.state.current!.name = content.value.title;
  if ((await props.page.save()) && (await saveIcon())) emit('saved');
}

onMounted(async () => {
  operations.value = (await store.list('operation')).map(o => ({ label: `${o.name} · ${o.key}`, value: o.key }));
});
</script>

<template>
  <div class="section-basic-info">
    <NForm label-placement="left" label-width="96px" inline>
      <NFormItem label="页面名称">
        <NInput v-model:value="content.title" style="width: 200px" @update:value="page.markDirty()" />
      </NFormItem>
      <NFormItem label="页面编码">
        <NInput :value="page.state.current!.key" disabled style="width: 200px" />
      </NFormItem>
      <NFormItem label="路由">
        <NInput :value="`/page/${page.state.current!.key}`" disabled style="width: 200px" />
      </NFormItem>
      <NFormItem label="图标">
        <NSelect
          v-model:value="icon"
          data-testid="page-icon"
          :options="iconOptions(icon)"
          :disabled="!place"
          :placeholder="place ? '选择或输入图标' : '页面没有挂在菜单下'"
          filterable
          tag
          clearable
          size="small"
          style="width: 180px"
        />
      </NFormItem>
      <NFormItem label="页面模式">
        <NInput :value="content.layout === 'single' ? '单表' : '主从'" disabled style="width: 80px" />
      </NFormItem>
      <NFormItem v-if="content.layout === 'masterDetail'" label="明细显示方式">
        <NSelect v-model:value="content.detailMode" :options="[{ label: '多 Tab', value: 'tabs' }, { label: '上下排列', value: 'stack' }]" style="width: 120px" @update:value="page.markDirty()" />
      </NFormItem>
      <NFormItem label="记录审计">
        <NSwitch v-model:value="content.audit" @update:value="page.markDirty()" />
      </NFormItem>
      <NFormItem label="保存操作">
        <NSelect v-model:value="content.saveOperation" :options="operations" filterable tag style="width: 260px" @update:value="page.markDirty()" />
      </NFormItem>
      <NFormItem>
        <NButton type="primary" size="small" :loading="page.state.busy" @click="save">保存</NButton>
        <span class="hint">{{ page.state.status }}</span>
      </NFormItem>
    </NForm>
  </div>
</template>

<style scoped>
.section-basic-info { padding: 8px 0; }
.hint { margin-left: 8px; color: #999; font-size: 12px; }
</style>
