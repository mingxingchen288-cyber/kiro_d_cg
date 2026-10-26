<script setup lang="ts">
import { computed, nextTick, ref } from 'vue';
import { NSelect } from 'naive-ui';

type CellEditorParams = {
  value?: unknown;
  values?: unknown[];
  stopEditing?: () => void;
};

const props = defineProps<{
  params: CellEditorParams;
}>();

const selectRef = ref<any>(null);
const currentValue = ref<string | null>(normalizeValue(props.params.value));

function normalizeValue(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  return String(value);
}

const options = computed(() => {
  const values = Array.isArray(props.params.values) ? props.params.values : [];
  const result = values
    .map(value => normalizeValue(value))
    .filter((value): value is string => Boolean(value))
    .map(value => ({ label: value, value }));

  if (currentValue.value && !result.some(item => item.value === currentValue.value)) {
    result.unshift({ label: currentValue.value, value: currentValue.value });
  }

  return result;
});

function handleUpdate(value: string | null) {
  currentValue.value = normalizeValue(value);
  void nextTick(() => props.params.stopEditing?.());
}

function getValue() {
  return currentValue.value;
}

function afterGuiAttached() {
  void nextTick(() => selectRef.value?.focus?.());
}

defineExpose({
  getValue,
  afterGuiAttached
});
</script>

<template>
  <div class="tag-select-cell-editor ag-custom-component-popup">
    <NSelect
      ref="selectRef"
      :value="currentValue"
      :options="options"
      tag
      filterable
      clearable
      size="small"
      placeholder="选择或输入"
      to="body"
      @update:value="handleUpdate"
    />
  </div>
</template>

<style scoped>
.tag-select-cell-editor {
  width: 220px;
  padding: 4px;
  background: #fff;
}
</style>
