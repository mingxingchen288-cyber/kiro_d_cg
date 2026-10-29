<script setup lang="ts">
/** "审核操作"弹窗（FC-05）：同旧系统"哪些保存操作触发送审"，改为本页面的每张表格各勾一组新增、修改、删除 */
import { ref, watch } from 'vue';
import { NButton, NCheckbox, NCheckboxGroup, NModal, NSpace } from 'naive-ui';
import type { PageTable } from '../core/catalog';
import type { RowOp } from '../core/types';
import { ROW_OPS, ROW_OP_LABELS } from './flow-model';

const props = defineProps<{ show: boolean; flowName: string; tables: PageTable[]; operations: Record<string, RowOp[]> }>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [operations: Record<string, RowOp[]>] }>();
const value = ref<Record<string, RowOp[]>>({});

watch(
  () => props.show,
  show => {
    if (show) value.value = Object.fromEntries(props.tables.map(t => [t.entity, [...(props.operations[t.entity] ?? [])]]));
  },
  { immediate: true }
);

function save() {
  emit('save', value.value);
  emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" :title="`哪些保存操作触发送审 · ${flowName}`" style="width: min(560px, 94vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="16">
      <div v-for="table in tables" :key="table.entity" class="op-row">
        <span class="op-table">{{ table.title }}<span class="hint"> · {{ table.entity }}</span></span>
        <NCheckboxGroup v-model:value="value[table.entity]">
          <NSpace>
            <NCheckbox v-for="op in ROW_OPS" :key="op" :value="op" :label="ROW_OP_LABELS[op]" />
          </NSpace>
        </NCheckboxGroup>
      </div>
      <div class="hint">列出本页面的表格。勾选的操作才送审：保存时，这些表格里本次新增、修改、删除的行，交给第 1 级各节点的入口条件逐行判断。</div>
      <div class="modal-actions">
        <NButton @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" @click="save">应用到当前草稿</NButton>
      </div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.op-row { display: flex; align-items: center; gap: 16px; }
.op-table { width: 180px; font-weight: 500; }
.hint { color: #687384; font-size: 12px; font-weight: normal; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
