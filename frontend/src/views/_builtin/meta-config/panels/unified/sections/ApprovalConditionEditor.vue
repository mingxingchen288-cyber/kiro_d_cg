<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NInput, NModal, NSelect, NSpace } from 'naive-ui';
import type { ApprovalCatalog, ApprovalConditionType, ApprovalDataItem } from '@/service/api/approval-config';
import { conditionOptions } from './approval-config-columns';

const props = defineProps<{
  show: boolean;
  title: string;
  conditionType: ApprovalConditionType;
  condition: string;
  catalog: ApprovalCatalog;
  tableCode: string;
  dataItems: ApprovalDataItem[];
}>();
const emit = defineEmits<{
  'update:show': [show: boolean];
  save: [value: { conditionType: ApprovalConditionType; condition: string }];
}>();
const kind = ref<ApprovalConditionType>('ALWAYS');
const expression = ref('');
const kindOptions = conditionOptions.map(option => ({ label: option.label, value: String(option.value) }));
const source = ref('待审值');
const selectedTable = ref('');
const selectedField = ref<string | null>(null);
const sourceOptions = [
  { label: '本次待审值', value: '待审值' }, { label: '送审前原值', value: '原值' },
  { label: '发起人员', value: '用户' }, { label: '自定义 SQL 数据', value: '自定义' }
];
const isPageField = computed(() => source.value === '待审值' || source.value === '原值');
const isDetailField = computed(() => isPageField.value && selectedTable.value !== props.tableCode);
const tableOptions = computed(() => props.catalog.tables
  .filter(table => table.tableCode === props.tableCode || table.parentTableCode === props.tableCode)
  .map(table => ({ label: `${table.tableName || table.tableCode} · ${table.tableCode}`, value: table.tableCode })));
const tableColumns = computed(() => props.catalog.tables.find(table => table.tableCode === selectedTable.value)?.columns || []);
const hasVirtualFields = computed(() => isPageField.value && tableColumns.value.some(column => column.isVirtual));
const canInsertReference = computed(() => Boolean(selectedField.value) && !(source.value === '待审值'
  && tableColumns.value.some(column => column.columnName === selectedField.value && column.isVirtual)));
const fieldOptions = computed(() => {
  if (source.value === '自定义') return props.dataItems.map(item => ({ label: item.name, value: item.name }));
  if (source.value === '用户') return [{ label: '人员 ID', value: 'id' }, { label: '部门 ID', value: 'departmentId' }];
  return tableColumns.value.map(column => ({
    label: `${column.label || column.headerText || column.columnName} · ${column.columnName}${column.isVirtual ? '（计算字段）' : ''}`,
    value: column.columnName,
    disabled: source.value === '待审值' && Boolean(column.isVirtual)
  }));
});
watch(() => props.show, show => {
  if (show) { kind.value = props.conditionType; expression.value = props.condition; selectedField.value = null; selectedTable.value = props.tableCode; }
}, { immediate: true });
watch(source, () => { selectedField.value = null; });
watch(selectedTable, () => { selectedField.value = null; });
function insertReference() {
  if (!canInsertReference.value || !selectedField.value) return;
  let token = `{${source.value}.${selectedField.value}}`;
  if (isDetailField.value) {
    const root = source.value === '原值' ? 'old' : 'new';
    const table = selectedTable.value.replaceAll("'", "''");
    const field = selectedField.value.replaceAll("'", "''");
    token = `#details.?[#this['tableCode'] == '${table}'].![#this['${root}']['${field}']]`;
  }
  if (kind.value === 'SQL') {
    const prefix = ({ 待审值: 'new', 原值: 'old', 用户: 'user', 自定义: 'data' } as Record<string, string>)[source.value];
    token = isDetailField.value ? ':contextJson' : `:${prefix}_${selectedField.value}`;
  }
  expression.value += token;
}
function save() {
  emit('save', { conditionType: kind.value, condition: kind.value === 'ALWAYS' ? '' : expression.value });
  emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" :title="title" style="width: min(900px, 94vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSelect v-model:value="kind" :options="kindOptions" style="width: 220px" />
      <template v-if="kind !== 'ALWAYS'">
        <div class="reference-picker">
          <NSelect v-model:value="source" :options="sourceOptions" />
          <NSelect v-if="isPageField" v-model:value="selectedTable" :options="tableOptions" placeholder="选择主表或明细表" />
          <NSelect v-model:value="selectedField" filterable clearable :options="fieldOptions" placeholder="选择字段或数据项（名称 · 编码）" />
          <NButton :disabled="!canInsertReference" @click="insertReference">{{ isDetailField ? kind === 'SQL' ? '插入上下文参数' : '插入字段集合' : '插入引用' }}</NButton>
        </div>
        <NInput v-model:value="expression" type="textarea" :autosize="{ minRows: 7, maxRows: 16 }" :placeholder="kind === 'SQL' ? '只读 SELECT 或 SQL 条件；使用上方插入具名参数' : '选择字段插入引用后，使用 ==、!=、>、>=、&&、|| 组合条件'" />
        <NAlert type="info" :bordered="false">
          {{ kind === 'SQL' ? 'SQL 仅用于判断和取数。可用 :billId、:contextJson 及上方插入的参数；不会在此编辑器中执行 SQL。' : '字段引用保存稳定编码；待审值包含本次修改。条件不满足跳过入口，条件计算出错则阻断本次操作。' }}
        </NAlert>
        <NAlert v-if="hasVirtualFields" type="info" :bordered="false">计算字段可以引用送审前原值。本次待审计算值尚未在服务端生成，因此不可直接引用；如需按本次修改后的计算结果判断，请配置服务端自定义 SQL 数据项。</NAlert>
        <NAlert v-if="isDetailField" type="info" :bordered="false">明细字段是集合，不能当作主表单值比较。表达式需明确筛选哪些明细行；SQL 从 :contextJson 的 details 中读取选定表和字段。</NAlert>
      </template>
      <div class="actions"><NButton @click="emit('update:show', false)">取消</NButton><NButton type="primary" @click="save">应用到当前草稿</NButton></div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.reference-picker { display: flex; flex-wrap: wrap; gap: 8px; }
.reference-picker :deep(.n-select) { flex: 1; min-width: 150px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
