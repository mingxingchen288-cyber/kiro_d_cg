<script setup lang="ts">
/**
 * 高级查询对话框（FP-22，systemButtons 含 advancedSearch 时提供），同旧系统 AdvancedSearchDialog.vue：标题"查询条件"，
 * 一打开就列出预置条件（页面视图中 searchable 的可见字段，advanced-search.ts 的 presetConditions）。每行为隐藏、勾选框和
 * 字段名（下方小字为表）、运算符、值；填了值自动勾上。有 Lookup 的字段值框旁有"选择"，用通用页的 Lookup 对话框选值，
 * IN、NOT IN 时多选。右上角"显示字段"恢复隐藏了的条件。底部同旧系统："已启用 N 项"，重置、取消、查询。
 * 新平台另有"添加条件"（选表和字段）、主表条件之间的且/或、添加的明细条件的组（C09 第 4 节）。
 */
import { computed, ref, watch } from 'vue';
import type { FieldValues } from '../../../contracts/command';
import type { PageView, ViewField } from '../../../contracts/page-view';
import {
  type ConditionDraft,
  buildAdvanced,
  conditionField,
  emptyCondition,
  enabledCount,
  hideCondition,
  needsNoValue,
  needsTwoValues,
  operatorsFor,
  pickLookup,
  resetConditions,
  selectOptions,
  setField,
  setOperator,
  setTable,
  setValue,
  splitList,
  syncConditions,
  tableLabel,
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

const shownDrafts = computed(() => drafts.value.filter(d => d.visible));
const hiddenDrafts = computed(() => drafts.value.filter(d => d.preset && !d.visible));
const count = computed(() => enabledCount(view.value, drafts.value));

const tableOptions = computed(() => [
  { label: '主表', value: '' },
  ...view.value.details.map(d => ({ label: d.title, value: d.entity }))
]);

const BOOLEAN_OPTIONS = [
  { label: '是', value: 'true' },
  { label: '否', value: 'false' }
];

function fieldOptions(draft: ConditionDraft) {
  const region = draft.entity ? view.value.details.find(d => d.entity === draft.entity) : view.value.master;
  return (region?.fields ?? []).filter(f => f.visible).map(f => ({ label: f.label, value: f.name }));
}

const meta = (draft: ConditionDraft) => conditionField(view.value, draft);

function operatorOptions(draft: ConditionDraft) {
  const field = meta(draft);
  return field ? operatorsFor(field.type) : [];
}

/** 下拉选择的选项（字典、选项值）；`dictVersion` 让字典读到后重算 */
function optionsOf(field: ViewField) {
  void runtime.state.dictVersion;
  return selectOptions(field, runtime.dicts);
}

type ValueKind = 'none' | 'boolean' | 'select' | 'date' | 'text';

function kindOf(draft: ConditionDraft): ValueKind {
  const field = meta(draft);
  if (!field || needsNoValue(draft.operator)) return 'none';
  if (field.type === 'boolean') return 'boolean';
  if (optionsOf(field)) return 'select';
  if (field.type === 'date' || field.type === 'datetime') return 'date';
  return 'text';
}

const canLookup = (draft: ConditionDraft) => Boolean(meta(draft)?.lookup) && !needsTwoValues(draft.operator);

function changeOperator(draft: ConditionDraft, operator: string) {
  const field = meta(draft);
  setOperator(draft, operator, Boolean(field && (field.lookup || optionsOf(field))));
}

function selectValue(draft: ConditionDraft) {
  return takesList(draft.operator) ? splitList(draft.value) : draft.value || null;
}

function changeSelect(draft: ConditionDraft, value: string | string[] | null) {
  setValue(draft, Array.isArray(value) ? value.join(',') : value);
}

const dateFormat = (draft: ConditionDraft) => (meta(draft)?.type === 'datetime' ? 'yyyy-MM-dd HH:mm:ss' : 'yyyy-MM-dd');

function openLookup(draft: ConditionDraft) {
  const field = meta(draft);
  if (!field) return;
  const entity = draft.entity ?? view.value.master.entity;
  void runtime.openSearchLookup(entity, field.name, {
    multiple: takesList(draft.operator),
    select: (rows: FieldValues[]) => pickLookup(draft, field, rows)
  });
}

function open() {
  drafts.value = syncConditions(view.value, runtime.personal, drafts.value);
}

watch(show, value => {
  if (value) open();
});

function add() {
  drafts.value.push(emptyCondition(view.value));
}

function remove(draft: ConditionDraft) {
  if (draft.preset) hideCondition(draft);
  else drafts.value = drafts.value.filter(d => d !== draft);
}

function reset() {
  drafts.value = resetConditions(drafts.value);
  op.value = 'and';
  runtime.applyAdvanced(null);
}

function search() {
  runtime.applyAdvanced(buildAdvanced(view.value, drafts.value, op.value));
  show.value = false;
}
</script>

<template>
  <NModal v-model:show="show">
    <NCard class="advanced-search" title="查询条件" :bordered="false" size="small" closable @close="show = false">
      <template #header-extra>
        <NPopover trigger="click" placement="bottom-end">
          <template #trigger>
            <NButton quaternary size="small" class="mr-8px">显示字段</NButton>
          </template>
          <div class="advanced-search__settings">
            <div class="mb-8px font-600">显示字段</div>
            <div v-if="hiddenDrafts.length === 0" class="text-12px text-#8c8c8c">当前没有可恢复的条件</div>
            <div v-for="draft in hiddenDrafts" :key="draft.key" class="mb-6px">
              <NCheckbox
                :checked="false"
                size="small"
                @update:checked="(checked: boolean) => checked && (draft.visible = true)"
              >
                {{ tableLabel(view, draft.entity) }} · {{ meta(draft)?.label ?? draft.field }}
              </NCheckbox>
            </div>
          </div>
        </NPopover>
      </template>
      <div class="mb-8px flex-y-center gap-8px text-12px">
        <span>主表条件之间：</span>
        <NRadioGroup v-model:value="op" size="small">
          <NRadio value="and">且</NRadio>
          <NRadio value="or">或</NRadio>
        </NRadioGroup>
      </div>
      <div class="advanced-search__body">
        <div
          v-for="draft in shownDrafts"
          :key="draft.key"
          class="advanced-search__row"
          :data-testid="`condition-${draft.key}`"
        >
          <NButton
            quaternary
            circle
            size="tiny"
            class="advanced-search__remove"
            :title="draft.preset ? '隐藏这个条件' : '删除这个条件'"
            @click="remove(draft)"
          >
            ×
          </NButton>
          <div class="advanced-search__label">
            <NCheckbox v-model:checked="draft.enabled">
              <template v-if="draft.preset">{{ meta(draft)?.label ?? draft.field }}</template>
            </NCheckbox>
            <span v-if="draft.preset" class="advanced-search__table">{{ tableLabel(view, draft.entity) }}</span>
            <template v-else>
              <NSelect
                size="small"
                class="w-110px"
                :value="draft.entity ?? ''"
                :options="tableOptions"
                @update:value="(v: string) => setTable(view, draft, v || null)"
              />
              <NSelect
                size="small"
                class="w-140px"
                filterable
                :value="draft.field"
                :options="fieldOptions(draft)"
                @update:value="(v: string) => setField(view, draft, v)"
              />
            </template>
          </div>
          <NSelect
            size="small"
            class="w-110px"
            :value="draft.operator"
            :options="operatorOptions(draft)"
            @update:value="(v: string) => changeOperator(draft, v)"
          />
          <div class="advanced-search__value">
            <NSelect
              v-if="kindOf(draft) === 'boolean'"
              size="small"
              :value="draft.value || null"
              :options="BOOLEAN_OPTIONS"
              @update:value="(v: string | null) => setValue(draft, v)"
            />
            <NSelect
              v-else-if="kindOf(draft) === 'select'"
              size="small"
              filterable
              clearable
              :multiple="takesList(draft.operator)"
              :value="selectValue(draft)"
              :options="optionsOf(meta(draft)!) ?? []"
              @update:value="(v: string | string[] | null) => changeSelect(draft, v)"
            />
            <template v-else-if="kindOf(draft) === 'date'">
              <NDatePicker
                size="small"
                clearable
                :type="meta(draft)?.type === 'datetime' ? 'datetime' : 'date'"
                :value-format="dateFormat(draft)"
                :formatted-value="draft.value || null"
                @update:formatted-value="(v: string | null) => setValue(draft, v)"
              />
              <template v-if="needsTwoValues(draft.operator)">
                <span class="advanced-search__to">至</span>
                <NDatePicker
                  size="small"
                  clearable
                  :type="meta(draft)?.type === 'datetime' ? 'datetime' : 'date'"
                  :value-format="dateFormat(draft)"
                  :formatted-value="draft.value2 || null"
                  @update:formatted-value="(v: string | null) => setValue(draft, v, true)"
                />
              </template>
            </template>
            <template v-else-if="kindOf(draft) === 'text'">
              <NInput
                size="small"
                clearable
                :value="draft.value"
                :placeholder="
                  takesList(draft.operator)
                    ? canLookup(draft)
                      ? '多个值用逗号分隔，或点右侧选择'
                      : '多个值用逗号分隔'
                    : canLookup(draft)
                      ? '可直接输入，或点右侧选择'
                      : '请输入'
                "
                @update:value="(v: string) => setValue(draft, v)"
                @keyup.enter="search"
              />
              <template v-if="needsTwoValues(draft.operator)">
                <span class="advanced-search__to">至</span>
                <NInput
                  size="small"
                  clearable
                  :value="draft.value2"
                  placeholder="请输入"
                  @update:value="(v: string) => setValue(draft, v, true)"
                  @keyup.enter="search"
                />
              </template>
              <NButton v-if="canLookup(draft)" size="small" class="advanced-search__lookup" @click="openLookup(draft)">
                选择
              </NButton>
            </template>
          </div>
          <template v-if="!draft.preset && draft.entity">
            <NInput v-model:value="draft.group" size="small" class="w-60px" placeholder="组" />
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
        </div>
        <NEmpty v-if="shownDrafts.length === 0" description="暂无可显示的查询条件" size="small" />
      </div>
      <NButton size="small" dashed class="mt-8px" @click="add">添加条件</NButton>
      <div class="mt-8px text-12px text-#999">
        同一明细表的条件由同一条明细行同时满足；添加的明细条件按组合并，组内第二条起按"且/或"与前一条组合。
      </div>
      <template #footer>
        <div class="flex-y-center justify-between">
          <span class="text-12px text-#8c8c8c">
            <template v-if="count > 0">已启用 {{ count }} 项</template>
          </span>
          <NSpace :size="8">
            <NButton size="small" @click="reset">重置</NButton>
            <NButton size="small" @click="show = false">取消</NButton>
            <NButton type="primary" size="small" @click="search">查询</NButton>
          </NSpace>
        </div>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
.advanced-search {
  width: 760px;
  max-width: calc(100vw - 100px);
}

.advanced-search__body {
  max-height: 56vh;
  overflow-y: auto;
}

.advanced-search__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.advanced-search__remove {
  flex-shrink: 0;
  color: #909399;
}

.advanced-search__remove:hover {
  color: #e03131;
}

.advanced-search__label {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px 6px;
  width: 280px;
  flex-shrink: 0;
}

.advanced-search__table {
  width: 100%;
  padding-left: 24px;
  color: #8c8c8c;
  font-size: 12px;
  line-height: 1.2;
}

.advanced-search__value {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.advanced-search__to {
  color: #8c8c8c;
  font-size: 12px;
}

.advanced-search__lookup {
  flex-shrink: 0;
}

.advanced-search__settings {
  max-height: 320px;
  min-width: 280px;
  overflow-y: auto;
}
</style>
