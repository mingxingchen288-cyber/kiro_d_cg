<script setup lang="ts">
/**
 * 人员管理、部门管理的高级查询对话框（FM-06），样子和交互同 frontend-page 的高级查询（FP-22）和旧系统
 * AdvancedSearchDialog.vue：标题"查询条件"，一打开就列出能查的列；每行为隐藏（×）、勾选框和字段名、运算符、值，
 * 填了值自动勾上；右上角"显示字段"恢复隐藏了的条件；底部"已启用 N 项"、重置、取消、查询。
 * 条件之间都是"且"，没有"添加条件"（旧对话框也没有）。条件的规则在 advanced-search.ts。
 *
 * 对话框改的是条件的副本：点"查询"时把条件交给面板（`search`），点"取消"或关掉时不改面板里的条件。
 */
import { computed, ref, watch } from 'vue';
import { NButton, NCard, NCheckbox, NInput, NModal, NPopover, NSelect, NSpace } from 'naive-ui';
import {
  type ConditionDraft,
  ENABLED_OPTIONS,
  type SearchField,
  type SearchOption,
  enabledCount,
  hideCondition,
  needsNoValue,
  needsTwoValues,
  operatorsFor,
  resetConditions,
  setOperator,
  setValue,
  splitList,
  takesList
} from '../advanced-search';

defineOptions({ name: 'AdminAdvancedSearchDialog' });

const props = defineProps<{
  fields: SearchField[];
  /** 当前的条件（面板保存的） */
  drafts: ConditionDraft[];
  /** 下拉选择的字段的选项，例如"部门"为部门列表 */
  options?: Record<string, SearchOption[]>;
}>();
const show = defineModel<boolean>('show', { default: false });
const emit = defineEmits<{ search: [drafts: ConditionDraft[]]; reset: [drafts: ConditionDraft[]] }>();

/** 对话框里正在改的条件（面板条件的副本） */
const editing = ref<ConditionDraft[]>([]);
const shownDrafts = computed(() => editing.value.filter(d => d.visible));
const hiddenDrafts = computed(() => editing.value.filter(d => !d.visible));
const count = computed(() => enabledCount(props.fields, editing.value));
const copy = () => editing.value.map(d => ({ ...d }));

watch(show, value => {
  if (value) editing.value = props.drafts.map(d => ({ ...d }));
});

const fieldOf = (draft: ConditionDraft) => props.fields.find(f => f.name === draft.field)!;

function optionsOf(draft: ConditionDraft): SearchOption[] {
  const field = fieldOf(draft);
  return field.type === 'boolean' ? ENABLED_OPTIONS : (props.options?.[field.name] ?? []);
}

type ValueKind = 'none' | 'select' | 'text';

function kindOf(draft: ConditionDraft): ValueKind {
  if (needsNoValue(draft.operator)) return 'none';
  const type = fieldOf(draft).type;
  return type === 'select' || type === 'boolean' ? 'select' : 'text';
}

function changeOperator(draft: ConditionDraft, operator: string) {
  setOperator(draft, operator, kindOf(draft) === 'select');
}

function selectValue(draft: ConditionDraft) {
  return takesList(draft.operator) ? splitList(draft.value) : draft.value || null;
}

function changeSelect(draft: ConditionDraft, value: string | string[] | null) {
  setValue(draft, Array.isArray(value) ? value.join(',') : value);
}

function reset() {
  editing.value = resetConditions(editing.value);
  emit('reset', copy());
}

function search() {
  emit('search', copy());
  show.value = false;
}
</script>

<template>
  <NModal v-model:show="show">
    <NCard
      class="admin-advanced-search"
      title="查询条件"
      :bordered="false"
      size="small"
      closable
      data-testid="admin-advanced-search"
      @close="show = false"
    >
      <template #header-extra>
        <NPopover trigger="click" placement="bottom-end">
          <template #trigger>
            <NButton quaternary size="small" class="mr-8px">显示字段</NButton>
          </template>
          <div class="admin-advanced-search__settings">
            <div class="mb-8px font-600">显示字段</div>
            <div v-if="hiddenDrafts.length === 0" class="text-12px text-#8c8c8c">当前没有可恢复的条件</div>
            <div v-for="draft in hiddenDrafts" :key="draft.key" class="mb-6px">
              <NCheckbox
                :checked="false"
                size="small"
                @update:checked="(checked: boolean) => checked && (draft.visible = true)"
              >
                {{ fieldOf(draft).label }}
              </NCheckbox>
            </div>
          </div>
        </NPopover>
      </template>
      <div class="admin-advanced-search__body">
        <div
          v-for="draft in shownDrafts"
          :key="draft.key"
          class="admin-advanced-search__row"
          :data-testid="`condition-${draft.key}`"
        >
          <NButton
            quaternary
            circle
            size="tiny"
            class="admin-advanced-search__remove"
            title="隐藏这个条件"
            @click="hideCondition(draft)"
          >
            ×
          </NButton>
          <div class="admin-advanced-search__label">
            <NCheckbox v-model:checked="draft.enabled">{{ fieldOf(draft).label }}</NCheckbox>
          </div>
          <NSelect
            size="small"
            class="w-110px"
            :value="draft.operator"
            :options="operatorsFor(fieldOf(draft).type)"
            :virtual-scroll="false"
            @update:value="(v: string) => changeOperator(draft, v)"
          />
          <div class="admin-advanced-search__value">
            <NSelect
              v-if="kindOf(draft) === 'select'"
              size="small"
              filterable
              clearable
              :multiple="takesList(draft.operator)"
              :value="selectValue(draft)"
              :options="optionsOf(draft)"
              @update:value="(v: string | string[] | null) => changeSelect(draft, v)"
            />
            <template v-else-if="kindOf(draft) === 'text'">
              <NInput
                size="small"
                clearable
                :value="draft.value"
                :placeholder="takesList(draft.operator) ? '多个值用逗号分隔' : '请输入'"
                @update:value="(v: string) => setValue(draft, v)"
                @keyup.enter="search"
              />
              <template v-if="needsTwoValues(draft.operator)">
                <span class="admin-advanced-search__to">至</span>
                <NInput
                  size="small"
                  clearable
                  :value="draft.value2"
                  placeholder="请输入"
                  @update:value="(v: string) => setValue(draft, v, true)"
                  @keyup.enter="search"
                />
              </template>
            </template>
          </div>
        </div>
        <div v-if="shownDrafts.length === 0" class="text-12px text-#8c8c8c">暂无可显示的查询条件</div>
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
.admin-advanced-search {
  width: 560px;
  max-width: calc(100vw - 100px);
}

.admin-advanced-search__body {
  max-height: 56vh;
  overflow-y: auto;
}

.admin-advanced-search__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.admin-advanced-search__remove {
  flex-shrink: 0;
  color: #909399;
}

.admin-advanced-search__remove:hover {
  color: #e03131;
}

.admin-advanced-search__label {
  width: 110px;
  flex-shrink: 0;
}

.admin-advanced-search__value {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.admin-advanced-search__to {
  color: #8c8c8c;
  font-size: 12px;
}

.admin-advanced-search__settings {
  max-height: 320px;
  min-width: 200px;
  overflow-y: auto;
}
</style>
