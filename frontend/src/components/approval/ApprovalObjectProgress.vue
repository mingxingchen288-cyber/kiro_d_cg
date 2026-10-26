<script setup lang="ts">
import { computed } from 'vue';
import { AgGridVue } from 'ag-grid-vue3';
import type { ColDef, GetRowIdParams } from 'ag-grid-community';
import type { ApprovalObjectDecision, ApprovalObjectProgressData, ApprovalRuntimeObject } from '@/service/api/approval-runtime';
import { buildApprovalObjectColumns } from './approval-object-columns';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';

interface TaskDetail {
  detailId?: number | string;
  operateRealName?: string;
  operateUsername?: string;
  targetUserName?: string;
  targetRoleName?: string;
}
const props = defineProps<{ progress?: ApprovalObjectProgressData | null; details?: TaskDetail[] }>();
const objects = computed(() => props.progress?.objects || []);
const counts = computed(() => ({
  approved: objects.value.filter(object => object.status === 'APPROVED').length,
  rejected: objects.value.filter(object => object.status === 'REJECTED').length,
  pending: objects.value.filter(object => object.status === 'PENDING').length
}));
const columns = computed<ColDef<ApprovalRuntimeObject>[]>(() => {
  const base = buildApprovalObjectColumns(objects.value);
  const levels = [...new Set(objects.value.flatMap(object => (object.decisions || []).map(decision => decision.level)))].sort((a, b) => a - b);
  const levelColumns: ColDef<ApprovalRuntimeObject>[] = levels.map(level => ({
    colId: `level:${level}`,
    headerName: `第 ${level} 级结果`,
    minWidth: 230,
    wrapText: true,
    autoHeight: true,
    cellStyle: { whiteSpace: 'pre-line' },
    valueGetter: params => (params.data?.decisions || []).filter(decision => decision.level === level).map(decisionText).join('\n') || '未参与本级'
  }));
  return [...base.slice(0, 3), ...levelColumns, ...base.slice(3)];
});

function decisionText(decision: ApprovalObjectDecision) {
  const detail = props.details?.find(item => String(item.detailId) === String(decision.detailId));
  const actor = detail?.operateRealName || detail?.operateUsername || detail?.targetUserName || detail?.targetRoleName || `任务 ${decision.detailId}`;
  const result = decision.selected ? '本级同意' : '本级不同意';
  const state = !decision.effective ? '（未作为本级结果）' : !decision.levelComplete ? '（本级待汇总）' : '';
  return `${actor}：${result}${state}`;
}
function rowId(params: GetRowIdParams<ApprovalRuntimeObject>) { return params.data.key; }
</script>

<template>
  <div v-if="objects.length" class="approval-object-progress">
    <div class="object-summary">审批对象结果：共 {{ objects.length }} 个，已通过 {{ counts.approved }} 个，已驳回 {{ counts.rejected }} 个，待审批 {{ counts.pending }} 个。各级选择仅表示本级意见。</div>
    <AgGridVue
      class="ag-theme-quartz object-progress-grid"
      theme="legacy"
      :row-data="objects"
      :column-defs="columns"
      :default-col-def="{ editable: false, sortable: true, resizable: true, filter: 'agTextColumnFilter' }"
      :get-row-id="rowId"
      :row-height="28"
      :header-height="28"
      :animate-rows="false"
      :locale-text="{ noRowsToShow: '暂无审批对象' }"
    />
  </div>
</template>

<style scoped>
.approval-object-progress { margin-top: 12px; }
.object-summary { margin-bottom: 8px; font-size: 13px; }
.object-progress-grid {
  height: 280px;
  width: 100%;
  --ag-font-size: 13px;
  --ag-font-family: inherit;
  --ag-wrapper-border-radius: 0;
}
</style>
