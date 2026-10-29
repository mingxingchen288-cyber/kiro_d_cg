<script setup lang="ts">
/**
 * 审批进度的从表（FA-06）：按 `steps` 每个节点一行，列为级别、审批节点、审批人、来自审批流、状态、处理时间和意见，
 * 对照旧系统 `ApprovalDetailDialog.vue` 的 progressColumns。审批节点后用标签标出或签、会签；会签时审批人逐个显示处理情况，
 * 状态后显示已通过几人。
 */
import { computed } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, ICellRendererParams } from 'ag-grid-community';
import { type ApprovalStep, type StepRow, stepRows } from '../view-model';
import { HEADER_HEIGHT, ROW_HEIGHT, gridLayout, simpleTheme } from './grid-theme';

defineOptions({ name: 'ApprovalStepsGrid' });

const props = defineProps<{ steps: ApprovalStep[] }>();

type Row = StepRow & { id: string; raw: ApprovalStep };

const rowData = computed<Row[]>(() =>
  stepRows(props.steps).map((row, index) => ({ ...row, id: `s${index}`, raw: props.steps[index] }))
);
const layout = computed(() => gridLayout(rowData.value.length, 300));

function renderNode(params: ICellRendererParams<Row>) {
  const row = params.data;
  const container = document.createElement('span');
  container.className = 'approval-node';
  if (!row) return container;
  container.append(row.node);
  const tag = document.createElement('span');
  tag.className = `approval-mode-tag approval-mode-${row.raw.mode}`;
  tag.textContent = row.mode;
  container.appendChild(tag);
  return container;
}

const wrap: ColDef<Row> = {
  wrapText: true,
  autoHeight: true,
  cellStyle: { whiteSpace: 'normal', lineHeight: '20px', paddingTop: '5px', paddingBottom: '5px' }
};

const columnDefs: ColDef<Row>[] = [
  { field: 'level', headerName: '级别', width: 70 },
  { colId: 'node', headerName: '审批节点', minWidth: 170, flex: 1, cellRenderer: renderNode, ...wrap },
  { field: 'approvers', headerName: '审批人', minWidth: 220, flex: 1.4, ...wrap },
  { field: 'flowName', headerName: '来自审批流', minWidth: 160, flex: 1, ...wrap },
  {
    field: 'status',
    headerName: '状态',
    width: 150,
    cellClassRules: {
      'approval-step-pending': p => p.data?.raw.status === 'pending',
      'approval-step-rejected': p => p.data?.raw.status === 'rejected',
      'approval-step-upcoming': p => p.data?.raw.status === 'upcoming'
    }
  },
  { field: 'time', headerName: '处理时间', width: 165, ...wrap },
  { field: 'comment', headerName: '意见 / 驳回原因', minWidth: 200, flex: 1, ...wrap }
];

const defaultColDef: ColDef = {
  editable: false,
  sortable: false,
  filter: false,
  resizable: true,
  suppressHeaderMenuButton: true,
  suppressHeaderFilterButton: true,
  suppressHeaderContextMenu: true
};
</script>

<template>
  <AgGridVue
    class="approval-simple-grid"
    :theme="simpleTheme"
    :dom-layout="layout.domLayout"
    :style="layout.style"
    :row-data="rowData"
    :column-defs="columnDefs"
    :default-col-def="defaultColDef"
    :get-row-id="p => p.data.id"
    :suppress-context-menu="true"
    :row-height="ROW_HEIGHT"
    :header-height="HEADER_HEIGHT"
    :locale-text="{ noRowsToShow: '暂无审批节点' }"
  />
</template>

<style scoped>
.approval-simple-grid {
  width: 100%;
}
.approval-simple-grid :deep(.ag-layout-auto-height .ag-center-cols-viewport),
.approval-simple-grid :deep(.ag-layout-auto-height .ag-center-cols-container) {
  min-height: 0;
}
.approval-simple-grid :deep(.approval-node) {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.approval-simple-grid :deep(.approval-mode-tag) {
  padding: 0 6px;
  border-radius: 3px;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
}
.approval-simple-grid :deep(.approval-mode-or) {
  background: #eef4ff;
  color: #3f6fd8;
}
.approval-simple-grid :deep(.approval-mode-and) {
  background: #f3f1ff;
  color: #6962ff;
}
.approval-simple-grid :deep(.approval-step-pending) {
  color: #d68a1a;
}
.approval-simple-grid :deep(.approval-step-rejected) {
  color: #d03050;
}
.approval-simple-grid :deep(.approval-step-upcoming) {
  color: #98a2b3;
}
</style>
