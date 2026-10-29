<script setup lang="ts">
/**
 * 表格选项，同旧系统 GridOptionsDialog.vue（460px，"表格选项 - 区域"）：单元格范围选择、侧边栏（C06 `grid`）；
 * C06 另有分组列 `groupBy`。旧系统的"列宽自适应"不在 C06 的 grid 选项中，这里不提供。
 */
import { ref } from 'vue';
import { NButton, NModal, NSelect, NSpace, NSwitch } from 'naive-ui';
import type { ItemEditor } from '../core/item-editor';
import type { EntityField, PageArea } from '../core/types';
import ProblemList from '../components/ProblemList.vue';

const props = defineProps<{ show: boolean; page: ItemEditor<'page'>; area: PageArea; title: string; fields: EntityField[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean] }>();
const grid = ref({ ...props.area.grid, groupBy: [...props.area.grid.groupBy] });
const items = [
  { key: 'cellSelection' as const, label: '单元格范围选择', desc: '像Excel一样框选多个单元格' },
  { key: 'sideBar' as const, label: '侧边栏', desc: '列筛选面板、列显隐控制' }
];

async function save() {
  props.area.grid = { ...grid.value };
  props.page.markDirty();
  if ((await props.page.save()) !== null) emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" :title="`表格选项 - ${title}`" style="width: 460px" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <div v-for="item in items" :key="item.key" class="option-row">
        <div>
          <div class="label">{{ item.label }}</div>
          <div class="desc">{{ item.desc }}</div>
        </div>
        <NSwitch v-model:value="grid[item.key]" />
      </div>
      <div>
        <div class="label">分组列</div>
        <NSelect v-model:value="grid.groupBy" multiple :options="fields.map(f => ({ label: `${f.label} · ${f.name}`, value: f.name }))" placeholder="不分组" />
      </div>
      <ProblemList :problems="page.state.problems" />
      <NSpace justify="end">
        <NButton size="small" @click="emit('update:show', false)">取消</NButton>
        <NButton size="small" type="primary" :loading="page.state.busy" @click="save">保存</NButton>
      </NSpace>
    </NSpace>
  </NModal>
</template>

<style scoped>
.option-row { display: flex; justify-content: space-between; align-items: center; }
.label { font-size: 13px; font-weight: 500; }
.desc { font-size: 12px; color: #999; }
</style>
