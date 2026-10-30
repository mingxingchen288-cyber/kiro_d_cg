<script setup lang="ts">
/**
 * 审批记录（FA-12，C09 v14 的 `history`）：每次提交、通过、驳回、撤回一行，列为动作、操作人、处理时间、意见、说明，
 * 列宽同旧系统 `ApprovalDetailDialog.vue` 第 200–208 行的 logColumns。
 */
import { computed } from "vue";
import { AgGridVue } from "ag-grid-vue3";
import type { ColDef } from "ag-grid-community";
import type { ApprovalDetail } from "../../../contracts/http";
import { type HistoryRow, historyRows } from "../view-model";
import {
  HEADER_HEIGHT,
  ROW_HEIGHT,
  gridLayout,
  simpleTheme,
} from "./grid-theme";

defineOptions({ name: "ApprovalHistoryGrid" });

const props = defineProps<{
  detail: Pick<ApprovalDetail, "history" | "status">;
}>();

type Row = HistoryRow & { id: string };

const rowData = computed<Row[]>(() =>
  historyRows(props.detail).map((row, index) => ({ ...row, id: `h${index}` })),
);
const layout = computed(() => gridLayout(rowData.value.length, 230));

const wrap: ColDef<Row> = {
  wrapText: true,
  autoHeight: true,
  cellStyle: {
    whiteSpace: "normal",
    lineHeight: "20px",
    paddingTop: "5px",
    paddingBottom: "5px",
  },
};

const columnDefs: ColDef<Row>[] = [
  { field: "action", headerName: "动作", width: 120 },
  { field: "by", headerName: "操作人", width: 130 },
  { field: "at", headerName: "处理时间", width: 180 },
  { field: "comment", headerName: "意见", minWidth: 180, flex: 1, ...wrap },
  { field: "note", headerName: "说明", minWidth: 200, flex: 1, ...wrap },
];

const defaultColDef: ColDef = {
  editable: false,
  sortable: false,
  filter: false,
  resizable: true,
  suppressHeaderMenuButton: true,
  suppressHeaderFilterButton: true,
  suppressHeaderContextMenu: true,
};
</script>

<template>
  <AgGridVue
    class="approval-history-grid"
    :theme="simpleTheme"
    :dom-layout="layout.domLayout"
    :style="layout.style"
    :row-data="rowData"
    :column-defs="columnDefs"
    :default-col-def="defaultColDef"
    :get-row-id="(p) => p.data.id"
    :suppress-context-menu="true"
    :row-height="ROW_HEIGHT"
    :header-height="HEADER_HEIGHT"
  />
</template>

<style scoped>
.approval-history-grid {
  width: 100%;
}
.approval-history-grid :deep(.ag-layout-auto-height .ag-center-cols-viewport),
.approval-history-grid :deep(.ag-layout-auto-height .ag-center-cols-container) {
  min-height: 0;
}
</style>
