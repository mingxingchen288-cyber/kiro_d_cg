<script setup lang="ts">
/**
 * 原地表单（FP-03）：在主表区原地替换表格显示（表格只设为不可见，滚动位置和选中行保留），明细区不动。
 * 头部有返回、上一条、下一条；按页面视图的 formLayout（24 列网格）排列，为空时按字段顺序排列。
 * 表单中的修改与表格共用编辑缓冲和撤销历史（FP-04）；被冻结的单据点击字段时弹出审批进度（FP-16）。
 */
import { computed, reactive, watch } from 'vue';
import type { FieldValue } from '../../../contracts/command';
import type { FormCell, ViewField } from '../../../contracts/page-view';
import { displayText, optionValues, parseInput } from '../fields';
import type { PageRuntime } from '../page-runtime';

defineOptions({ name: 'RecordForm' });

const props = defineProps<{ runtime: PageRuntime }>();
const runtime = props.runtime;

const view = computed(() => {
  void runtime.state.viewVersion;
  return runtime.view.value!;
});
const master = computed(() => view.value.master);
const recordId = computed(() => runtime.state.formRecord!);
const gridId = computed(() => runtime.model.gridId(recordId.value));

const values = computed(() => {
  void runtime.state.revision;
  return runtime.model.values(master.value.entity, recordId.value);
});

const frozenBy = computed(() => {
  void runtime.state.revision;
  return runtime.model.frozenBy(master.value.entity, recordId.value);
});

const title = computed(() => {
  const key = values.value[master.value.primaryKey];
  return key ? `单据 ${key}` : '新增的单据（未保存）';
});

/** 24 列网格中的位置；formLayout 为空时每行 3 个字段 */
const cells = computed<Array<{ field: ViewField; cell: FormCell }>>(() => {
  const visible = master.value.fields.filter(f => f.visible);
  const layout = master.value.formLayout;
  if (layout.length) {
    return layout
      .map(cell => ({ field: visible.find(f => f.name === cell.field), cell }))
      .filter((item): item is { field: ViewField; cell: FormCell } => Boolean(item.field));
  }
  return visible.map((field, index) => ({
    field,
    cell: { field: field.name, x: (index % 3) * 8, y: Math.floor(index / 3), w: 8, h: 1 }
  }));
});

function cellStyle(cell: FormCell) {
  return { gridColumn: `${cell.x + 1} / span ${cell.w}`, gridRow: `${cell.y + 1} / span ${cell.h}` };
}

function editable(field: ViewField) {
  void runtime.state.revision;
  void runtime.state.saving;
  return runtime.cellEditable(master.value.entity, gridId.value, field.name);
}

function dictOptions(field: ViewField) {
  void runtime.state.dictVersion;
  const dict = field.dictType ? runtime.dicts.get(field.dictType) : undefined;
  if (dict) return [...dict].map(([value, label]) => ({ value, label }));
  const options = optionValues(field);
  return options ? options.map(value => ({ value, label: value })) : null;
}

function text(field: ViewField) {
  const dict = field.dictType ? runtime.dicts.get(field.dictType) : undefined;
  return displayText(field, values.value[field.name] ?? null, dict);
}

/** 文本和数值在离开输入框或回车时提交（每次提交是一个撤销步骤） */
const drafts = reactive<Record<string, string>>({});
watch(recordId, () => {
  for (const key of Object.keys(drafts)) delete drafts[key];
});

function draftOf(field: ViewField) {
  return field.name in drafts ? drafts[field.name] : String(values.value[field.name] ?? '');
}

function commit(field: ViewField, raw: unknown) {
  delete drafts[field.name];
  const value = parseInput(field, raw);
  if (value === undefined) {
    runtime.state.error = `${field.label} 不是合法的数值`;
    return;
  }
  if (value === (values.value[field.name] ?? null)) return;
  runtime.editForm(field.name, value as FieldValue);
}

/** 被冻结的单据：试图修改时弹出审批进度 */
function onFocusField() {
  if (frozenBy.value) runtime.guard(master.value.entity, recordId.value);
}

function openLookup(field: ViewField) {
  void runtime.openLookup(master.value.entity, gridId.value, field.name);
}
</script>

<template>
  <div class="record-form h-full flex-col">
    <div class="record-form__header flex-y-center gap-8px">
      <NButton size="small" @click="runtime.closeForm()">返回</NButton>
      <NButton size="small" @click="runtime.stepForm(-1)">上一条</NButton>
      <NButton size="small" @click="runtime.stepForm(1)">下一条</NButton>
      <span class="ml-8px text-14px font-medium">{{ title }}</span>
      <span v-if="frozenBy" class="text-12px text-warning">审批 {{ frozenBy }} 中，只读</span>
    </div>
    <div class="record-form__body">
      <div v-for="{ field, cell } in cells" :key="field.name" class="record-form__cell" :style="cellStyle(cell)">
        <div class="record-form__label">
          <span v-if="runtime.model.cellRequired(master.entity, recordId, field.name)" class="text-error">*</span>
          {{ field.label }}
        </div>
        <div class="record-form__control" @mousedown="onFocusField">
          <template v-if="field.lookup">
            <NInputGroup>
              <NInput size="small" :value="text(field)" readonly />
              <NButton size="small" @click="openLookup(field)">选择</NButton>
            </NInputGroup>
          </template>
          <template v-else-if="!editable(field)">
            <NInput size="small" :value="text(field)" readonly />
          </template>
          <template v-else-if="field.type === 'boolean'">
            <NCheckbox :checked="values[field.name] === true" @update:checked="(v: boolean) => commit(field, v)" />
          </template>
          <template v-else-if="dictOptions(field)">
            <NSelect
              size="small"
              clearable
              :value="(values[field.name] as string | null) ?? null"
              :options="dictOptions(field)!"
              @update:value="(v: string | null) => commit(field, v)"
            />
          </template>
          <template v-else-if="field.type === 'date' || field.type === 'datetime'">
            <NDatePicker
              size="small"
              clearable
              class="w-full"
              :type="field.type === 'date' ? 'date' : 'datetime'"
              :value-format="field.type === 'date' ? 'yyyy-MM-dd' : 'yyyy-MM-dd HH:mm:ss'"
              :formatted-value="text(field) || null"
              @update:formatted-value="(v: string | null) => commit(field, v)"
            />
          </template>
          <template v-else>
            <NInput
              size="small"
              :value="draftOf(field)"
              :input-props="{ inputmode: field.type === 'number' ? 'decimal' : 'text' }"
              @update:value="(v: string) => (drafts[field.name] = v)"
              @change="(v: string) => commit(field, v)"
            />
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.record-form {
  background: #fff;
}

.record-form__header {
  padding: 6px 12px;
  border-bottom: 1px solid #eef2f7;
  flex-shrink: 0;
}

.record-form__body {
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  grid-auto-rows: minmax(52px, auto);
  gap: 8px 12px;
  padding: 12px;
  overflow: auto;
}

.record-form__label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 4px;
}
</style>
