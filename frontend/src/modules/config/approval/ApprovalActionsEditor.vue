<script setup lang="ts">
/**
 * 审批通过后的操作弹窗，同旧系统"审批通过后写入的字段"：每行一个写入字段和取值（SQL 表达式片段，C06 7.2）。
 * C06 7.5 的四种操作按顺序执行：修改这一行（updateFields）、新增一行（insertRows，写目标表）、删除这一行（deleteRows）、
 * 逃生舱（escapeHatch，只在用户点名时启用）。
 */
import { ref, watch } from 'vue';
import { NButton, NCard, NInput, NModal, NSelect, NSpace } from 'naive-ui';
import type { Option } from '../core/catalog';
import type { BlockAction, FieldWrite } from '../core/types';

type Kind = BlockAction['action'];
interface Row {
  action: Kind;
  table: string;
  operation: string;
  fields: FieldWrite[];
  columns: Option[];
}

const props = defineProps<{
  show: boolean;
  title: string;
  actions: BlockAction[];
  /** 修改表的列 */
  targetOptions: Option[];
  /** 已登记的逃生舱操作 */
  escapeOptions: Option[];
  loadColumns: (table: string) => Promise<Option[]>;
}>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [actions: BlockAction[]] }>();
const rows = ref<Row[]>([]);

const kinds: Array<{ label: string; value: Kind }> = [
  { label: '修改这一行（写入字段）', value: 'updateFields' },
  { label: '新增一行到别的表', value: 'insertRows' },
  { label: '删除这一行', value: 'deleteRows' },
  { label: '逃生舱（存储过程）', value: 'escapeHatch' }
];

watch(
  () => props.show,
  async show => {
    if (!show) return;
    rows.value = props.actions.map(a => ({
      action: a.action,
      table: a.action === 'insertRows' ? a.table : '',
      operation: a.action === 'escapeHatch' ? a.operation : '',
      fields: a.action === 'updateFields' || a.action === 'insertRows' ? a.fields.map(f => ({ ...f })) : [],
      columns: a.action === 'updateFields' ? props.targetOptions : []
    }));
    if (!rows.value.length) rows.value.push({ action: 'updateFields', table: '', operation: '', fields: [], columns: props.targetOptions });
    for (const row of rows.value) if (row.action === 'insertRows' && row.table) row.columns = await props.loadColumns(row.table);
  },
  { immediate: true }
);

async function kindChanged(row: Row) {
  row.columns = row.action === 'updateFields' ? props.targetOptions : row.action === 'insertRows' && row.table ? await props.loadColumns(row.table) : [];
}

async function tableChanged(row: Row) {
  row.columns = row.table.trim() ? await props.loadColumns(row.table.trim()) : [];
}

function save() {
  const actions: BlockAction[] = rows.value.map(row => {
    const fields = row.fields.map(f => ({ column: (f.column ?? '').trim(), value: (f.value ?? '').trim() })).filter(f => f.column || f.value);
    if (row.action === 'updateFields') return { action: 'updateFields', fields };
    if (row.action === 'insertRows') return { action: 'insertRows', table: row.table.trim(), fields };
    if (row.action === 'deleteRows') return { action: 'deleteRows' };
    return { action: 'escapeHatch', operation: row.operation };
  });
  emit('save', actions);
  emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" :title="`审批通过后写入的字段 · ${title}`" style="width: min(880px, 96vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <div class="hint">
        全部级别通过后，对勾选的行按顺序执行。每行一个字段：把"取值"写进修改表的这一列。取值只写表达式本身，可用 :new_字段、:old_字段（找到这一行的那个触发行）、:row_列名（这一行当前值）、:params_名称、:billId，也可以写子查询。例如物料改价写成本明细单价：NVL(:new_ZX_PRICE, :old_PRICE)。修改表在平台注册过时，按所属页面的计算规则重算。
      </div>
      <NCard v-for="(row, index) in rows" :key="index" size="small" :bordered="true">
        <div class="action-head">
          <NSelect v-model:value="row.action" :options="kinds" style="width: 240px" @update:value="kindChanged(row)" />
          <NInput v-if="row.action === 'insertRows'" v-model:value="row.table" placeholder="新增到的表名，主键取序列 <表名>_SEQ" style="width: 300px" @blur="tableChanged(row)" />
          <NSelect v-if="row.action === 'escapeHatch'" v-model:value="row.operation" :options="escapeOptions" placeholder="已登记的逃生舱操作" style="width: 300px" />
          <NButton quaternary type="error" @click="rows.splice(index, 1)">删除操作</NButton>
        </div>
        <template v-if="row.action === 'updateFields' || row.action === 'insertRows'">
          <div v-for="(write, wi) in row.fields" :key="wi" class="write-row">
            <NSelect v-model:value="write.column" :options="row.columns" filterable tag placeholder="写入字段" :input-props="{ 'aria-label': `第 ${wi + 1} 个写入字段` }" />
            <NInput v-model:value="write.value" type="textarea" :autosize="{ minRows: 1, maxRows: 6 }" placeholder="取值，例如 :new_PRICE" :input-props="{ 'aria-label': `第 ${wi + 1} 个写入字段的取值` }" />
            <NButton quaternary type="error" @click="row.fields.splice(wi, 1)">删除</NButton>
          </div>
          <NButton size="small" @click="row.fields.push({ column: '', value: '' })">新增写入字段</NButton>
        </template>
      </NCard>
      <NButton size="small" dashed @click="rows.push({ action: 'updateFields', table: '', operation: '', fields: [], columns: targetOptions })">+ 添加操作</NButton>
      <div class="modal-actions">
        <NButton @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" @click="save">应用到当前草稿</NButton>
      </div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.hint { color: #687384; font-size: 12px; }
.action-head { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.write-row { display: grid; grid-template-columns: 220px 1fr auto; gap: 8px; align-items: start; margin-bottom: 8px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
