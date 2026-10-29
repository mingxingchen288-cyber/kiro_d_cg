<script setup lang="ts">
/**
 * 显示列弹窗，同旧系统"审批展示 · 列映射"（ApprovalDisplayColumnsEditor.vue）：列为字段、显示名称、小数位、列宽、
 * 对应修改表的列（只用于受影响单据）；新增列、删除选中列、上移、下移，显示顺序按此表行顺序。
 * 字段从所选表格的字段或表 / 视图的列中选（经 `POST /api/config/schema/columns` 读出）；修改表在平台注册过时还可以选
 * `master.字段`。
 */
import { computed, ref, watch } from 'vue';
import { NAlert, NButton, NModal, NSpace } from 'naive-ui';
import type { ColDef } from 'ag-grid-community';
import type { Option } from '../core/catalog';
import type { DisplayColumn } from '../core/types';
import ConfigGrid from '../components/ConfigGrid.vue';
import { selectColumn } from '../components/grid-columns';

interface Row extends DisplayColumn {
  _id: string;
}

const props = defineProps<{
  show: boolean;
  title: string;
  columns: DisplayColumn[];
  fieldOptions: Option[];
  /** 修改表的列；为 null 时不是受影响单据，不显示"对应修改表的列" */
  targetOptions: Option[] | null;
}>();
const emit = defineEmits<{ 'update:show': [show: boolean]; save: [columns: DisplayColumn[]] }>();
const rows = ref<Row[]>([]);
const selected = ref<Row[]>([]);
const grid = ref<InstanceType<typeof ConfigGrid>>();
const warning = ref('');
let sequence = 0;

const columnDefs = computed<ColDef[]>(() => [
  { ...selectColumn('field', '字段', props.fieldOptions, 220), cellEditor: 'agRichSelectCellEditor', cellEditorParams: { values: props.fieldOptions.map(o => o.value), allowTyping: true, filterList: true, searchType: 'matchAny' } },
  { field: 'label', headerName: '显示名称', width: 160 },
  { field: 'precision', headerName: '小数位（留空取页面视图）', width: 185, cellDataType: 'number', cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 0, max: 16, precision: 0 } },
  { field: 'width', headerName: '列宽（可选）', width: 130, cellDataType: 'number', cellEditor: 'agNumberCellEditor', cellEditorParams: { min: 60, max: 1200, precision: 0 } },
  ...(props.targetOptions ? [{ ...selectColumn('targetColumn', '对应修改表的列（省略按同名）', [{ label: '（同名）', value: '' }, ...props.targetOptions], 220) }] : [])
]);

watch(
  () => props.show,
  show => {
    if (!show) return;
    rows.value = props.columns.map(c => ({ _id: `col-${++sequence}`, precision: null, width: null, targetColumn: '', ...c }));
    selected.value = [];
    warning.value = '';
  },
  { immediate: true }
);

function add() {
  rows.value = [...rows.value, { _id: `col-${++sequence}`, field: '', label: '', precision: null, width: null, targetColumn: '' }];
}

function remove() {
  rows.value = rows.value.filter(row => !selected.value.includes(row));
  selected.value = [];
}

function move(offset: number) {
  grid.value?.stopEditing();
  const index = rows.value.indexOf(selected.value[0]);
  if (selected.value.length !== 1 || index + offset < 0 || index + offset >= rows.value.length) return;
  const next = [...rows.value];
  [next[index], next[index + offset]] = [next[index + offset], next[index]];
  rows.value = next;
}

/** 选了字段而显示名称为空时，带出字段的名称 */
function changed(event: { colDef: ColDef; data: Row }) {
  if (event.colDef.field === 'field' && !event.data.label) {
    const option = props.fieldOptions.find(o => o.value === event.data.field);
    event.data.label = option ? option.label.split(' · ')[0] : event.data.field;
    grid.value?.refresh();
  }
}

function save() {
  grid.value?.stopEditing();
  const fields = rows.value.map(row => (row.field ?? '').trim());
  if (fields.some(f => !f) || new Set(fields).size !== fields.length) {
    warning.value = '字段不能为空或重复';
    return;
  }
  emit(
    'save',
    rows.value.map(({ _id, ...row }) => ({ ...row, field: row.field.trim(), label: (row.label ?? '').trim() || row.field.trim() }))
  );
  emit('update:show', false);
}
</script>

<template>
  <NModal :show="show" preset="card" :title="`审批展示 · 列映射 · ${title}`" style="width: min(1120px, 95vw)" @update:show="emit('update:show', $event)">
    <NSpace vertical :size="12">
      <NSpace size="small">
        <NButton size="small" @click="add">新增列</NButton>
        <NButton size="small" :disabled="!selected.length" @click="remove">删除选中列</NButton>
        <NButton size="small" :disabled="selected.length !== 1" @click="move(-1)">上移</NButton>
        <NButton size="small" :disabled="selected.length !== 1" @click="move(1)">下移</NButton>
      </NSpace>
      <ConfigGrid ref="grid" :rows="rows" :columns="columnDefs" :height="280" multiple row-key="_id" @select="selected = $event" @change="changed" />
      <NAlert v-if="warning" type="warning" :bordered="false">{{ warning }}</NAlert>
      <NAlert type="info" :bordered="false">
        字段从所选表格的字段（受影响单据为表或视图的列）里选；修改表在平台注册过时，还可以选它所属主表的字段（master.字段）。每一列自动显示"修改前 → 修改后"，修改后只对能对应上修改表的列显示。显示顺序按此表行顺序。
      </NAlert>
      <div class="actions">
        <NButton @click="emit('update:show', false)">取消</NButton>
        <NButton type="primary" @click="save">应用到当前草稿</NButton>
      </div>
    </NSpace>
  </NModal>
</template>

<style scoped>
.actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
