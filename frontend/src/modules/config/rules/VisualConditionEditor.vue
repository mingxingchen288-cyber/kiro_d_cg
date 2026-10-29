<script setup lang="ts">
/**
 * 可视化条件（C06 第 5 节）：AND (全部满足) / OR (任一满足)，每行 来源（当前行字段 / 主表字段）、字段、运算符、值，
 * "+ 添加条件"。写法同旧系统 CellEditableDialog.vue 的条件区。
 */
import { NButton, NInput, NSelect } from 'naive-ui';
import type { VisualCondition } from '../core/types';
import { LOGIC_OPTIONS, OP_OPTIONS, SOURCE_OPTIONS, newConditionItem } from './rule-model';

const props = defineProps<{
  value: VisualCondition;
  rowFields: Array<{ label: string; value: string }>;
  masterFields: Array<{ label: string; value: string }>;
}>();
const emit = defineEmits<{ change: [] }>();
const fieldsOf = (source: 'row' | 'master') => (source === 'master' ? props.masterFields : props.rowFields);
const noValue = (op: string) => op === 'isNull' || op === 'isNotNull';
</script>

<template>
  <div>
    <div class="condition-head">
      <span class="field-label">满足条件</span>
      <NSelect v-model:value="props.value.logic" :options="LOGIC_OPTIONS" size="small" style="width: 160px" @update:value="emit('change')" />
    </div>
    <div v-for="(cond, i) in props.value.conditions" :key="i" class="condition-row">
      <NSelect v-model:value="cond.source" :options="SOURCE_OPTIONS" size="small" style="width: 130px" @update:value="emit('change')" />
      <NSelect v-model:value="cond.field" :options="fieldsOf(cond.source)" filterable placeholder="字段" size="small" style="width: 170px" @update:value="emit('change')" />
      <NSelect v-model:value="cond.op" :options="OP_OPTIONS" size="small" style="width: 110px" @update:value="emit('change')" />
      <NInput v-if="!noValue(cond.op)" :value="cond.value == null ? '' : String(cond.value)" size="small" :placeholder="cond.op === 'in' ? '多个值用逗号分隔' : '值'" style="width: 130px" @update:value="v => ((cond.value = v), emit('change'))" />
      <NButton size="tiny" quaternary type="error" @click="props.value.conditions.splice(i, 1), emit('change')">删除</NButton>
    </div>
    <NButton size="tiny" dashed style="margin: 4px 0 8px" @click="props.value.conditions.push(newConditionItem()), emit('change')">+ 添加条件</NButton>
  </div>
</template>

<style scoped>
.condition-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.condition-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.field-label { font-size: 12px; color: #666; }
</style>
