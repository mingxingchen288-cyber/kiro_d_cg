<script setup lang="ts">
/**
 * grid-adapter：字典下拉、可以填写字典以外的值的单元格编辑器（C05 `dictFreeText`），同旧系统
 * TagSelectCellEditor.vue（"下拉（可填写）"）：naive-ui NSelect 的 tag、filterable、clearable，单值，选中或填写后即结束编辑。
 * 选项为字典项（显示 label，保存 value）；单元格当前的值不在字典中时也列在最前面。下拉菜单挂在 body 上，
 * 带 `ag-custom-component-popup`，点选项时表格不因"单元格失去焦点"而结束编辑（PageGrid 设了 stopEditingWhenCellsLoseFocus）。
 */
import { computed, nextTick, ref } from 'vue';
import type { SelectOption } from 'naive-ui';

defineOptions({ name: 'DictSelectCellEditor' });

interface Option {
  value: string;
  label: string;
}

const props = defineProps<{
  params: { value?: unknown; options?: Option[]; stopEditing?: () => void };
}>();

function normalize(value: unknown): string | null {
  return value === null || value === undefined || value === '' ? null : String(value);
}

const selectRef = ref<{ focus?: () => void } | null>(null);
const current = ref<string | null>(normalize(props.params.value));

const options = computed<SelectOption[]>(() => {
  const list: SelectOption[] = (props.params.options ?? []).map(o => ({ value: o.value, label: o.label }));
  if (current.value !== null && !list.some(o => o.value === current.value))
    list.unshift({ value: current.value, label: current.value });
  return list;
});

function onUpdate(value: string | null) {
  current.value = normalize(value);
  void nextTick(() => props.params.stopEditing?.());
}

function getValue() {
  return current.value;
}

function isPopup() {
  return true;
}

function afterGuiAttached() {
  void nextTick(() => selectRef.value?.focus?.());
}

defineExpose({ getValue, isPopup, afterGuiAttached });
</script>

<template>
  <div class="dict-select-cell-editor ag-custom-component-popup">
    <NSelect
      ref="selectRef"
      :value="current"
      :options="options"
      tag
      filterable
      clearable
      size="small"
      placeholder="选择或输入"
      to="body"
      :menu-props="{ class: 'ag-custom-component-popup' }"
      @update:value="onUpdate"
    />
  </div>
</template>

<style scoped>
.dict-select-cell-editor {
  width: 220px;
  padding: 4px;
  background: #fff;
}
</style>
