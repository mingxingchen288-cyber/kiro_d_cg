<script setup lang="ts">
import { nextTick, ref } from 'vue';
import { NDatePicker } from 'naive-ui';

type CellEditorParams = {
  value?: unknown;
  stopEditing?: () => void;
};

const props = defineProps<{
  params: CellEditorParams;
}>();

const editorRef = ref<HTMLElement | null>(null);
const formattedValue = ref<string | null>(normalizeDateValue(props.params.value));

function normalizeDateValue(value: unknown): string | null {
  if (value == null || value === '') return null;
  if (typeof value === 'string') {
    const trimmed = value.trim();
    const match = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : trimmed;
  }
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return formatLocalDate(value);
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : formatLocalDate(date);
  }
  return String(value);
}

function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function handleUpdate(value: string | [string, string] | null) {
  formattedValue.value = Array.isArray(value) ? value[0] || null : value;
  void nextTick(() => props.params.stopEditing?.());
}

function getValue() {
  return formattedValue.value || null;
}

function afterGuiAttached() {
  editorRef.value?.focus();
}

defineExpose({
  getValue,
  afterGuiAttached
});
</script>

<template>
  <div ref="editorRef" class="meta-date-cell-editor ag-custom-component-popup" tabindex="-1">
    <NDatePicker
      panel
      type="date"
      format="yyyy-MM-dd"
      value-format="yyyy-MM-dd"
      :formatted-value="formattedValue"
      @update:formatted-value="handleUpdate"
    />
  </div>
</template>

<style scoped>
.meta-date-cell-editor {
  padding: 6px;
  outline: none;
  background: var(--n-color, #fff);
}
</style>
