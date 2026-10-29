<script setup lang="ts">
/**
 * 字段的对比（C06 第 2 节 `compare`、FC-08，对应旧系统 rulesConfig.compare）：与同一行的另一个字段对比，
 * 或按关联键到另一个表或视图取对比值；显示差值、百分比或两者。结果只用于显示。
 */
import { ref, watch } from 'vue';
import { NButton, NInput, NModal, NRadio, NRadioGroup, NSelect, NSpace } from 'naive-ui';
import type { CompareFormat, FieldCompare } from '../core/types';

const props = defineProps<{ show: boolean; value: FieldCompare | null; fields: string[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [value: FieldCompare | null] }>();
const mode = ref<'none' | 'field' | 'query'>('none');
const field = ref('');
const source = ref('');
const format = ref<CompareFormat>('both');
const keys = ref<Array<{ current: string; compare: string }>>([]);
const fieldOptions = () => props.fields.map(f => ({ label: f, value: f }));
const formats = [
  { label: '差值', value: 'value' },
  { label: '百分比', value: 'percent' },
  { label: '差值和百分比', value: 'both' }
];

watch(
  () => props.show,
  show => {
    if (!show) return;
    const v = props.value;
    mode.value = v?.mode ?? 'none';
    field.value = v?.field ?? '';
    format.value = v?.format ?? 'both';
    source.value = v?.mode === 'query' ? v.source : '';
    keys.value = v?.mode === 'query' ? v.keys.map(k => ({ ...k })) : [];
  },
  { immediate: true }
);

function save() {
  let value: FieldCompare | null = null;
  if (mode.value === 'field') value = { mode: 'field', field: field.value, format: format.value };
  if (mode.value === 'query') value = { mode: 'query', source: source.value.trim(), keys: keys.value.filter(k => k.current && k.compare), field: field.value.trim(), format: format.value };
  emit('save', value);
  emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" title="对比" :style="{ width: '600px' }" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NRadioGroup v-model:value="mode">
        <NRadio value="none">不对比</NRadio>
        <NRadio value="field">与本行的另一个字段对比</NRadio>
        <NRadio value="query">按关联键到别的表或视图取值</NRadio>
      </NRadioGroup>
      <template v-if="mode === 'field'">
        <NSelect v-model:value="field" :options="fieldOptions()" placeholder="对比的字段，如 LAST_PRICE" />
      </template>
      <template v-if="mode === 'query'">
        <NInput v-model:value="source" placeholder="表或视图名，如 T_COST_GOODS_HIS_V" />
        <div v-for="(key, i) in keys" :key="i" class="row">
          <NSelect v-model:value="key.current" :options="fieldOptions()" placeholder="本行字段" style="width: 180px" />
          <span>=</span>
          <NInput v-model:value="key.compare" placeholder="对比表的列" style="width: 180px" />
          <NButton text type="error" @click="keys.splice(i, 1)">删</NButton>
        </div>
        <NButton size="tiny" dashed @click="keys.push({ current: '', compare: '' })">+ 添加关联键</NButton>
        <NInput v-model:value="field" placeholder="取对比值的列，如 PRICE" />
      </template>
      <NSelect v-if="mode !== 'none'" v-model:value="format" :options="formats" style="width: 200px" />
      <NSpace justify="end">
        <NButton size="small" @click="emit('update:show', false)">取消</NButton>
        <NButton size="small" type="primary" @click="save">确定</NButton>
      </NSpace>
    </NSpace>
  </NModal>
</template>

<style scoped>
.row { display: flex; align-items: center; gap: 8px; }
</style>
