<script setup lang="ts">
import { computed, nextTick, ref, unref } from 'vue';
import {
  NButton,
  NCheckbox,
  NDatePicker,
  NEmpty,
  NInput,
  NInputNumber,
  NModal,
  NPopover,
  NSelect,
  NSpace
} from 'naive-ui';
import { Icon } from '@iconify/vue';
import LookupDialog from '@/v3/components/LookupDialog.vue';
import {
  getEmptyAdvancedSearchSecondaryValue,
  getEmptyAdvancedSearchValue,
  isAdvancedSearchMultiValueOperator,
  isAdvancedSearchNullaryOperator,
  isAdvancedSearchRangeOperator
} from '@/v3/composables/meta-v3/advanced-search-values';

type SearchCondition = {
  key: string;
  field: string;
  fieldLabel: string;
  tableLabel: string;
  operator: string;
  value: any;
  value2?: any;
  enabled: boolean;
  visible: boolean;
  dataType: 'string' | 'number' | 'date' | 'datetime';
  inputMode: 'text' | 'number' | 'date' | 'datetime' | 'select' | 'lookup';
  lookupCode?: string;
  options?: Array<{ label: string; value: string | number }>;
  loadingOptions?: boolean;
};

type LookupDialogExpose = {
  open: () => Promise<void> | void;
};

const props = defineProps<{
  runtime: any;
}>();

const advancedSearch = computed(() => props.runtime?.actions?.advancedSearch || {});
const searchConditions = computed<SearchCondition[]>(() => unref(advancedSearch.value.searchConditions) || []);
const visibleConditions = computed<SearchCondition[]>(() => unref(advancedSearch.value.visibleConditions) || []);
const hiddenConditions = computed<SearchCondition[]>(() => searchConditions.value.filter(cond => !cond.visible));
const activeFilterSummaries = computed<string[]>(() => unref(advancedSearch.value.activeFilterSummaries) || []);
const showDialog = computed({
  get: () => Boolean(unref(advancedSearch.value.showDialog)),
  set: value => {
    if (!value) {
      advancedSearch.value.close?.();
    } else {
      advancedSearch.value.open?.();
    }
  }
});

const lookupDialogRef = ref<LookupDialogExpose | null>(null);
const currentLookupCondition = ref<SearchCondition | null>(null);

const currentLookupCode = computed(() => currentLookupCondition.value?.lookupCode || '');
const isLookupMultiple = computed(() => isAdvancedSearchMultiValueOperator(currentLookupCondition.value?.operator));
const modalStyle = {
  width: '560px',
  maxWidth: 'calc(100vw - 48px)'
};
const currentLookupMapping = computed(() => {
  const selectedField = currentLookupCondition.value?.field;
  const mapping: Record<string, string> = {};
  if (selectedField) {
    mapping.selectedValue = selectedField;
  }
  return mapping;
});

function getOperatorOptions(cond: SearchCondition) {
  if (cond.dataType === 'number') {
    return [
      { label: '等于', value: 'eq' },
      { label: '不等于', value: 'ne' },
      { label: '大于', value: 'gt' },
      { label: '大于等于', value: 'ge' },
      { label: '小于', value: 'lt' },
      { label: '小于等于', value: 'le' },
      { label: '包含', value: 'like' },
      { label: '不包含', value: 'notLike' },
      { label: '介于', value: 'between' },
      { label: '不介于', value: 'notBetween' },
      { label: 'IN', value: 'in' },
      { label: 'NOT IN', value: 'notIn' },
      { label: '为空', value: 'isNull' },
      { label: '不为空', value: 'isNotNull' }
    ];
  }
  if (cond.dataType === 'date' || cond.dataType === 'datetime') {
    return [
      { label: '等于', value: 'eq' },
      { label: '不等于', value: 'ne' },
      { label: '大于', value: 'gt' },
      { label: '大于等于', value: 'ge' },
      { label: '小于', value: 'lt' },
      { label: '小于等于', value: 'le' },
      { label: '介于', value: 'between' },
      { label: '不介于', value: 'notBetween' }
    ];
  }
  return [
    { label: '等于', value: 'eq' },
    { label: '不等于', value: 'ne' },
    { label: '包含', value: 'like' },
    { label: '不包含', value: 'notLike' },
    { label: 'IN', value: 'in' },
    { label: 'NOT IN', value: 'notIn' },
    { label: '为空', value: 'isNull' },
    { label: '不为空', value: 'isNotNull' }
  ];
}

function handleOperatorChange(cond: SearchCondition, operator: string) {
  cond.operator = operator;
  if (!isAdvancedSearchRangeOperator(operator)) {
    cond.value2 = getEmptyAdvancedSearchSecondaryValue({
      inputMode: cond.inputMode,
      dataType: cond.dataType
    });
  }
  if (isAdvancedSearchNullaryOperator(operator)) {
    cond.value = getEmptyAdvancedSearchValue({
      inputMode: cond.inputMode,
      dataType: cond.dataType,
      operator
    });
    cond.value2 = getEmptyAdvancedSearchSecondaryValue({
      inputMode: cond.inputMode,
      dataType: cond.dataType
    });
    return;
  }
  if (isAdvancedSearchMultiValueOperator(operator)) {
    if (cond.inputMode === 'select' || cond.inputMode === 'lookup') {
      if (!Array.isArray(cond.value)) {
        if (cond.value === null || cond.value === undefined || cond.value === '') {
          cond.value = [];
        } else if (cond.inputMode === 'lookup') {
          cond.value = splitLookupValues(String(cond.value));
        } else {
          cond.value = [cond.value];
        }
      }
    } else if (Array.isArray(cond.value)) {
      cond.value = cond.value.join(',');
    }
  } else if (Array.isArray(cond.value)) {
    cond.value =
      cond.value[0] ??
      getEmptyAdvancedSearchValue({
        inputMode: cond.inputMode,
        dataType: cond.dataType,
        operator
      });
  }
}

function shouldUseLookupInput(cond: SearchCondition) {
  return (
    cond.inputMode === 'lookup' &&
    !isAdvancedSearchRangeOperator(cond.operator) &&
    !isAdvancedSearchNullaryOperator(cond.operator)
  );
}

function shouldUseSelectInput(cond: SearchCondition) {
  return cond.inputMode === 'select' && !isAdvancedSearchNullaryOperator(cond.operator);
}

function shouldUseNumberInput(cond: SearchCondition) {
  return (
    cond.dataType === 'number' &&
    cond.inputMode !== 'select' &&
    !isAdvancedSearchRangeOperator(cond.operator) &&
    !isAdvancedSearchMultiValueOperator(cond.operator) &&
    !isAdvancedSearchNullaryOperator(cond.operator) &&
    cond.operator !== 'like' &&
    cond.operator !== 'notLike'
  );
}

function shouldUseNumberRangeInput(cond: SearchCondition) {
  return cond.dataType === 'number' && cond.inputMode !== 'select' && isAdvancedSearchRangeOperator(cond.operator);
}

function shouldUseDateInput(cond: SearchCondition) {
  return (
    (cond.dataType === 'date' || cond.dataType === 'datetime') &&
    cond.inputMode !== 'select' &&
    !isAdvancedSearchRangeOperator(cond.operator)
  );
}

function shouldUseDateRangeInput(cond: SearchCondition) {
  return (
    (cond.dataType === 'date' || cond.dataType === 'datetime') &&
    cond.inputMode !== 'select' &&
    isAdvancedSearchRangeOperator(cond.operator)
  );
}

function shouldUseTextInput(cond: SearchCondition) {
  if (isAdvancedSearchRangeOperator(cond.operator) || isAdvancedSearchNullaryOperator(cond.operator)) {
    return false;
  }
  if (
    shouldUseLookupInput(cond) ||
    shouldUseSelectInput(cond) ||
    shouldUseNumberInput(cond) ||
    shouldUseDateInput(cond) ||
    shouldUseDateRangeInput(cond) ||
    shouldUseNumberRangeInput(cond)
  ) {
    return false;
  }
  return true;
}

function markEnabled(cond: SearchCondition) {
  if (isAdvancedSearchNullaryOperator(cond.operator)) {
    cond.enabled = true;
    return;
  }
  if (Array.isArray(cond.value)) {
    cond.enabled = cond.value.length > 0;
    return;
  }
  cond.enabled = String(cond.value ?? '').trim().length > 0;
}

function clearConditionValue(cond: SearchCondition) {
  cond.value = getEmptyAdvancedSearchValue({
    inputMode: cond.inputMode,
    dataType: cond.dataType,
    operator: cond.operator
  });
  cond.value2 = getEmptyAdvancedSearchSecondaryValue({
    inputMode: cond.inputMode,
    dataType: cond.dataType
  });
  cond.enabled = false;
}

function hideCondition(cond: SearchCondition) {
  clearConditionValue(cond);
  cond.visible = false;
}

function showCondition(cond: SearchCondition) {
  cond.visible = true;
}

function handleSingleValueChange(cond: SearchCondition, value: any) {
  cond.value =
    value ??
    getEmptyAdvancedSearchValue({
      inputMode: cond.inputMode,
      dataType: cond.dataType,
      operator: cond.operator
    });
  markEnabled(cond);
}

function handleSelectValueChange(cond: SearchCondition, value: any) {
  cond.value = value ?? (isAdvancedSearchMultiValueOperator(cond.operator) ? [] : null);
  markEnabled(cond);
}

function handleRangeValueChange(cond: SearchCondition, edge: 'start' | 'end', value: number | null) {
  if (edge === 'start') {
    cond.value = value;
  } else {
    cond.value2 = value;
  }
  cond.enabled = cond.value !== null && cond.value !== '' && cond.value2 !== null && cond.value2 !== '';
}

function getDatePickerType(cond: SearchCondition) {
  return cond.dataType === 'datetime' ? 'datetime' : 'date';
}

function getDateValueFormat(cond: SearchCondition) {
  return cond.dataType === 'datetime' ? 'yyyy-MM-dd HH:mm:ss' : 'yyyy-MM-dd';
}

function getDateRangePickerType(cond: SearchCondition) {
  return cond.dataType === 'datetime' ? 'datetimerange' : 'daterange';
}

function formatSingleDateValue(value: unknown) {
  return typeof value === 'string' ? value : null;
}

function getDateRangeValue(cond: SearchCondition): [string, string] | null {
  if (!cond.value || !cond.value2) return null;
  return [String(cond.value), String(cond.value2)];
}

function handleDateRangeChange(cond: SearchCondition, value: [string, string] | null) {
  cond.value = value?.[0] || '';
  cond.value2 = value?.[1] || '';
  cond.enabled = Boolean(cond.value && cond.value2);
}

function formatLookupValue(value: unknown) {
  if (Array.isArray(value)) {
    return value
      .map(item => String(item ?? '').trim())
      .filter(Boolean)
      .join(', ');
  }
  return value === null || value === undefined ? '' : String(value);
}

function splitLookupValues(value: string) {
  return value
    .split(/[,，]/)
    .map(item => item.trim())
    .filter(Boolean);
}

function normalizeLookupValues(value: unknown) {
  if (Array.isArray(value)) {
    return value
      .flatMap(item => splitLookupValues(String(item ?? '')))
      .filter(Boolean);
  }
  return splitLookupValues(String(value ?? ''));
}

function appendLookupValues(currentValue: unknown, selectedValues: unknown[]) {
  const values = [...normalizeLookupValues(currentValue)];
  const seen = new Set(values.map(value => value.toLowerCase()));

  for (const value of selectedValues) {
    const text = String(value ?? '').trim();
    if (!text) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    values.push(text);
  }

  return values.join(', ');
}

function handleLookupInputChange(cond: SearchCondition, value: string) {
  cond.value = value;
  markEnabled(cond);
}

async function openLookup(cond: SearchCondition) {
  await advancedSearch.value.ensureLookupConditionReady?.(cond);
  currentLookupCondition.value = cond;
  await nextTick();
  await lookupDialogRef.value?.open?.();
}

function handleLookupSelect(fillData: Record<string, any> | Record<string, any>[]) {
  if (!currentLookupCondition.value) return;
  if (isAdvancedSearchMultiValueOperator(currentLookupCondition.value.operator)) {
    const selectedValues = (Array.isArray(fillData) ? fillData : [fillData])
      .map(item => item?.selectedValue)
      .filter(value => value !== null && value !== undefined && String(value).trim().length > 0);
    currentLookupCondition.value.value = appendLookupValues(currentLookupCondition.value.value, selectedValues);
    currentLookupCondition.value.enabled = normalizeLookupValues(currentLookupCondition.value.value).length > 0;
    currentLookupCondition.value = null;
    return;
  }
  const single = Array.isArray(fillData) ? fillData[0] : fillData;
  currentLookupCondition.value.value = single?.selectedValue ?? '';
  currentLookupCondition.value.enabled = String(currentLookupCondition.value.value ?? '').trim().length > 0;
  currentLookupCondition.value = null;
}

function handleLookupCancel() {
  currentLookupCondition.value = null;
}
</script>

<template>
  <NModal v-model:show="showDialog" preset="card" class="advanced-search-modal" :style="modalStyle">
    <template #header>
      <div class="advanced-search-header">
        <span>查询条件</span>
        <NPopover trigger="click" placement="bottom-end">
          <template #trigger>
            <NButton quaternary circle size="small">
              <template #icon>
                <Icon icon="mdi:cog-outline" />
              </template>
            </NButton>
          </template>
          <div class="field-settings">
            <div class="settings-title">显示字段</div>
            <div v-if="hiddenConditions.length === 0" class="field-settings-empty">当前没有可恢复的条件</div>
            <div v-for="cond in hiddenConditions" :key="cond.key" class="field-setting-item">
              <NCheckbox
                :checked="cond.visible"
                size="small"
                @update:checked="checked => checked && showCondition(cond)"
              >
                {{ cond.tableLabel }} · {{ cond.fieldLabel }}
              </NCheckbox>
            </div>
          </div>
        </NPopover>
      </div>
    </template>

    <div class="advanced-search-body">
      <div v-for="cond in visibleConditions" :key="cond.key" class="search-condition-row">
        <NButton quaternary circle size="tiny" class="condition-remove" @click="hideCondition(cond)">
          <template #icon>
            <Icon icon="mdi:close" />
          </template>
        </NButton>
        <div class="condition-label-wrap">
          <NCheckbox v-model:checked="cond.enabled" class="condition-label">
            {{ cond.fieldLabel }}
          </NCheckbox>
          <span class="condition-table-label">{{ cond.tableLabel }}</span>
        </div>
        <NSelect
          v-model:value="cond.operator"
          :options="getOperatorOptions(cond)"
          size="small"
          class="condition-operator"
          @update:value="value => handleOperatorChange(cond, value)"
        />
        <div class="condition-value-wrap">
          <NInput
            v-if="shouldUseTextInput(cond)"
            v-model:value="cond.value"
            size="small"
            class="condition-value"
            :placeholder="isAdvancedSearchMultiValueOperator(cond.operator) ? '多个值用逗号分隔' : '请输入'"
            :show-count="false"
            @input="() => markEnabled(cond)"
            @keyup.enter="advancedSearch.executeSearch"
          />

          <div v-else-if="shouldUseLookupInput(cond)" class="lookup-value-group">
            <NInput
              :value="formatLookupValue(cond.value)"
              size="small"
              class="condition-value"
              :placeholder="
                isAdvancedSearchMultiValueOperator(cond.operator)
                  ? '多个值用逗号分隔，或点右侧选择'
                  : '可直接输入，或点右侧选择'
              "
              :show-count="false"
              clearable
              @update:value="value => handleLookupInputChange(cond, value)"
              @clear="clearConditionValue(cond)"
              @keyup.enter="advancedSearch.executeSearch"
            />
            <NButton size="small" class="lookup-trigger" @click="openLookup(cond)">
              <template #icon>
                <Icon icon="mdi:magnify" />
              </template>
            </NButton>
          </div>

          <NSelect
            v-else-if="shouldUseSelectInput(cond)"
            :value="cond.value"
            :options="cond.options || []"
            :multiple="isAdvancedSearchMultiValueOperator(cond.operator)"
            :loading="!!cond.loadingOptions"
            size="small"
            class="condition-value"
            filterable
            clearable
            @update:value="value => handleSelectValueChange(cond, value)"
          />

          <NInputNumber
            v-else-if="shouldUseNumberInput(cond)"
            :value="cond.value"
            size="small"
            class="condition-value"
            clearable
            :show-button="false"
            @update:value="value => handleSingleValueChange(cond, value)"
          />

          <div v-else-if="shouldUseNumberRangeInput(cond)" class="range-value-group">
            <NInputNumber
              :value="cond.value"
              size="small"
              class="range-value-item"
              clearable
              :show-button="false"
              @update:value="value => handleRangeValueChange(cond, 'start', value)"
            />
            <span class="range-separator">至</span>
            <NInputNumber
              :value="cond.value2"
              size="small"
              class="range-value-item"
              clearable
              :show-button="false"
              @update:value="value => handleRangeValueChange(cond, 'end', value)"
            />
          </div>

          <NDatePicker
            v-else-if="shouldUseDateInput(cond)"
            :type="getDatePickerType(cond)"
            :formatted-value="formatSingleDateValue(cond.value)"
            :value-format="getDateValueFormat(cond)"
            size="small"
            class="condition-value"
            clearable
            @update:formatted-value="value => handleSingleValueChange(cond, value)"
          />

          <NDatePicker
            v-else-if="shouldUseDateRangeInput(cond)"
            :type="getDateRangePickerType(cond)"
            :formatted-value="getDateRangeValue(cond)"
            :value-format="getDateValueFormat(cond)"
            size="small"
            class="condition-value"
            clearable
            @update:formatted-value="value => handleDateRangeChange(cond, value)"
          />
        </div>
      </div>
      <NEmpty v-if="visibleConditions.length === 0" description="暂无可显示的查询条件" size="small" />
    </div>

    <template #footer>
      <div class="advanced-search-footer">
        <div class="advanced-search-summary">
          <span v-if="activeFilterSummaries.length > 0">已启用 {{ activeFilterSummaries.length }} 项</span>
        </div>
        <NSpace :size="8">
          <NButton size="small" @click="advancedSearch.clearSearch">重置</NButton>
          <NButton size="small" @click="advancedSearch.close">取消</NButton>
          <NButton type="primary" size="small" @click="advancedSearch.executeSearch">查询</NButton>
        </NSpace>
      </div>
    </template>
  </NModal>

  <LookupDialog
    ref="lookupDialogRef"
    :lookup-code="currentLookupCode"
    :mapping="currentLookupMapping"
    :multiple="isLookupMultiple"
    @select="handleLookupSelect"
    @cancel="handleLookupCancel"
  />
</template>

<style scoped>
.advanced-search-modal {
  width: 560px;
}

.advanced-search-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.advanced-search-body {
  max-height: 56vh;
  overflow-y: auto;
}

.search-condition-row {
  display: grid;
  grid-template-columns: 24px 126px 110px minmax(200px, 240px);
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

.condition-remove {
  color: #909399;
}

.condition-remove:hover {
  color: #e03131;
}

.condition-label-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.condition-label {
  width: fit-content;
}

.condition-table-label {
  padding-left: 24px;
  color: #8c8c8c;
  font-size: 12px;
  line-height: 1.2;
}

.condition-value-wrap {
  min-width: 0;
  max-width: 240px;
}

.condition-value {
  width: 100%;
}

.range-value-group,
.lookup-value-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.range-value-item {
  flex: 1;
  min-width: 0;
}

.range-separator {
  color: #8c8c8c;
  font-size: 12px;
}

.lookup-trigger {
  flex-shrink: 0;
}

.field-settings {
  max-height: 320px;
  min-width: 280px;
  overflow-y: auto;
}

.field-settings-empty {
  color: #8c8c8c;
  font-size: 12px;
}

.settings-title {
  margin-bottom: 8px;
  font-weight: 600;
}

.field-setting-item {
  margin-bottom: 6px;
}

.advanced-search-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.advanced-search-summary {
  color: #8c8c8c;
  font-size: 12px;
}
</style>
