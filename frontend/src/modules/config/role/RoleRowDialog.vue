<script setup lang="ts">
/**
 * 配置行权限（FC-04），同旧系统（700px）：配置方式 可视化配置 / 自定义SQL；可视化为"满足 全部 / 任一 条件时可见"，
 * 每行 字段、运算符、固定值 / 动态值（当前用户、当前用户ID）、值，"添加条件"，下方显示生成的 SQL（只读）；
 * 自定义 SQL 写 WHERE 条件，支持占位符 ${userId}、${username}。平台把占位符换成绑定变量执行，不拼接字符串。
 */
import { computed, ref } from 'vue';
import { NButton, NInput, NModal, NRadio, NRadioGroup, NSelect } from 'naive-ui';
import type { EntityField, RolePage } from '../core/types';
import { DYNAMIC_VALUE_OPTIONS, ROW_OP_OPTIONS, generateRowSql, rowPolicyForm, rowPolicyValue } from './role-model';

const props = defineProps<{ pageTitle: string; fields: EntityField[]; value: RolePage['rows'] }>();
const emit = defineEmits<{ close: []; save: [rows: RolePage['rows']] }>();
const form = ref(rowPolicyForm(props.value));
const fieldOptions = computed(() => props.fields.map(f => ({ label: f.label, value: f.name })));
const generated = computed(() => generateRowSql(form.value.logic, form.value.conditions.filter(c => c.field)));

function add() {
  const first = props.fields[0];
  form.value.conditions.push({ field: first?.name ?? '', fieldLabel: first?.label ?? '', op: 'eq', valueType: 'static', value: '' });
}

function fieldChanged(index: number, name: string) {
  const cond = form.value.conditions[index];
  cond.field = name;
  cond.fieldLabel = props.fields.find(f => f.name === name)?.label ?? name;
}
</script>

<template>
  <NModal :show="true" preset="card" title="配置行权限" style="width: 700px" @update:show="emit('close')">
    <div class="row-modal-header"><span class="page-label">页面：{{ pageTitle }}</span></div>
    <div class="row-config-mode">
      <span class="mode-label">配置方式：</span>
      <NRadioGroup v-model:value="form.mode" size="small">
        <NRadio value="visual">可视化配置</NRadio>
        <NRadio value="sql">自定义SQL</NRadio>
      </NRadioGroup>
    </div>
    <template v-if="form.mode === 'visual'">
      <div class="condition-header">
        <span>满足</span>
        <NSelect v-model:value="form.logic" :options="[{ label: '全部', value: 'AND' }, { label: '任一', value: 'OR' }]" size="small" style="width: 80px" />
        <span>条件时可见：</span>
      </div>
      <div class="condition-list">
        <div v-for="(cond, index) in form.conditions" :key="index" class="condition-row">
          <NSelect :value="cond.field" :options="fieldOptions" size="small" style="width: 140px" placeholder="选择字段" filterable @update:value="v => fieldChanged(index, v)" />
          <NSelect v-model:value="cond.op" :options="ROW_OP_OPTIONS" size="small" style="width: 100px" />
          <template v-if="cond.op !== 'isNull' && cond.op !== 'isNotNull'">
            <NSelect v-model:value="cond.valueType" :options="[{ label: '固定值', value: 'static' }, { label: '动态值', value: 'dynamic' }]" size="small" style="width: 90px" />
            <NSelect v-if="cond.valueType === 'dynamic'" :value="String(cond.value ?? '')" :options="DYNAMIC_VALUE_OPTIONS" size="small" style="flex: 1" placeholder="选择动态值" @update:value="v => (cond.value = v)" />
            <NInput v-else :value="String(cond.value ?? '')" size="small" style="flex: 1" :placeholder="cond.op === 'in' ? '多个值用逗号分隔' : '输入值'" @update:value="v => (cond.value = v)" />
          </template>
          <NButton quaternary circle size="small" @click="form.conditions.splice(index, 1)">×</NButton>
        </div>
        <NButton dashed size="small" style="width: 100%" @click="add">+ 添加条件</NButton>
      </div>
      <div v-if="generated" class="generated-sql">
        <div class="sql-label">生成的SQL（只读）：</div>
        <div class="sql-content">{{ generated }}</div>
      </div>
    </template>
    <template v-else>
      <NInput v-model:value="form.sql" type="textarea" placeholder="SQL WHERE 条件，如：DEPT_ID = 1 或 CREATE_BY = ${username}" :rows="5" />
      <div class="row-policy-tip">
        <div>支持占位符：</div>
        <div class="tip-item"><code>${userId}</code> - 当前用户ID</div>
        <div class="tip-item"><code>${username}</code> - 当前用户名</div>
        <div class="tip-item warning">⚠️ 只能是一个条件表达式，不能含分号和数据修改语句；避免使用 1=2、1=0 等永假条件</div>
      </div>
    </template>
    <template #footer>
      <div class="modal-footer">
        <NButton size="small" @click="emit('close')">取消</NButton>
        <NButton type="primary" size="small" @click="emit('save', rowPolicyValue(form))">确定</NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.row-modal-header { margin-bottom: 8px; }
.page-label { color: #666; font-size: 13px; }
.row-config-mode { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.condition-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.condition-list { display: flex; flex-direction: column; gap: 8px; }
.condition-row { display: flex; align-items: center; gap: 8px; }
.generated-sql { margin-top: 12px; padding: 8px; background: #f5f7fa; border-radius: 4px; }
.sql-label { font-size: 12px; color: #666; }
.sql-content { font-family: monospace; font-size: 13px; word-break: break-all; }
.row-policy-tip { margin-top: 8px; font-size: 12px; color: #666; }
.tip-item.warning { color: #f0a020; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
