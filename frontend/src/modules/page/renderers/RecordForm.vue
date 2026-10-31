<script setup lang="ts">
/**
 * 原地表单（FP-03）：主表区和每个明细区用同一个组件，在这个区域原地替换表格显示（表格只设为不可见，滚动位置和选中行保留，
 * 见 RegionPane.vue），其他区域不动。头部有返回、上一条、下一条。
 * 内容来自 record-form.ts：与表格同一份区域元数据和同一个编辑缓冲（撤销、重做、预览、保存同表格，FP-04）。每个字段显示的与表格
 * 同一格相同（marks.ts）：改动标记和错误标记（样式 marks.css）、悬停时的错误提示、对比（箭头和差值写在输入框下面，颜色同表格）、
 * 界面规则的单元格样式；行的标记和界面规则的行样式加在表单主体上。数值右对齐、布尔字段不能改时是不能勾的复选框，同表格。
 * 只有排布按区域的 formLayout（24 列网格），为空时每行 3 个字段。
 * 被冻结的单据点击字段时弹出审批进度（FP-16）。
 */
import { computed, reactive, watch } from 'vue';
import type { PageRuntime } from '../page-runtime';
import { parseInput } from '../fields';
import { type FormItem, formView } from '../record-form';

defineOptions({ name: 'RecordForm' });

const props = defineProps<{ runtime: PageRuntime; entity: string }>();
const runtime = props.runtime;

const form = computed(() => {
  // 页面视图（配置原地替换）、数据（编辑、预览、保存）、字典变了都重算；保存中（只读）经 cellEditable 读到
  void runtime.state.viewVersion;
  void runtime.state.revision;
  void runtime.state.dictVersion;
  return formView(runtime, props.entity)!;
});

/** 字段的位置和大小，加上界面规则给这一格的样式（同表格这一格） */
function cellStyle(item: FormItem) {
  const { x, y, w, h } = item.cell;
  return { ...item.style, gridColumn: `${x + 1} / span ${w}`, gridRow: `${y + 1} / span ${h}` };
}

/** 文本和数值在离开输入框或回车时提交（每次提交是一个撤销步骤）；换了行时清掉没提交的输入 */
const drafts = reactive(new Map<string, string>());
watch(
  () => form.value.gridId,
  () => drafts.clear()
);

function draftOf(item: FormItem) {
  return drafts.get(item.field.name) ?? String(item.value ?? '');
}

function commit(item: FormItem, raw: unknown) {
  drafts.delete(item.field.name);
  const value = parseInput(item.field, raw);
  if (value === undefined) {
    runtime.state.error = `${item.field.label} 不是合法的数值`;
    return;
  }
  if (value === item.value) return;
  runtime.editForm(props.entity, item.field.name, value);
}

/** 被冻结的单据：试图修改时弹出审批进度 */
function onFocusField() {
  if (form.value.frozenBy) runtime.guard(props.entity, form.value.id);
}

function openLookup(item: FormItem) {
  void runtime.openLookup(props.entity, form.value.gridId, item.field.name);
}
</script>

<template>
  <div class="record-form h-full flex-col">
    <div class="record-form__header flex-y-center gap-8px">
      <NButton size="small" @click="runtime.closeForm(entity)">返回</NButton>
      <NButton size="small" @click="runtime.stepForm(entity, -1)">上一条</NButton>
      <NButton size="small" @click="runtime.stepForm(entity, 1)">下一条</NButton>
      <span class="ml-8px text-14px font-medium">{{ form.title }}</span>
      <span v-if="form.frozenBy" class="text-12px text-warning">审批 {{ form.frozenBy }} 中，只读</span>
    </div>
    <div class="record-form__body" :class="form.rowMarks" :style="form.rowStyle">
      <div
        v-for="item in form.items"
        :key="item.field.name"
        class="record-form__cell"
        :class="[item.marks, { 'record-form__cell--number': item.field.type === 'number' }]"
        :data-field="item.field.name"
        :style="cellStyle(item)"
        :title="item.tooltip"
      >
        <div class="record-form__label">
          <span v-if="item.required" class="text-error">*</span>
          {{ item.field.label }}
        </div>
        <div class="record-form__control" @mousedown="onFocusField">
          <template v-if="item.field.lookup">
            <NInputGroup>
              <NInput size="small" :value="item.text" readonly />
              <NButton size="small" @click="openLookup(item)">选择</NButton>
            </NInputGroup>
          </template>
          <template v-else-if="item.field.type === 'boolean'">
            <!-- 同表格的复选框：不能改时不能勾 -->
            <NCheckbox
              :checked="item.value === true"
              :disabled="!item.editable"
              @update:checked="(v: boolean) => commit(item, v)"
            />
          </template>
          <template v-else-if="!item.editable">
            <NInput size="small" :value="item.text" readonly />
          </template>
          <template v-else-if="item.options">
            <NSelect
              size="small"
              clearable
              :tag="Boolean(item.field.dictFreeText)"
              :filterable="Boolean(item.field.dictFreeText)"
              :value="(item.value as string | null) ?? null"
              :options="item.options"
              @update:value="(v: string | null) => commit(item, v)"
            />
          </template>
          <template v-else-if="item.field.type === 'date' || item.field.type === 'datetime'">
            <NDatePicker
              size="small"
              clearable
              class="w-full"
              :type="item.field.type === 'date' ? 'date' : 'datetime'"
              :value-format="item.field.type === 'date' ? 'yyyy-MM-dd' : 'yyyy-MM-dd HH:mm:ss'"
              :formatted-value="item.text || null"
              @update:formatted-value="(v: string | null) => commit(item, v)"
            />
          </template>
          <template v-else>
            <NInput
              size="small"
              :value="draftOf(item)"
              :input-props="{ inputmode: item.field.type === 'number' ? 'decimal' : 'text' }"
              @update:value="(v: string) => drafts.set(item.field.name, v)"
              @change="(v: string) => commit(item, v)"
            />
          </template>
        </div>
        <!-- 对比：与表格这一格相同的箭头、差值和颜色（只读、可编辑的字段都显示） -->
        <div v-if="item.compare" class="record-form__compare cell-compare" :style="{ color: item.compare.color }">
          {{ item.compare.arrow }}{{ item.compare.text }}
        </div>
        <div v-if="item.error" class="record-form__error">{{ item.error }}</div>
      </div>
    </div>
  </div>
</template>

<!-- 字段的改动标记和错误标记、表单主体的行的标记：与表格共用（marks.ts） -->
<style src="../marks.css"></style>

<style scoped>
.record-form {
  background: #fff;
}

.record-form__header {
  padding: 6px 12px;
  border-bottom: 1px solid #eef2f7;
  flex-shrink: 0;
}

/* 文字颜色是标签的默认颜色：行样式、行的标记（marks.css）、单元格样式和改动标记的颜色经继承加到标签上 */
.record-form__body {
  display: grid;
  grid-template-columns: repeat(24, minmax(0, 1fr));
  grid-auto-rows: minmax(52px, auto);
  gap: 8px 12px;
  padding: 12px;
  overflow: auto;
  color: #64748b;
}

.record-form__cell {
  padding: 2px 6px 4px;
  border-radius: 4px;
}

.record-form__label {
  font-size: 12px;
  margin-bottom: 4px;
}

/* 数值右对齐，同表格 */
.record-form__cell--number :deep(.n-input__input-el) {
  text-align: right;
}

.record-form__compare {
  font-size: 11px;
  margin-top: 2px;
}

/* 数值的对比跟着值靠右，同表格 */
.record-form__cell--number .record-form__compare {
  text-align: right;
}

.record-form__error {
  font-size: 12px;
  color: #d03050;
  margin-top: 2px;
}
</style>
