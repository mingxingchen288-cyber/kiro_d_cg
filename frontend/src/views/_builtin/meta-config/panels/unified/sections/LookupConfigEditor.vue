<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { NAutoComplete, NButton, NInput, NSelect, NSpace, NSwitch, useMessage } from 'naive-ui';
import { fetchAllLookupConfigs } from '@/service/api/meta-config';

const props = defineProps<{
  config: any; // cellEditorParams: { lookupCode, mapping, noFillback, filterField, filterColumn, filterValueFrom }
  availableFields: string[]; // 当前表的所有字段名
}>();

const emit = defineEmits<{
  (e: 'save', config: any): void;
  (e: 'close'): void;
}>();

const message = useMessage();

// 状态
const lookupCode = ref('');
const dataSource = ref('');
const noFillback = ref(false);
const filterField = ref('');
const filterColumn = ref('');
const filterValueFrom = ref('');
const mappingPairs = ref<Array<{ local: string; remote: string }>>([]);

// Lookup 选项列表
const lookupOptions = ref<Array<{ label: string; value: string; dataSource: string }>>([]);

onMounted(async () => {
  // 加载 Lookup 配置列表
  try {
    const list = await fetchAllLookupConfigs();
    lookupOptions.value = (list || []).map((item: any) => ({
      label: item.lookupName || item.lookupCode,
      value: item.lookupCode,
      dataSource: item.dataSource || ''
    }));
  } catch {}

  // 解析传入的配置
  const cfg = props.config || {};
  lookupCode.value = cfg.lookupCode || '';
  noFillback.value = !!cfg.noFillback;
  filterField.value = cfg.filterField || '';
  filterColumn.value = cfg.filterColumn || '';
  filterValueFrom.value = cfg.filterValueFrom || '';

  // 解析映射
  if (cfg.mapping && typeof cfg.mapping === 'object') {
    mappingPairs.value = Object.entries(cfg.mapping).map(([local, remote]) => ({
      local,
      remote: String(remote ?? '')
    }));
  }

  // 找到 dataSource
  updateDataSource();
});

function updateDataSource() {
  const matched = lookupOptions.value.find(o => o.value === lookupCode.value);
  dataSource.value = matched?.dataSource || '';
}

function onLookupCodeChange(value: string) {
  lookupCode.value = value || '';
  updateDataSource();
}

function addMapping() {
  mappingPairs.value.push({ local: '', remote: '' });
}

function removeMapping(index: number) {
  mappingPairs.value.splice(index, 1);
}

function getFieldOptions(input: string) {
  if (!input) return props.availableFields.map(f => ({ label: f, value: f }));
  const lower = input.toLowerCase();
  return props.availableFields
    .filter(f => f.toLowerCase().includes(lower))
    .map(f => ({ label: f, value: f }));
}

function handleSave() {
  if (!lookupCode.value) {
    message.warning('请选择弹窗');
    return;
  }
  const mapping: Record<string, string> = {};
  for (const pair of mappingPairs.value) {
    if (pair.local && pair.remote) {
      mapping[pair.local] = pair.remote;
    }
  }
  const result: any = {
    lookupCode: lookupCode.value,
    mapping
  };
  if (noFillback.value) result.noFillback = true;
  if (filterField.value) result.filterField = filterField.value;
  if (filterColumn.value) result.filterColumn = filterColumn.value;
  if (filterValueFrom.value) result.filterValueFrom = filterValueFrom.value;

  emit('save', result);
}
</script>

<template>
  <div class="lookup-config-editor">
    <!-- 弹窗选择 -->
    <div class="config-row">
      <span class="config-label">弹窗</span>
      <NSelect
        :value="lookupCode || null"
        :options="lookupOptions"
        filterable
        clearable
        size="small"
        placeholder="选择弹窗配置"
        style="width: 200px"
        @update:value="onLookupCodeChange"
      />
      <span v-if="dataSource" class="data-source">视图: {{ dataSource }}</span>
    </div>

    <!-- 禁止回填 -->
    <div class="config-row">
      <span class="config-label">禁止回填</span>
      <NSwitch v-model:value="noFillback" size="small" />
    </div>

    <!-- 筛选配置 -->
    <div class="config-row">
      <span class="config-label">筛选字段(行)</span>
      <NAutoComplete
        v-model:value="filterField"
        :options="getFieldOptions(filterField)"
        size="small"
        clearable
        placeholder="可选"
        style="width: 140px"
      />
      <span class="config-label">筛选列(SQL)</span>
      <NInput v-model:value="filterColumn" size="small" placeholder="如 GOODSID" style="width: 130px" />
      <span class="config-label">值来源</span>
      <NSelect
        v-model:value="filterValueFrom"
        :options="[{ label: '行数据', value: 'row' }, { label: '单元格', value: 'cell' }]"
        size="small"
        clearable
        style="width: 100px"
      />
    </div>

    <!-- 字段映射 -->
    <div class="config-row" style="align-items: flex-start">
      <span class="config-label" style="margin-top: 4px">字段映射</span>
      <div class="mapping-list">
        <div v-for="(pair, pi) in mappingPairs" :key="pi" class="mapping-pair">
          <NAutoComplete
            v-model:value="pair.local"
            :options="getFieldOptions(pair.local)"
            size="small"
            clearable
            placeholder="本表字段"
            style="width: 150px"
          />
          <span class="mapping-arrow">→</span>
          <NInput v-model:value="pair.remote" size="small" placeholder="弹窗字段" style="width: 150px" />
          <NButton text size="small" type="error" @click="removeMapping(pi)">删</NButton>
        </div>
        <NButton size="tiny" dashed @click="addMapping">+ 添加映射</NButton>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="config-actions">
      <NSpace justify="end">
        <NButton size="small" @click="emit('close')">取消</NButton>
        <NButton size="small" type="primary" @click="handleSave">确定</NButton>
      </NSpace>
    </div>
  </div>
</template>

<style scoped>
.lookup-config-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.config-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.config-label {
  font-size: 12px;
  color: #666;
  white-space: nowrap;
}
.data-source {
  font-size: 12px;
  color: #999;
}
.mapping-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mapping-pair {
  display: flex;
  align-items: center;
  gap: 4px;
}
.mapping-arrow {
  color: #999;
}
.config-actions {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
}
</style>
