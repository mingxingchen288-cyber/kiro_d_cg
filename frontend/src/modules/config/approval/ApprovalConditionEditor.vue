<script setup lang="ts">
/**
 * 入口条件、关联条件、取值的编辑弹窗，同旧系统 ApprovalConditionEditor.vue：条件类型（只用于入口条件）、
 * "来源 / 表 / 字段"选择后点"插入参数"，把 C06 7.2 的参数（`:new_PRICE` 等）接到文本末尾；只写条件或表达式本身。
 */
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NInput, NModal, NSelect, NSpace } from 'naive-ui';
import type { PageTable } from '../core/catalog';
import type { FlowParam } from '../core/types';
import { conditionOptions } from '../components/grid-columns';
import { type ParamSource, fieldChoices, insertToken, needsTable, paramToken, sourceOptions } from './params';

const props = withDefaults(
  defineProps<{
    show: boolean;
    title: string;
    /** 入口条件有条件类型；关联条件、取值没有 */
    withType?: boolean;
    conditionType?: 'always' | 'sql';
    condition: string;
    tables: PageTable[];
    /** 取值：可以插入 `:row_`、`:params_` */
    forValue?: boolean;
    rowColumns?: string[];
    params?: FlowParam[];
    placeholder?: string;
  }>(),
  { withType: false, conditionType: 'sql', forValue: false, rowColumns: () => [], params: () => [], placeholder: '' }
);
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [value: { conditionType?: 'always' | 'sql'; condition: string }] }>();

const kind = ref<'always' | 'sql'>('sql');
const expression = ref('');
const source = ref<ParamSource>('new');
const table = ref<string | null>(null);
const field = ref<string | null>(null);
const sources = computed(() => sourceOptions(props.forValue));
const tableOptions = computed(() => props.tables.map(t => ({ label: `${t.title} · ${t.entity}`, value: t.entity })));
const fields = computed(() => fieldChoices(source.value, props.tables, table.value, props.rowColumns, props.params));

watch(
  () => props.show,
  show => {
    if (!show) return;
    kind.value = props.conditionType;
    expression.value = props.condition;
    source.value = 'new';
    table.value = props.tables.find(t => !t.isMaster)?.entity ?? props.tables[0]?.entity ?? null;
    field.value = null;
  },
  { immediate: true }
);
watch([source, table], () => (field.value = null));

function insert() {
  if (field.value) expression.value = insertToken(expression.value, paramToken(source.value, field.value));
}

function save() {
  emit('save', props.withType ? { conditionType: kind.value, condition: kind.value === 'always' ? '' : expression.value } : { condition: expression.value });
  emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" :title="title" style="width: min(900px, 94vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSelect v-if="withType" v-model:value="kind" :options="conditionOptions as any" style="width: 220px" />
      <template v-if="!withType || kind !== 'always'">
        <div class="reference-picker">
          <NSelect v-model:value="source" :options="sources" />
          <NSelect v-if="needsTable(source)" v-model:value="table" :options="tableOptions" placeholder="选择主表或明细表" />
          <NSelect v-model:value="field" filterable clearable :options="fields" placeholder="选择字段（名称 · 编码）" />
          <NButton :disabled="!field" @click="insert">插入参数</NButton>
        </div>
        <NInput v-model:value="expression" type="textarea" :autosize="{ minRows: 7, maxRows: 16 }" :placeholder="placeholder || '只写条件本身，例如 GOODSID = :new_GOODSID'" />
        <NAlert type="info" :bordered="false">
          <div><code>:new_字段</code> 本行修改后的值（计算字段是重算后的值）；<code>:old_字段</code> 本行修改前的值，保存时加锁读出；新增行的 old、删除行的 new 为空。</div>
          <div><code>:master_new_字段</code>、<code>:master_old_字段</code> 本行所属主表修改后、修改前的值；<code>:operation</code> 本行操作 added / modified / deleted；<code>:billId</code> 单据主键；<code>:user_id</code>、<code>:user_departmentId</code> 发起人员。</div>
          <div v-if="forValue"><code>:row_列名</code> 修改表这一行的当前值；<code>:params_名称</code> 审批流参数的值。</div>
          <div>只写条件或表达式本身，不写分号；需要别的表的数据就写子查询，SQL 里查到的数据库数据都是保存前的值。比较可能为空的值用 DECODE。</div>
        </NAlert>
      </template>
      <div class="actions">
        <NButton @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" @click="save">应用到当前草稿</NButton>
      </div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.reference-picker { display: flex; flex-wrap: wrap; gap: 8px; }
.reference-picker :deep(.n-select) { flex: 1; min-width: 150px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
