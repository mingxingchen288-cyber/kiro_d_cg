<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  NButton,
  NEmpty,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage
} from 'naive-ui';
import {
  fetchApprovalReferenceData,
  fetchColumnsByTableId,
  fetchTablesByPageCode,
  savePageRule
} from '@/service/api/meta-config';

const props = defineProps<{
  show: boolean;
  rulesJson: string;
  pageCode: string;
  componentKey: string;
  ruleRow?: any;
  ruleType?: 'EDITABLE' | 'APPROVAL_REQUIRED';
}>();

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void;
  (e: 'save', json: string): void;
}>();

const message = useMessage();
const currentRuleType = computed(() => props.ruleType || props.ruleRow?.ruleType || 'EDITABLE');
const approvalRequired = computed(() => currentRuleType.value === 'APPROVAL_REQUIRED');
const ruleTitle = computed(() => (approvalRequired.value ? '需审批的编辑字段' : '可编辑规则'));

type Condition = {
  source: 'row' | 'currentUser' | 'currentDepartment';
  field: string;
  operator: string;
  value?: any;
};

type EditableRule = {
  scope: 'row' | 'cell';
  logic: 'AND' | 'OR';
  conditions: Condition[];
  sqlCheck?: string;
  enableSql: boolean;
  editableFields?: string[];
};

const items = ref<EditableRule[]>([]);
const availableFields = ref<{ label: string; value: string }[]>([]);
const userOptions = ref<{ label: string; value: number }[]>([]);
const departmentOptions = ref<{ label: string; value: number }[]>([]);
const saving = ref(false);

const rowOperatorOptions = [
  { label: '= 等于', value: 'eq' },
  { label: '≠ 不等于', value: 'ne' },
  { label: '非空', value: 'notNull' },
  { label: '为空', value: 'isNull' },
  { label: '包含', value: 'in' },
  { label: '不包含', value: 'notIn' }
];

const identityOperatorOptions = [
  { label: '= 等于', value: 'eq' },
  { label: '≠ 不等于', value: 'ne' }
];

const sourceOptions = [
  { label: '当前行字段', value: 'row' },
  { label: '当前人员', value: 'currentUser' },
  { label: '当前部门', value: 'currentDepartment' }
];

const scopeOptions = [
  { label: '整行可编辑', value: 'row' },
  { label: '指定字段可编辑', value: 'cell' }
];
const availableSourceOptions = computed(() => (approvalRequired.value ? sourceOptions.slice(0, 1) : sourceOptions));
const availableScopeOptions = computed(() => (approvalRequired.value ? scopeOptions.slice(1) : scopeOptions));

const needsValue = (op: string) => !['notNull', 'isNull'].includes(op);

watch(
  () => props.show,
  async val => {
    if (!val) return;
    try {
      const raw = props.rulesJson ? JSON.parse(props.rulesJson) : [];
      const arr = Array.isArray(raw) ? raw : [raw];
      items.value = arr.map(normalizeRule);
    } catch {
      items.value = [];
    }
    await Promise.all([loadAvailableFields(), approvalRequired.value ? Promise.resolve() : loadIdentityOptions()]);
  },
  { immediate: true }
);

/** 兼容旧格式（单条件）和新格式（多条件） */
function normalizeRule(r: any): EditableRule {
  const scope = !approvalRequired.value && r.scope === 'row' ? 'row' : 'cell';
  const hasConditions = Array.isArray(r.conditions) && r.conditions.length > 0;
  let conditions: Condition[] = [];
  if (hasConditions) {
    conditions = r.conditions.map((c: any) => ({
      source:
        c.source === 'currentUser' || c.source === 'currentDepartment'
          ? c.source
          : 'row',
      field: c.field || '',
      operator: c.operator || 'eq',
      value: c.value
    }));
  } else if (r.condition) {
    conditions = [
      {
        source: 'row',
        field: r.condition.field || '',
        operator: r.condition.operator || 'eq',
        value: r.condition.value
      }
    ];
  }

  return {
    scope,
    logic: r.logic === 'OR' ? 'OR' : 'AND',
    conditions,
    sqlCheck: approvalRequired.value ? '' : r.sqlCheck || '',
    enableSql: !approvalRequired.value && Boolean(r.sqlCheck),
    editableFields: scope === 'cell' && Array.isArray(r.editableFields) ? r.editableFields : []
  };
}

async function loadAvailableFields() {
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
    const targetTable = currentComp?.refTableCode
      ? tables.find((t: any) => t.tableCode === currentComp.refTableCode)
      : tables[0];
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
  }
}

async function loadIdentityOptions() {
  try {
    const referenceData = await fetchApprovalReferenceData();
    userOptions.value = (referenceData.users || []).map((user: any) => ({
      label: `${user.realName || user.username} (${user.id})`,
      value: Number(user.id)
    }));
    departmentOptions.value = (referenceData.departments || []).map((department: any) => ({
      label: `${department.deptName || department.deptCode} (${department.id})`,
      value: Number(department.id)
    }));
  } catch {
    userOptions.value = [];
    departmentOptions.value = [];
  }
}

function handleSourceChange(condition: Condition) {
  condition.value = undefined;
  condition.operator = 'eq';
  if (condition.source === 'currentUser') {
    condition.field = 'userId';
  } else if (condition.source === 'currentDepartment') {
    condition.field = 'departmentId';
  } else {
    condition.field = '';
  }
}

function conditionOperatorOptions(condition: Condition) {
  if (approvalRequired.value) return rowOperatorOptions.filter(option => !['in', 'notIn'].includes(option.value));
  return condition.source === 'row' ? rowOperatorOptions : identityOperatorOptions;
}

function conditionValueOptions(condition: Condition) {
  return condition.source === 'currentUser' ? userOptions.value : departmentOptions.value;
}

function addRule() {
  items.value.push({
    scope: 'cell',
    logic: 'AND',
    conditions: [{ source: 'row', field: '', operator: 'eq', value: undefined }],
    sqlCheck: '',
    enableSql: false,
    editableFields: []
  });
}

function removeRule(idx: number) {
  items.value.splice(idx, 1);
}

function addCondition(rule: EditableRule) {
  rule.conditions.push({ source: 'row', field: '', operator: 'eq', value: undefined });
}

function removeCondition(rule: EditableRule, idx: number) {
  rule.conditions.splice(idx, 1);
}

function buildJson(): string {
  return JSON.stringify(
    items.value.map(rule => {
      const r: any = {
        scope: approvalRequired.value ? 'cell' : rule.scope,
        logic: rule.logic,
        conditions: rule.conditions.map(c => {
          const cond: any = { source: c.source, field: c.field, operator: c.operator };
          if (needsValue(c.operator) && c.value !== undefined && c.value !== '') cond.value = c.value;
          return cond;
        })
      };
      if (!approvalRequired.value && rule.enableSql && rule.sqlCheck?.trim()) {
        r.sqlCheck = rule.sqlCheck.trim();
      }
      if (rule.scope === 'cell') {
        r.editableFields = rule.editableFields || [];
      }
      return r;
    })
  );
}

async function handleSave() {
  if (approvalRequired.value && items.value.length === 0) {
    message.warning('请至少配置一条需审批的编辑字段规则');
    return;
  }
  for (const rule of items.value) {
    const invalidApprovalConditions = rule.conditions.length === 0 || rule.conditions.some(condition =>
      condition.source !== 'row' || !['eq', 'ne', 'notNull', 'isNull'].includes(condition.operator)
    );
    if (approvalRequired.value && invalidApprovalConditions) {
      message.warning('需审批的编辑字段仅支持当前行字段的等于、不等于、为空或非空条件');
      return;
    }
    if (rule.conditions.length === 0 && !rule.enableSql) {
      message.warning('每条规则至少需要一个条件或启用SQL判断');
      return;
    }
    for (const c of rule.conditions) {
      if (!c.field) {
        message.warning('请选择条件字段');
        return;
      }
      if (needsValue(c.operator) && (c.value === undefined || c.value === '')) {
        message.warning(c.source === 'row' ? '请输入条件值' : '请选择条件值');
        return;
      }
    }
    if (rule.scope === 'cell' && !rule.editableFields?.length) {
      message.warning('请选择可编辑字段');
      return;
    }
  }
  const json = buildJson();
  if (props.ruleRow) {
    saving.value = true;
    try {
      await savePageRule({ ...props.ruleRow, ruleType: currentRuleType.value, rules: json });
      message.success(`${ruleTitle.value}已保存`);
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
    :title="`${ruleTitle} - ${componentKey}`"
    style="width: 760px; max-height: 85vh"
    :mask-closable="true"
    :segmented="{ content: true, footer: true }"
    @update:show="(v: boolean) => emit('update:show', v)"
  >
    <div style="max-height: 65vh; overflow-y: auto">
      <div v-if="approvalRequired" class="hint" style="margin-bottom: 8px">
        命中条件的指定字段允许编辑，保存必须进入已启用的审批流程；审批通过后生效。其他字段沿用原编辑规则。
      </div>
      <div v-if="items.length === 0" style="padding: 20px 0; text-align: center">
        <NEmpty description="暂无规则，点击下方添加" />
      </div>

      <div v-for="(rule, rIdx) in items" :key="rIdx" class="rule-card">
        <div class="rule-header">
          <NTag size="small" type="info">#{{ rIdx + 1 }}</NTag>
          <span style="flex: 1"></span>
          <NPopconfirm @positive-click="removeRule(rIdx)">
            <template #trigger>
              <NButton size="tiny" quaternary type="error">删除</NButton>
            </template>
            确定删除此规则？
          </NPopconfirm>
        </div>

        <!-- 条件组合 -->
        <div class="section-label">
          作用范围
        </div>
        <NSelect
          v-model:value="rule.scope"
          :options="availableScopeOptions"
          :disabled="approvalRequired"
          size="small"
          style="width: 220px; margin-bottom: 8px"
        />

        <div class="section-label">
          条件组合
          <NSelect
            v-model:value="rule.logic"
            size="tiny"
            :options="[
              { label: 'AND (全部满足)', value: 'AND' },
              { label: 'OR (任一满足)', value: 'OR' }
            ]"
            style="width: 160px; display: inline-flex; margin-left: 8px"
          />
        </div>

        <!-- 条件列表 -->
        <div v-for="(cond, cIdx) in rule.conditions" :key="cIdx" class="condition-row">
          <NSelect
            v-model:value="cond.source"
            :options="availableSourceOptions"
            :disabled="approvalRequired"
            size="small"
            style="width: 130px"
            @update:value="handleSourceChange(cond)"
          />
          <NSelect
            v-if="cond.source === 'row'"
            v-model:value="cond.field"
            :options="availableFields"
            size="small"
            filterable
            placeholder="字段"
            style="width: 170px"
          />
          <NSelect
            v-model:value="cond.operator"
            :options="conditionOperatorOptions(cond)"
            size="small"
            style="width: 110px"
          />
          <NInput
            v-if="cond.source === 'row' && needsValue(cond.operator)"
            v-model:value="cond.value"
            size="small"
            placeholder="值"
            style="width: 130px"
          />
          <NSelect
            v-else-if="needsValue(cond.operator)"
            v-model:value="cond.value"
            :options="conditionValueOptions(cond)"
            size="small"
            filterable
            placeholder="请选择"
            style="width: 170px"
          />
          <NButton
            size="tiny"
            quaternary
            type="error"
            :disabled="rule.conditions.length <= 1 && !rule.enableSql"
            @click="removeCondition(rule, cIdx)"
          >
            ✕
          </NButton>
        </div>
        <NButton size="tiny" dashed style="margin: 4px 0 8px" @click="addCondition(rule)">+ 添加条件</NButton>

        <!-- SQL 判断 -->
        <div v-if="!approvalRequired" class="section-label" style="margin-top: 6px">
          <NSwitch v-model:value="rule.enableSql" size="small" />
          <span style="margin-left: 6px">启用 SQL 判断</span>
        </div>
        <div v-if="!approvalRequired && rule.enableSql" style="margin-bottom: 8px">
          <NInput
            v-model:value="rule.sqlCheck"
            type="textarea"
            size="small"
            placeholder="SELECT CASE WHEN ... THEN 1 ELSE 0 END FROM ... WHERE id = :id"
            :autosize="{ minRows: 2, maxRows: 4 }"
          />
          <div class="hint">返回 1 = 可编辑，0 = 不可编辑。:id 自动替换为当前行主键</div>
        </div>

        <!-- 可编辑字段 -->
        <template v-if="rule.scope === 'cell'">
          <div class="section-label">可编辑字段</div>
          <NSelect
            v-model:value="rule.editableFields"
            :options="availableFields"
            size="small"
            filterable
            multiple
            placeholder="选择允许编辑的字段"
            style="width: 100%"
          />
        </template>
      </div>
    </div>

    <template #footer>
      <NSpace justify="space-between" size="small">
        <NButton size="small" @click="addRule">+ 新增规则</NButton>
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
.section-label {
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
}
.condition-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.hint {
  font-size: 11px;
  color: #999;
  margin-top: 2px;
}
</style>
