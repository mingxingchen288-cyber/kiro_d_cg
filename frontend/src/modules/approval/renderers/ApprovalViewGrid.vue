<script setup lang="ts">
/**
 * 修改内容和受影响单据的表格（FA-01、FA-06、FA-09），对照旧系统 `ApprovalPresentationGrid.vue`：
 * - 改了的格子橙色框显示"A → B"；明细（kind 为 detail）末尾加"变化"和"触发审批"两列，触发审批用标签显示审批流名称，
 *   没有触发时显示"随审批等待"；新增行"变化"为绿色，删除行灰字。
 * - 受影响单据（kind 为 affected）最前面是勾选框，表头有全选；同一主键的几行合并勾选框和相同的格子（旧系统用 rowSpan，
 *   这里用 AG Grid 35 的 cell span）。记录已不存在的行整行红底，第一列前标"记录已不存在"，没有勾选框。
 * - 列宽（FA-13，C09 v14）：配了宽度的列按配置，没配的 170 起随表格伸展，同旧系统第 188 行。
 * - 列虚拟化只在测试模式下关掉（grid-theme.ts 的 suppressColumnVirtualisation，用户 2026-10-30 同意），正式模式不变。
 */
import { computed, onBeforeUnmount, watch } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, ICellRendererParams, IHeaderComp, RowClassRules, SpanRowsParams } from 'ag-grid-community';
import {
  DEFAULT_COLUMN_WIDTH,
  type GridRowModel,
  type ViewRow,
  WAITING,
  columnWidth,
  gridRows,
  triggerLabel
} from '../view-model';
import { HEADER_HEIGHT, ROW_HEIGHT, presentationTheme, suppressColumnVirtualisation } from './grid-theme';

defineOptions({ name: 'ApprovalViewGrid' });

const props = withDefaults(
  defineProps<{
    kind: 'master' | 'detail' | 'affected';
    columns: string[];
    /** 各列的宽度（C09 v14 的 `widths`），没配的为 null */
    widths?: ReadonlyArray<number | null> | null;
    rows: ViewRow[];
    flowNames?: ReadonlyMap<string, string>;
    /** 受影响单据：当前勾选的主键 */
    checkedKeys?: readonly string[];
    /** 受影响单据：能改勾选的主键 */
    selectableKeys?: readonly string[];
    disabled?: boolean;
  }>(),
  { widths: null, flowNames: () => new Map(), checkedKeys: () => [], selectableKeys: () => [], disabled: false }
);

const emit = defineEmits<{ (e: 'toggle', key: string, checked: boolean): void; (e: 'toggleAll', checked: boolean): void }>();

type Row = GridRowModel & { checked: boolean; selectable: boolean };

const MAX_HEIGHT = 450;
const affected = computed(() => props.kind === 'affected');

const rowData = computed<Row[]>(() =>
  gridRows(props.rows).map(row => ({
    ...row,
    checked: row.key !== null && props.checkedKeys.includes(row.key),
    selectable: row.key !== null && !props.disabled && props.selectableKeys.includes(row.key)
  }))
);

// 行少时随内容撑开（包括折行的审批流标签），行多时固定高度并按行虚拟滚动（同旧系统，10 行为界）
const autoHeight = computed(() => rowData.value.length <= 10);

const enabledKeys = computed(() => (props.disabled ? [] : props.selectableKeys));
/** 表头全选的状态：有能改的行时按能改的行，否则（不能改勾选的块）按全部行显示 */
const headerKeys = computed(() => {
  if (props.selectableKeys.length) return props.selectableKeys;
  return [...new Set(rowData.value.map(row => row.key).filter((key): key is string => key !== null))];
});
const allSelected = computed(
  () => headerKeys.value.length > 0 && headerKeys.value.every(key => props.checkedKeys.includes(key))
);
const someSelected = computed(() => headerKeys.value.some(key => props.checkedKeys.includes(key)) && !allSelected.value);

// ---- 表头全选（JS 表头组件，状态变化时同步）
const headers = new Set<SelectionHeader>();

class SelectionHeader implements IHeaderComp {
  private input = document.createElement('input');

  init() {
    this.input.type = 'checkbox';
    this.input.setAttribute('aria-label', '全选可勾选的行');
    this.input.addEventListener('change', () => emit('toggleAll', this.input.checked));
    this.sync();
    headers.add(this);
  }

  getGui() {
    return this.input;
  }

  refresh() {
    this.sync();
    return true;
  }

  sync() {
    this.input.checked = allSelected.value;
    this.input.indeterminate = someSelected.value;
    this.input.disabled = enabledKeys.value.length === 0;
  }

  destroy() {
    headers.delete(this);
  }
}

watch([allSelected, someSelected, enabledKeys], () => {
  for (const header of headers) header.sync();
});

onBeforeUnmount(() => headers.clear());

function renderCheck(params: ICellRendererParams<Row>) {
  const row = params.data;
  if (!row || row.key === null) return '';
  const key = row.key;
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = row.checked;
  input.disabled = !row.selectable;
  input.setAttribute('aria-label', `勾选 ${key}`);
  input.addEventListener('change', () => emit('toggle', key, input.checked));
  return input;
}

function renderValue(index: number) {
  return (params: ICellRendererParams<Row>) => {
    const row = params.data;
    if (!row) return '';
    const container = document.createElement('span');
    container.className = 'approval-value';
    if (row.missing && index === 0) {
      const tag = document.createElement('span');
      tag.className = 'approval-missing-tag';
      tag.textContent = '记录已不存在';
      container.appendChild(tag);
    }
    const text = document.createElement('span');
    text.textContent = row.texts[index] ?? '';
    if (row.changed[index]) text.className = 'approval-changed-value';
    container.appendChild(text);
    return container;
  };
}

function renderFlows(params: ICellRendererParams<Row>) {
  const container = document.createElement('div');
  container.className = 'approval-flow-tags';
  const flows = params.data?.flows ?? [];
  if (!flows.length) {
    container.classList.add('approval-flow-fallback');
    container.textContent = WAITING;
    return container;
  }
  for (const flow of flows) {
    const tag = document.createElement('span');
    tag.className = 'approval-flow-tag';
    tag.textContent = props.flowNames.get(flow) ?? flow;
    container.appendChild(tag);
  }
  return container;
}

/** 同一主键的相邻行：勾选框总是合并，其他列文字相同才合并 */
function sameKey(params: SpanRowsParams<Row>) {
  const a = params.nodeA?.data;
  const b = params.nodeB?.data;
  return Boolean(a && b && a.key !== null && a.key === b.key);
}

const columnDefs = computed<ColDef<Row>[]>(() => [
  ...(affected.value
    ? [
        {
          colId: 'approval:selection',
          headerName: '',
          width: 42,
          minWidth: 42,
          maxWidth: 42,
          resizable: false,
          headerComponent: SelectionHeader,
          valueGetter: (p: { data?: Row }) => (p.data ? `${p.data.key}|${p.data.checked}|${p.data.selectable}` : ''),
          cellRenderer: renderCheck,
          spanRows: sameKey,
          cellClass: 'approval-span-cell approval-check-cell'
        } satisfies ColDef<Row>
      ]
    : []),
  ...props.columns.map(
    (label, index): ColDef<Row> => ({
      colId: `c${index}`,
      headerName: label,
      // 配了宽度的列按配置的宽度，没配的从 170 起随表格伸展（同旧系统 width: column.width || 170、flex 只给没配的列）
      width: columnWidth(props.widths, index) ?? DEFAULT_COLUMN_WIDTH,
      minWidth: 60,
      flex: columnWidth(props.widths, index) === null ? 1 : undefined,
      valueGetter: p => (p.data ? `${p.data.missing ? '!' : ''}${p.data.texts[index] ?? ''}|${p.data.changed[index]}` : ''),
      cellRenderer: renderValue(index),
      spanRows: affected.value ? (p: SpanRowsParams<Row>) => sameKey(p) && p.valueA === p.valueB : undefined,
      cellClass: 'approval-span-cell'
    })
  ),
  ...(props.kind === 'detail'
    ? [
        {
          colId: 'approval:operation',
          headerName: '变化',
          width: 90,
          valueGetter: (p: { data?: Row }) => p.data?.change ?? ''
        } satisfies ColDef<Row>,
        {
          colId: 'approval:flows',
          headerName: '触发审批',
          minWidth: 200,
          flex: 1,
          wrapText: true,
          autoHeight: true,
          cellStyle: { whiteSpace: 'normal', lineHeight: '20px', paddingTop: '4px', paddingBottom: '4px' },
          cellClass: 'approval-flow-label',
          valueGetter: (p: { data?: Row }) => (p.data ? triggerLabel(p.data.flows, props.flowNames) : ''),
          tooltipValueGetter: p => String(p.value ?? ''),
          cellRenderer: renderFlows
        } satisfies ColDef<Row>
      ]
    : [])
]);

const defaultColDef: ColDef = {
  editable: false,
  sortable: false,
  filter: false,
  resizable: true,
  suppressHeaderMenuButton: true,
  suppressHeaderFilterButton: true,
  suppressHeaderContextMenu: true
};

const rowClassRules: RowClassRules<Row> = {
  'approval-deleted-row': p => p.data?.op === 'delete',
  'approval-added-row': p => p.data?.op === 'add',
  'approval-missing-row': p => Boolean(p.data?.missing)
};
</script>

<template>
  <div class="approval-presentation-wrap">
    <AgGridVue
      class="approval-presentation-grid"
      :class="{ 'approval-empty-grid': !rowData.length }"
      :theme="presentationTheme"
      :dom-layout="autoHeight ? 'autoHeight' : 'normal'"
      :style="{ height: autoHeight ? 'auto' : `${MAX_HEIGHT}px` }"
      :row-data="rowData"
      :column-defs="columnDefs"
      :default-col-def="defaultColDef"
      :row-height="ROW_HEIGHT"
      :header-height="HEADER_HEIGHT"
      :get-row-id="p => p.data.id"
      :enable-cell-span="affected"
      :suppress-context-menu="true"
      :animate-rows="false"
      :row-class-rules="rowClassRules"
      :locale-text="{ noRowsToShow: '本区域没有展示数据' }"
      :suppress-column-virtualisation="suppressColumnVirtualisation"
    />
  </div>
</template>

<style scoped>
.approval-presentation-grid {
  width: 100%;
}
.approval-presentation-grid :deep(.ag-layout-auto-height .ag-center-cols-container),
.approval-presentation-grid :deep(.ag-layout-auto-height .ag-center-cols-viewport) {
  min-height: 0;
}
.approval-empty-grid :deep(.ag-layout-auto-height .ag-center-cols-container),
.approval-empty-grid :deep(.ag-layout-auto-height .ag-center-cols-viewport) {
  min-height: 32px;
}
.approval-presentation-grid :deep(.approval-span-cell) {
  background: #fff;
  display: flex;
  align-items: center;
}
.approval-presentation-grid :deep(.approval-check-cell) {
  justify-content: center;
}
.approval-presentation-grid :deep(.approval-value) {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
}
.approval-presentation-grid :deep(.approval-changed-value) {
  display: block;
  width: 100%;
  padding: 1px 7px;
  box-sizing: border-box;
  border: 1px solid #ffd18d;
  border-radius: 4px;
  background: #fff7e6;
  font-weight: 600;
  line-height: 25px;
}
.approval-presentation-grid :deep(.approval-flow-label) {
  color: #6761ff;
}
.approval-presentation-grid :deep(.approval-flow-tags) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  width: 100%;
  min-width: 0;
}
.approval-presentation-grid :deep(.approval-flow-tag) {
  max-width: 100%;
  padding: 0 6px;
  border: 1px solid #e3e1ff;
  border-radius: 4px;
  background: #f3f2ff;
  color: inherit;
  line-height: 20px;
  white-space: normal;
  overflow-wrap: anywhere;
}
.approval-presentation-grid :deep(.approval-flow-fallback) {
  color: #98a2b3;
}
.approval-presentation-grid :deep(.approval-deleted-row .ag-cell) {
  color: #98a2b3;
}
.approval-presentation-grid :deep(.approval-added-row .ag-cell[col-id='approval:operation']) {
  color: #16a078;
}
/* 记录已不存在（FA-09）：整行红底 */
.approval-presentation-grid :deep(.approval-missing-row .ag-cell) {
  background: #fdecec;
  color: #b42318;
}
.approval-presentation-grid :deep(.approval-missing-tag) {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid #f5b5b5;
  border-radius: 4px;
  background: #fff;
  color: #d03050;
  line-height: 20px;
  white-space: nowrap;
}
</style>
