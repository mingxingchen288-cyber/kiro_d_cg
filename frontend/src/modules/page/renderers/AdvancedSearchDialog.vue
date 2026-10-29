<script setup lang="ts">
/**
 * 高级查询对话框（systemButtons 含 advancedSearch 时提供）：条件行为"表、字段、运算符、值"，运算符与旧系统
 * AdvancedSearchDialog.vue 相同；明细的条件按组合成"同一条明细行同时满足"，组内可以选且、或（C09 第 4 节）。
 * 底部按钮与旧系统相同：重置、取消、查询。
 */
import { computed, ref } from 'vue';
import type { PageView } from '../../../contracts/page-view';
import {
  type ConditionDraft,
  buildAdvanced,
  emptyCondition,
  needsNoValue,
  needsTwoValues,
  operatorsFor,
  takesList
} from '../advanced-search';
import type { PageRuntime } from '../page-runtime';

defineOptions({ name: 'AdvancedSearchDialog' });

const props = defineProps<{ runtime: PageRuntime }>();
const show = defineModel<boolean>('show', { default: false });
const runtime = props.runtime;
const view = computed<PageView>(() => runtime.view.value!);

const drafts = ref<ConditionDraft[]>([]);
const op = ref<'and' | 'or'>('and');

const tableOptions = computed(() => [
  { label: '主表', value: '' },
  ...view.value.details.map(d => ({ label: d.title, value: d.entity }))
]);

function regionOf(draft: ConditionDraft) {
  return draft.entity ? view.value.details.find(d => d.entity === draft.entity) : view.value.master;
}

function fieldOptions(draft: ConditionDraft) {
  return (regionOf(draft)?.fields ?? []).filter(f => f.visible).map(f => ({ label: f.label, value: f.name }));
}

function fieldMeta(draft: ConditionDraft) {
  return regionOf(draft)?.fields.find(f => f.name === draft.field);
}

function operatorOptions(draft: ConditionDraft) {
  const meta = fieldMeta(draft);
  return meta ? operatorsFor(meta.type) : [];
}

function setTable(draft: ConditionDraft, value: string) {
  Object.assign(draft, emptyCondition(view.value, value || null));
}

function setField(draft: ConditionDraft, value: string) {
  draft.field = value;
  const ops = operatorOptions(draft);
  if (!ops.some(o => o.value === draft.operator)) draft.operator = ops[0]?.value ?? 'eq';
}

function add() {
  drafts.value.push(emptyCondition(view.value));
}

function remove(index: number) {
  drafts.value.splice(index, 1);
}

function reset() {
  drafts.value = [];
  op.value = 'and';
  runtime.applyAdvanced(null);
}

function search() {
  runtime.applyAdvanced(buildAdvanced(view.value, drafts.value, op.value));
  show.value = false;
}

function open() {
  if (!drafts.value.length) add();
}
</script>

<template>
  <NModal v-model:show="show" @after-enter="open">
    <NCard class="advanced-search" title="高级查询" :bordered="false" size="small" closable @close="show = false">
      <div class="mb-8px flex-y-center gap-8px text-12px">
        <span>主表条件之间：</span>
        <NRadioGroup v-model:value="op" size="small">
          <NRadio value="and">且</NRadio>
          <NRadio value="or">或</NRadio>
        </NRadioGroup>
      </div>
      <div v-for="(draft, index) in drafts" :key="index" class="advanced-search__row">
        <NSelect
          size="small"
          class="w-120px"
          :value="draft.entity ?? ''"
          :options="tableOptions"
          @update:value="(v: string) => setTable(draft, v)"
        />
        <NSelect
          size="small"
          class="w-160px"
          :value="draft.field"
          :options="fieldOptions(draft)"
          @update:value="(v: string) => setField(draft, v)"
        />
        <NSelect v-model:value="draft.operator" size="small" class="w-110px" :options="operatorOptions(draft)" />
        <template v-if="!needsNoValue(draft.operator)">
          <NSelect
            v-if="fieldMeta(draft)?.type === 'boolean'"
            v-model:value="draft.value"
            size="small"
            class="w-100px"
            :options="[
              { label: '是', value: 'true' },
              { label: '否', value: 'false' }
            ]"
          />
          <NInput
            v-else
            v-model:value="draft.value"
            size="small"
            class="w-180px"
            :placeholder="takesList(draft.operator) ? '多个值用逗号分隔' : '请输入'"
          />
          <NInput
            v-if="needsTwoValues(draft.operator)"
            v-model:value="draft.value2"
            size="small"
            class="w-140px"
            placeholder="请输入"
          />
        </template>
        <template v-if="draft.entity">
          <NInput v-model:value="draft.group" size="small" class="w-70px" placeholder="组" />
          <NSelect
            v-model:value="draft.logic"
            size="small"
            class="w-70px"
            :options="[
              { label: '且', value: 'and' },
              { label: '或', value: 'or' }
            ]"
          />
        </template>
        <NButton quaternary size="small" @click="remove(index)">删除</NButton>
      </div>
      <NButton size="small" dashed class="mt-8px" @click="add">添加条件</NButton>
      <div class="mt-8px text-12px text-#999">
        明细表的条件：同一组的条件由同一条明细行同时满足，组内第二条起按"且/或"与前一条组合。
      </div>
      <template #footer>
        <NSpace justify="end">
          <NButton size="small" @click="reset">重置</NButton>
          <NButton size="small" @click="show = false">取消</NButton>
          <NButton type="primary" size="small" @click="search">查询</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
.advanced-search {
  width: 980px;
  max-width: calc(100vw - 100px);
}

.advanced-search__row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
</style>
