<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  NButton,
  NColorPicker,
  NEmpty,
  NIcon,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NTag,
  useMessage
} from 'naive-ui';
import { fetchColumnsByTableId, fetchTablesByPageCode, savePageRule } from '@/service/api/meta-config';

const props = defineProps<{
  show: boolean;
  rulesJson: string;
  pageCode: string;
  componentKey: string;
  ruleRow?: any;
}>();

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void;
  (e: 'save', json: string): void;
}>();

const message = useMessage();

type StyleRule = {
  field: string;
  operator: string;
  value?: any;
  scope?: 'row' | 'cell';
  targetFields?: string[];
  style?: {
    backgroundColor?: string;
    color?: string;
    fontWeight?: string;
    fontStyle?: string;
  };
};

const items = ref<StyleRule[]>([]);
const availableFields = ref<{ label: string; value: string }[]>([]);
const loadingFields = ref(false);
const saving = ref(false);

const operatorOptions = [
  { label: '等于', value: 'eq' },
  { label: '不等于', value: 'ne' },
  { label: '不为空', value: 'notNull' },
  { label: '在列表中', value: 'in' },
  { label: '不在列表中', value: 'notIn' }
];

const scopeOptions = [
  { label: '整行', value: 'row' },
  { label: '指定单元格', value: 'cell' }
];

// 需要输入值的操作符
const needsValue = (op: string) => op !== 'notNull';

watch(
  () => props.show,
  async val => {
    if (!val) return;
    try {
      items.value = props.rulesJson ? JSON.parse(props.rulesJson) : [];
      if (!Array.isArray(items.value)) items.value = [];
      // 确保每条规则有默认值
      items.value = items.value.map(normalizeRule);
    } catch {
      items.value = [];
    }
    await loadAvailableFields();
  },
  { immediate: true }
);

function normalizeRule(r: any): StyleRule {
  return {
    field: r.field || '',
    operator: r.operator || 'eq',
    value: r.value,
    scope: r.scope || 'row',
    targetFields: r.targetFields || [],
    style: {
      backgroundColor: r.style?.backgroundColor || undefined,
      color: r.style?.color || undefined,
      fontWeight: r.style?.fontWeight || undefined,
      fontStyle: r.style?.fontStyle || undefined
    }
  };
}

async function loadAvailableFields() {
  loadingFields.value = true;
  try {
    const tables = await fetchTablesByPageCode(props.pageCode);
    if (!tables.length) {
      availableFields.value = [];
      return;
    }
    const { fetchAllPageComponents } = await import('@/service/api/meta-config');
    const allComps = await fetchAllPageComponents();
    const currentComp = allComps?.find(
      (c: any) => c.pageCode === props.pageCode && c.componentKey === props.componentKey
    );
    const currentRefTableCode = currentComp?.refTableCode;
    const targetTable = currentRefTableCode ? tables.find((t: any) => t.tableCode === currentRefTableCode) : tables[0];
    if (!targetTable?.id) {
      availableFields.value = [];
      return;
    }
    const cols = await fetchColumnsByTableId(targetTable.id);
    availableFields.value = cols
      .filter((col: any) => col.columnName)
      .map((col: any) => ({
        label: `${col.columnName} (${col.headerText || col.columnName})`,
        value: col.columnName
      }));
  } catch {
    availableFields.value = [];
  } finally {
    loadingFields.value = false;
  }
}

function addRule() {
  items.value.push({
    field: '',
    operator: 'eq',
    value: undefined,
    scope: 'row',
    targetFields: [],
    style: {}
  });
}

function removeRule(index: number) {
  items.value.splice(index, 1);
}

function buildJson(): string {
  const cleaned = items.value.map(item => {
    const r: any = {
      field: item.field,
      operator: item.operator
    };
    if (needsValue(item.operator) && item.value !== undefined && item.value !== '') {
      r.value = item.value;
    }
    if (item.scope === 'cell') {
      r.scope = 'cell';
      if (item.targetFields?.length) r.targetFields = item.targetFields;
    }
    // 清理空样式
    const style: any = {};
    if (item.style?.backgroundColor) style.backgroundColor = item.style.backgroundColor;
    if (item.style?.color) style.color = item.style.color;
    if (item.style?.fontWeight) style.fontWeight = item.style.fontWeight;
    if (item.style?.fontStyle) style.fontStyle = item.style.fontStyle;
    if (Object.keys(style).length > 0) r.style = style;
    return r;
  });
  return JSON.stringify(cleaned);
}

async function handleSave() {
  // 校验
  for (const item of items.value) {
    if (!item.field) {
      message.warning('请选择条件字段');
      return;
    }
    if (!item.operator) {
      message.warning('请选择操作符');
      return;
    }
    if (item.scope === 'cell' && (!item.targetFields || item.targetFields.length === 0)) {
      message.warning('单元格模式需要选择目标字段');
      return;
    }
  }
  const json = buildJson();
  if (props.ruleRow) {
    saving.value = true;
    try {
      await savePageRule({ ...props.ruleRow, rules: json });
      message.success('样式规则已保存');
      emit('save', json);
      emit('update:show', false);
    } catch {
      message.error('保存失败');
    } finally {
      saving.value = false;
    }
  } else {
    emit('save', json);
    emit('update:show', false);
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    :title="`Grid 样式规则 - ${componentKey}`"
    style="width: 720px; max-height: 80vh"
    :mask-closable="true"
    :segmented="{ content: true, footer: true }"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div style="max-height: 60vh; overflow-y: auto">
      <div v-if="items.length === 0" style="padding: 20px 0; text-align: center">
        <NEmpty description="暂无样式规则" />
      </div>

      <div v-for="(item, idx) in items" :key="idx" class="rule-card">
        <div class="rule-header">
          <NTag size="small" :type="item.scope === 'cell' ? 'info' : 'success'">
            {{ item.scope === 'cell' ? '单元格' : '整行' }}
          </NTag>
          <span class="rule-index">#{{ idx + 1 }}</span>
          <NPopconfirm @positive-click="removeRule(idx)">
            <template #trigger>
              <NButton size="tiny" quaternary type="error">删除</NButton>
            </template>
            确定删除此规则？
          </NPopconfirm>
        </div>

        <!-- 条件行 -->
        <div class="rule-row">
          <div class="rule-field">
            <span class="field-label">条件字段</span>
            <NSelect
              v-model:value="item.field"
              :options="availableFields"
              size="small"
              filterable
              placeholder="选择字段"
              style="width: 180px"
            />
          </div>
          <div class="rule-field">
            <span class="field-label">操作符</span>
            <NSelect v-model:value="item.operator" :options="operatorOptions" size="small" style="width: 110px" />
          </div>
          <div v-if="needsValue(item.operator)" class="rule-field">
            <span class="field-label">值</span>
            <NInput v-model:value="item.value" size="small" placeholder="条件值" style="width: 140px" />
          </div>
        </div>

        <!-- 作用范围 -->
        <div class="rule-row">
          <div class="rule-field">
            <span class="field-label">作用范围</span>
            <NSelect v-model:value="item.scope" :options="scopeOptions" size="small" style="width: 130px" />
          </div>
          <div v-if="item.scope === 'cell'" class="rule-field" style="flex: 1">
            <span class="field-label">目标字段</span>
            <NSelect
              v-model:value="item.targetFields"
              :options="availableFields"
              size="small"
              filterable
              multiple
              placeholder="选择目标列"
              style="min-width: 200px"
            />
          </div>
        </div>

        <!-- 样式配置 -->
        <div class="rule-row">
          <div class="rule-field">
            <span class="field-label">背景色</span>
            <NColorPicker
              v-model:value="item.style!.backgroundColor"
              size="small"
              :show-alpha="false"
              :swatches="['#e6ffed', '#fff2a8', '#f8d7da', '#ffcccc', '#d4edda', '#cce5ff', '#e2e3e5']"
              style="width: 120px"
              :actions="['clear']"
            />
          </div>
          <div class="rule-field">
            <span class="field-label">字体颜色</span>
            <NColorPicker
              v-model:value="item.style!.color"
              size="small"
              :show-alpha="false"
              :swatches="['#e53935', '#1890ff', '#43a047', '#ff9800', '#333333', '#ffffff']"
              style="width: 120px"
              :actions="['clear']"
            />
          </div>
          <div class="rule-field">
            <span class="field-label">加粗</span>
            <NSelect
              v-model:value="item.style!.fontWeight"
              size="small"
              clearable
              placeholder="默认"
              :options="[
                { label: '加粗', value: 'bold' },
                { label: '正常', value: 'normal' }
              ]"
              style="width: 90px"
            />
          </div>
          <div class="rule-field">
            <span class="field-label">斜体</span>
            <NSelect
              v-model:value="item.style!.fontStyle"
              size="small"
              clearable
              placeholder="默认"
              :options="[
                { label: '斜体', value: 'italic' },
                { label: '正常', value: 'normal' }
              ]"
              style="width: 90px"
            />
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <NSpace justify="space-between" size="small">
        <NButton size="small" @click="addRule">+ 添加规则</NButton>
        <NSpace size="small">
          <NButton size="small" @click="emit('update:show', false)">取消</NButton>
          <NButton size="small" type="primary" :loading="saving" @click="handleSave">保存</NButton>
        </NSpace>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.rule-card {
  border: 1px solid #e8e8e8;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fafafa;
}
.rule-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.rule-index {
  font-size: 12px;
  color: #999;
  flex: 1;
}
.rule-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.rule-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.field-label {
  font-size: 12px;
  color: #666;
}
</style>
