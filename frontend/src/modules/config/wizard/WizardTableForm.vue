<script setup lang="ts">
/**
 * 向导第 2 步中的一张表（同旧系统 WizardStep2.vue 的主表 / 从表区）：视图名、目标表、表名称、实体编码、"导入列"，
 * 导入后的列表格（字段名、标题、数据类型、真实/虚拟、显示、编辑、ERP 列）；明细另有区域标题和关联字段。
 * 视图名、目标表输入两个字符起列出名称含它的表和视图（FC-14，同旧系统 SectionTables.vue 第 587–601 行的 NAutoComplete），
 * 也可以直接输入完整名称；导入后的标题预填列注释，没有注释时为列名。
 */
import { computed } from 'vue';
import { NAlert, NAutoComplete, NButton, NForm, NFormItem, NInput, NSelect, type SelectOption } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import ConfigGrid from '../components/ConfigGrid.vue';
import { booleanColumn } from '../components/grid-columns';
import type { ObjectOption, WizardState, WizardTable } from './wizard-state';

const props = defineProps<{ wizard: WizardState; table: WizardTable; detail: boolean }>();
const columns: ColDef[] = [
  { field: 'name', headerName: '字段名', width: 150, editable: false },
  { field: 'label', headerName: '标题', width: 150 },
  { field: 'type', headerName: '数据类型', width: 90, editable: false },
  { colId: 'inTable', headerName: '真实/虚拟', width: 90, editable: false, valueGetter: p => (p.data?.inTable ? '真实列' : '虚拟列（只读）') },
  booleanColumn('visible', '显示', 60),
  { ...booleanColumn('editable', '编辑', 60), editable: p => Boolean(p.data?.inTable) },
  booleanColumn('erp', 'ERP 列', 70)
];
const keyOptions = computed(() => props.table.columns.map(c => ({ label: `${c.label} · ${c.name}`, value: c.name })));
const rowStyle = (p: { data?: { inTable: boolean } }) => (p.data && !p.data.inTable ? { background: '#fffbe6' } : undefined);
const search = (value: string | null) => void props.wizard.searchObjects(value ?? '');
/** 下拉中显示"名称（表）""名称（视图）"；选中后输入框里只填名称 */
const renderLabel = (option: SelectOption) => `${option.label}（${(option as unknown as ObjectOption).kind}）`;
</script>

<template>
  <div>
    <NForm inline label-placement="left" size="small" :show-feedback="false">
      <NFormItem label="视图名">
        <NAutoComplete v-model:value="table.readView" :options="wizard.state.objectOptions" :render-label="renderLabel" :placeholder="detail ? '搜索从表视图...' : '搜索视图...'" style="width: 240px" @update:value="search" />
      </NFormItem>
      <NFormItem label="目标表">
        <NAutoComplete v-model:value="table.table" :options="wizard.state.objectOptions" :render-label="renderLabel" :placeholder="detail ? '搜索从表目标表...' : '搜索表...'" style="width: 240px" @update:value="search" />
      </NFormItem>
      <NFormItem label="表名称"><NInput v-model:value="table.name" placeholder="中文名" style="width: 150px" /></NFormItem>
      <NFormItem label="实体编码"><NInput v-model:value="table.entity" placeholder="导入后按目标表预填" style="width: 170px" /></NFormItem>
      <NFormItem v-if="detail" label="区域标题"><NInput v-model:value="table.title" placeholder="明细区标题，如 原辅料" style="width: 150px" /></NFormItem>
      <NFormItem><NButton size="small" type="primary" :disabled="!table.table.trim()" @click="wizard.importColumns(table)">导入列</NButton></NFormItem>
    </NForm>
    <NAlert v-if="table.importError" type="error" :bordered="false" class="mt-8">{{ table.importError }}</NAlert>
    <div v-if="table.columns.length" class="mt-8">
      <div class="hint">主键 {{ table.primaryKey }}；序列 {{ table.sequence?.name }}{{ table.sequence?.exists ? '（已存在）' : '（不存在）' }}。黄色行是视图中有、表中没有的列，只读显示。</div>
      <NFormItem v-if="detail" label="关联字段" :validation-status="!table.parentKey ? 'error' : undefined" :feedback="!table.parentKey ? '请选择关联字段' : ''" label-placement="left" size="small">
        <NSelect v-model:value="table.parentKey" :options="keyOptions" filterable placeholder="选择从表关联主表的字段" style="width: 260px" />
      </NFormItem>
      <ConfigGrid :rows="table.columns" :columns="columns" :height="Math.min(360, table.columns.length * 29 + 40)" row-key="name" :row-style="rowStyle" />
    </div>
  </div>
</template>

<style scoped>
.hint { color: #999; font-size: 12px; margin-bottom: 6px; }
</style>
