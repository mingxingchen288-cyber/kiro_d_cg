<script setup lang="ts">
/**
 * 基本信息，同旧系统 SectionBasicInfo.vue（页面名称、页面编码、路由、保存）；路由固定为 `/page/{pageCode}`（C11）。
 * 另有页面的审计、明细显示方式（C06 第 3 节必须写的两项）和保存操作。旧系统的图标、排序属于菜单资源，
 * C06 的菜单项没有图标、排序（顺序即排序，在左侧树中拖动）。
 */
import { computed, onMounted, ref } from 'vue';
import { NButton, NForm, NFormItem, NInput, NSelect, NSwitch } from 'naive-ui';
import { useConfigContext } from '../core/context';
import type { ItemEditor } from '../core/item-editor';

const props = defineProps<{ page: ItemEditor<'page'> }>();
const emit = defineEmits<{ saved: [] }>();
const { store } = useConfigContext();
const content = computed(() => props.page.state.current!.content);
const operations = ref<Array<{ label: string; value: string }>>([]);

async function save() {
  props.page.state.current!.name = content.value.title;
  if (await props.page.save()) emit('saved');
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
