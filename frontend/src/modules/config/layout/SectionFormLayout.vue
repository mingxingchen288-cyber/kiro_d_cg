<script setup lang="ts">
/**
 * 页面配置中的"表单布局"（FC-03）：选区域（主表或某个明细），"编辑布局"后拖动和缩放字段，"保存布局"写进页面配置的
 * `formLayout`（随 `PUT /api/config/items/page/{pageCode}` 保存，所有人共用）；"退出编辑"不保存，恢复原布局。
 * 保存后已打开的业务页面经 `config.changed` 刷新，由 assembly 联调（T-AS-7）。
 */
import { computed, ref, shallowRef, watch } from 'vue';
import { NButton, NSelect, NSpace, NTag } from 'naive-ui';
import type { PageCatalog } from '../core/catalog';
import type { ItemEditor } from '../core/item-editor';
import ProblemList from '../components/ProblemList.vue';
import FormLayoutEditor from './FormLayoutEditor.vue';
import { FormLayoutModel } from './form-layout';

const props = defineProps<{ page: ItemEditor<'page'>; catalog: PageCatalog }>();
const areaIndex = ref(0);
const content = computed(() => props.page.state.current!.content);
const area = computed(() => (areaIndex.value === 0 ? content.value.master : content.value.details![areaIndex.value - 1]));
const table = computed(() => props.catalog.tables[areaIndex.value]);
const labels = computed(() => Object.fromEntries((table.value?.fields ?? []).map(f => [f.name, f.label])));
const options = computed(() => props.catalog.tables.map((t, i) => ({ label: `${i === 0 ? '主表' : '明细'} · ${t.title}`, value: i })));
const model = shallowRef<FormLayoutModel>(build());

/** 可以放进表单的字段：页面上可见的字段，按实体字段顺序 */
function build() {
  const fields = (props.catalog.tables[areaIndex.value]?.fields ?? []).filter(f => area.value.fields?.[f.name]?.visible !== false).map(f => f.name);
  return new FormLayoutModel(fields, area.value.formLayout ?? []);
}

watch(areaIndex, () => (model.value = build()));

async function save() {
  area.value.formLayout = model.value.result();
  props.page.markDirty();
  if ((await props.page.save()) !== null) model.value.commit();
}
</script>

<template>
  <div class="section-layout">
    <NSpace align="center" size="small" class="toolbar">
      <NSelect v-model:value="areaIndex" :options="options" size="small" style="width: 220px" :disabled="model.state.editing" />
      <template v-if="!model.state.editing">
        <NButton size="small" type="primary" @click="model.begin()">编辑布局</NButton>
        <span class="hint">{{ area.formLayout?.length ? `${area.formLayout.length} 个字段` : '未设置布局：表单按字段顺序每行 3 个' }}</span>
      </template>
      <template v-else>
        <NButton size="small" type="primary" :loading="page.state.busy" @click="save">保存布局</NButton>
        <NButton size="small" @click="model.cancel()">退出编辑（不保存）</NButton>
        <span class="hint">拖动字段移动，拖右下角缩放；按整列、整行对齐，共 24 列。{{ model.state.dirty ? '有未保存的改动' : '' }}</span>
      </template>
    </NSpace>
    <div v-if="model.state.editing && model.unplaced().length" class="unplaced">
      <span class="hint">未放进表单的字段（点击加到最下面）：</span>
      <NTag v-for="f in model.unplaced()" :key="f" size="small" class="tag" @click="model.add(f)">+ {{ labels[f] ?? f }}</NTag>
    </div>
    <FormLayoutEditor :model="model" :labels="labels" />
    <ProblemList :problems="page.state.problems" />
  </div>
</template>

<style scoped>
.section-layout { padding: 8px 0; }
.toolbar { margin-bottom: 8px; }
.hint { color: #999; font-size: 12px; }
.unplaced { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 8px; }
.tag { cursor: pointer; }
</style>
