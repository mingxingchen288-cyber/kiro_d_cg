<script setup lang="ts">
/**
 * 字段的 Lookup 设置（C06 第 3 节 `lookup`），同旧系统"弹窗选择配置"（LookupConfigEditor.vue）：
 * 弹窗、禁止回填、多选、筛选字段(行) / 筛选列(SQL) / 值来源(行数据 / 单元格)、字段映射（本表字段 → 弹窗字段）。
 */
import { ref, watch } from 'vue';
import { NButton, NCheckbox, NInput, NModal, NSelect, NSpace } from 'naive-ui';
import type { LookupSetting } from '../core/types';

const props = defineProps<{ show: boolean; value: LookupSetting | null; lookups: Array<{ label: string; value: string }>; fields: string[] }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [value: LookupSetting | null] }>();
const code = ref<string | null>(null);
const noFillBack = ref(false);
const multiple = ref(false);
const filterField = ref<string | null>(null);
const filterColumn = ref('');
const filterFrom = ref<'row' | 'cell'>('row');
const pairs = ref<Array<{ local: string | null; remote: string }>>([]);
const fieldOptions = () => props.fields.map(f => ({ label: f, value: f }));

watch(
  () => props.show,
  show => {
    if (!show) return;
    const v = props.value;
    code.value = v?.code ?? null;
    noFillBack.value = v?.fillBack === false;
    multiple.value = v?.multiple === true;
    filterColumn.value = v?.filter?.column ?? '';
    filterFrom.value = v?.filter?.from ?? 'row';
    filterField.value = v?.filter?.field ?? null;
    pairs.value = Object.entries(v?.fill ?? {}).map(([local, remote]) => ({ local, remote }));
  },
  { immediate: true }
);

function save() {
  if (!code.value) {
    emit('save', null);
    emit('update:show', false);
    return;
  }
  const value: LookupSetting = { code: code.value, fill: Object.fromEntries(pairs.value.filter(p => p.local && p.remote).map(p => [p.local!, p.remote.trim()])) };
  if (multiple.value) value.multiple = true;
  if (noFillBack.value) value.fillBack = false;
  if (filterColumn.value.trim()) {
    value.filter = filterFrom.value === 'row' ? { column: filterColumn.value.trim(), from: 'row', field: filterField.value } : { column: filterColumn.value.trim(), from: 'cell' };
  }
  emit('save', value);
  emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" title="弹窗选择配置" :style="{ width: '650px' }" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="10">
      <div class="row">
        <span class="config-label">弹窗</span>
        <NSelect v-model:value="code" :options="lookups" clearable filterable placeholder="选择弹窗配置" size="small" style="width: 200px" />
        <NCheckbox v-model:checked="noFillBack">禁止回填（只查看）</NCheckbox>
        <NCheckbox v-model:checked="multiple">多选（值用英文逗号连接）</NCheckbox>
      </div>
      <div class="row">
        <span class="config-label">筛选列(SQL)</span>
        <NInput v-model:value="filterColumn" size="small" placeholder="如 GOODSID" style="width: 130px" />
        <span class="config-label">值来源</span>
        <NSelect v-model:value="filterFrom" :options="[{ label: '行数据', value: 'row' }, { label: '单元格', value: 'cell' }]" size="small" style="width: 100px" />
        <template v-if="filterFrom === 'row'">
          <span class="config-label">筛选字段(行)</span>
          <NSelect v-model:value="filterField" :options="fieldOptions()" clearable size="small" placeholder="可选" style="width: 140px" />
        </template>
      </div>
      <div class="row top">
        <span class="config-label">字段映射</span>
        <NSpace vertical size="small">
          <div v-for="(pair, i) in pairs" :key="i" class="row">
            <NSelect v-model:value="pair.local" :options="fieldOptions()" size="small" placeholder="本表字段" style="width: 150px" />
            <span>←</span>
            <NInput v-model:value="pair.remote" size="small" placeholder="弹窗字段" style="width: 150px" />
            <NButton text size="small" type="error" @click="pairs.splice(i, 1)">删</NButton>
          </div>
          <NButton size="tiny" dashed @click="pairs.push({ local: null, remote: '' })">+ 添加映射</NButton>
        </NSpace>
      </div>
      <NSpace justify="end">
        <NButton size="small" @click="emit('update:show', false)">取消</NButton>
        <NButton size="small" type="primary" @click="save">确定</NButton>
      </NSpace>
    </NSpace>
  </NModal>
</template>

<style scoped>
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.row.top { align-items: flex-start; }
.config-label { font-size: 12px; color: #666; min-width: 56px; }
</style>
