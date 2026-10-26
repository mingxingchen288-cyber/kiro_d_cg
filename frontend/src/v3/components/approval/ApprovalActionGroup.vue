<script setup lang="ts">
import { computed, h, ref, unref } from 'vue';
import {
  NButton,
  NDataTable,
  NDropdown,
  NInput,
  NModal,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  useMessage
} from 'naive-ui';
import type { DataTableColumns } from 'naive-ui';
import {
  applyApproval,
  cancelApproval,
  fetchApprovalProgress,
  type ApprovalRuntimePayload
} from '@/service/api/approval-runtime';
import ApprovalDecisionDialog from '@/components/approval/ApprovalDecisionDialog.vue';
import ApprovalObjectProgress from '@/components/approval/ApprovalObjectProgress.vue';

const props = defineProps<{
  runtime: any;
  getSelectedRow: () => any | null;
}>();

type ApprovalDetailRow = {
  detailId?: number | string;
  roundNo?: number | string;
  nodeId?: number | string;
  approvalLevel?: number | string;
  nodeName?: string;
  approvalMode?: string;
  targetType?: string;
  targetUserId?: number | string;
  targetUserName?: string;
  targetRoleId?: number | string;
  targetRoleName?: string;
  status?: string;
  operateUserId?: number | string;
  operateUsername?: string;
  operateRealName?: string;
  approveComment?: string;
  approveTime?: string;
  operateTime?: string;
};

const message = useMessage();

const loading = ref(false);
const rejectVisible = ref(false);
const cancelVisible = ref(false);
const decisionDialog = ref<InstanceType<typeof ApprovalDecisionDialog>>();
const progressVisible = ref(false);
const rejectReason = ref('');
const cancelReason = ref('');
const progressData = ref<any>({ main: {}, details: [], logs: [] });
const changeRows = computed(() => {
  const rows = progressData.value?.changePreview?.rows;
  return Array.isArray(rows) ? rows : [];
});

const dropdownOptions = computed(() =>
  [
    { label: '送审', key: 'apply', permission: 'approval.apply' },
    { label: '审批通过', key: 'approve', permission: 'approval.approve' },
    { label: '驳回', key: 'reject', permission: 'approval.reject' },
    { label: '撤销送审', key: 'cancel', permission: 'approval.cancel' },
    { label: '查看审批进度', key: 'progress', permission: 'approval.progress' }
  ].filter(item => hasButton(item.permission))
);

const visible = computed(() => dropdownOptions.value.length > 0);

const detailColumns: DataTableColumns<any> = [
  { title: '级别', key: 'approvalLevel', width: 70 },
  { title: '节点', key: 'nodeName', minWidth: 140 },
  { title: '预计审批人', key: 'expectedApprovers', minWidth: 220, ellipsis: { tooltip: true } },
  { title: '实际审批人', key: 'actualApprovers', minWidth: 180, ellipsis: { tooltip: true } },
  {
    title: '状态',
    key: 'status',
    width: 110,
    render: row => renderStatus(row.status)
  }
];

const logColumns: DataTableColumns<any> = [
  { title: '动作', key: 'actionType', width: 120 },
  { title: '操作人', key: 'actionRealName', width: 120, render: row => row.actionRealName || row.actionUsername || '-' },
  { title: '状态', key: 'toStatus', width: 120, render: row => statusText(row.toStatus || row.fromStatus) },
  { title: '意见', key: 'actionComment', minWidth: 180, ellipsis: { tooltip: true } },
  { title: '说明', key: 'detailMessage', minWidth: 220, ellipsis: { tooltip: true } }
];

const changeColumns: DataTableColumns<any> = [
  { title: '表', key: 'tableName', width: 150, ellipsis: { tooltip: true }, render: row => row.tableName || row.tableCode || '-' },
  { title: '记录ID', key: 'recordId', width: 100 },
  { title: '字段', key: 'fieldLabel', width: 150, ellipsis: { tooltip: true }, render: row => row.fieldLabel || row.field || '-' },
  { title: '当前值', key: 'oldValue', minWidth: 180, ellipsis: { tooltip: true }, render: row => displayValue(row.oldValue) },
  { title: '拟修改值', key: 'newValue', minWidth: 180, ellipsis: { tooltip: true }, render: row => displayValue(row.newValue) }
];

const mainStatus = computed(() => progressData.value?.main?.status || '');
const mainStatusText = computed(() => statusText(mainStatus.value) || '暂无审批记录');
const groupedDetails = computed(() => buildGroupedDetails(progressData.value?.details || [], progressData.value?.main));

function renderStatus(status: string) {
  const type =
    status === 'APPROVED' || status === 'AUTO_APPROVED'
      ? 'success'
      : status === 'REJECTED'
        ? 'error'
        : status === 'PENDING' || status === 'APPROVING'
          ? 'warning'
          : 'default';
  return hTag(statusText(status) || '-', type);
}

function statusText(status?: string) {
  const statusMap: Record<string, string> = {
    DRAFT: '草稿',
    APPROVING: '审批中',
    PENDING: '待审批',
    APPROVED: '已通过',
    REJECTED: '已驳回',
    CANCELED: '已撤销',
    WAITING: '等待中',
    SKIPPED: '已跳过',
    AUTO_APPROVED: '自动通过'
  };
  return status ? statusMap[status] || status : '-';
}

function displayValue(value: any) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function hasButton(buttonKey: string) {
  return props.runtime?.permissions?.hasButton?.(buttonKey) === true;
}

function hTag(label: string, type: any) {
  return h(NTag, { size: 'small', type, bordered: false }, { default: () => label });
}

function detailDisplayName(row: ApprovalDetailRow) {
  if (row.targetType === 'ROLE') {
    return row.targetRoleName || '-';
  }
  return row.targetUserName || '-';
}

function uniqueJoin(values: Array<string | null | undefined>) {
  const items = Array.from(
    new Set(
      values
        .map(value => (value || '').trim())
        .filter(Boolean)
    )
  );
  return items.length ? items.join('、') : '-';
}

function resolveGroupNodeName(rows: ApprovalDetailRow[]) {
  return rows.find(row => row.nodeName)?.nodeName || '-';
}

function summarizeGroupStatus(rows: ApprovalDetailRow[]) {
  const statuses = rows.map(row => row.status).filter(Boolean) as string[];
  if (statuses.includes('REJECTED')) return 'REJECTED';
  if (statuses.includes('PENDING')) return 'PENDING';
  if (statuses.includes('APPROVING')) return 'APPROVING';
  if (statuses.includes('APPROVED')) return 'APPROVED';
  if (statuses.includes('AUTO_APPROVED')) return 'AUTO_APPROVED';
  if (statuses.includes('CANCELED')) return 'CANCELED';
  if (statuses.includes('SKIPPED')) return 'SKIPPED';
  return rows[0]?.status || '';
}

function buildGroupedDetails(details: ApprovalDetailRow[], main?: any) {
  const rows = Array.isArray(details) ? details : [];
  const latestRound =
    Number(main?.currentRound || 0) ||
    rows.reduce((max, row) => Math.max(max, Number(row.roundNo || 0)), 0);
  const roundRows = latestRound > 0 ? rows.filter(row => Number(row.roundNo || 0) === latestRound) : rows;
  const levelNodeNameMap = new Map<number, string>();

  for (const row of roundRows) {
    const level = Number(row.approvalLevel || 0);
    if (!levelNodeNameMap.has(level) && row.nodeName) {
      levelNodeNameMap.set(level, row.nodeName);
    }
  }

  const groups = new Map<string, ApprovalDetailRow[]>();
  for (const row of roundRows) {
    const level = Number(row.approvalLevel || 0);
    const nodeName = levelNodeNameMap.get(level) || row.nodeName || '-';
    const key = `${level}|${nodeName}`;
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(row);
  }

  return Array.from(groups.values()).map(groupRows => {
    const actualRows = groupRows.filter(row => ['APPROVED', 'REJECTED'].includes(row.status || ''));

    return {
      approvalLevel: groupRows[0]?.approvalLevel,
      nodeName: resolveGroupNodeName(groupRows),
      expectedApprovers: uniqueJoin(groupRows.map(row => detailDisplayName(row))),
      actualApprovers: uniqueJoin(actualRows.map(row => row.operateRealName || row.operateUsername || '-')),
      status: summarizeGroupStatus(groupRows)
    };
  });
}

async function handleSelect(key: string) {
  if (key === 'reject') {
    if (!hasButton('approval.reject')) return;
    if (!buildPayload()) return;
    rejectReason.value = '';
    rejectVisible.value = true;
    return;
  }

  if (key === 'progress') {
    if (!hasButton('approval.progress')) return;
    await openProgress();
    return;
  }

  if (key === 'cancel') {
    if (!hasButton('approval.cancel')) return;
    if (!buildPayload()) return;
    cancelReason.value = '';
    cancelVisible.value = true;
    return;
  }

  if (key === 'apply') {
    if (!hasButton('approval.apply')) return;
    await runAction(() => applyApproval(requiredPayload()), '送审完成');
    return;
  }

  if (key === 'approve') {
    if (!hasButton('approval.approve')) return;
    await prepareApprovalAction('approve');
  }
}

async function submitReject() {
  if (!rejectReason.value.trim()) {
    message.warning('请填写驳回原因');
    return false;
  }
  const prepared = await prepareApprovalAction('reject', rejectReason.value.trim());
  if (prepared) rejectVisible.value = false;
  return false;
}

async function submitCancel() {
  await runAction(
    () =>
      cancelApproval({
        ...requiredPayload(),
        comment: cancelReason.value.trim()
      }),
    '已撤销送审'
  );
  cancelVisible.value = false;
}

async function openProgress() {
  const payload = buildPayload();
  if (!payload) return;

  loading.value = true;
  try {
    const { data, error } = await fetchApprovalProgress({
      pageCode: payload.pageCode,
      tableCode: payload.tableCode,
      billId: payload.billId
    });
    if (error) {
      message.error(error.message || '查询审批进度失败');
      return;
    }
    progressData.value = data || { main: {}, details: [], logs: [] };
    progressVisible.value = true;
  } finally {
    loading.value = false;
  }
}

async function prepareApprovalAction(action: 'approve' | 'reject', comment = '') {
  const payload = buildPayload();
  if (!payload) return false;
  return decisionDialog.value?.open(payload, action, comment) ?? false;
}

async function decisionCompleted() {
  rejectVisible.value = false;
  await syncCurrentData();
  if (progressVisible.value) await openProgress();
}

async function runAction(action: () => Promise<any>, fallbackMessage: string) {
  loading.value = true;
  try {
    const { data, error } = await action();
    if (error) {
      message.error(error.message || `${fallbackMessage}失败`);
      return;
    }
    message.success(data?.message || fallbackMessage);
    await syncCurrentData();
    if (progressVisible.value) {
      await openProgress();
    }
  } finally {
    loading.value = false;
  }
}

function requiredPayload() {
  const payload = buildPayload();
  if (!payload) {
    throw new Error('请选择一条单据');
  }
  return payload;
}

function buildPayload(): ApprovalRuntimePayload | null {
  const row = props.getSelectedRow?.();
  if (!row) {
    message.warning('请先选择一条单据');
    return null;
  }

  const pageCode = props.runtime?.pageCode || '';
  const pageConfig = unref(props.runtime?.meta?.pageConfig);
  const tableCode = pageConfig?.masterTableCode || '';
  const billId = row.id ?? row.ID;

  if (!pageCode || !tableCode || billId == null) {
    message.warning('当前页面缺少审批所需参数');
    return null;
  }

  return {
    pageCode,
    pageName: pageCode,
    tableCode,
    billId,
    billNo: firstText(row.billNo, row.BILL_NO, row.batchNo, row.BATCH_NO, row.code, row.CODE),
    billTitle: firstText(
      row.billTitle,
      row.BILL_TITLE,
      row.projectOrCustomerCode,
      row.PROJECT_OR_CUSTOMER_CODE,
      row.inspectionName,
      row.INSPECTION_NAME,
      `${pageCode}#${billId}`
    ),
    conditionJson: ''
  };
}

function firstText(...values: any[]) {
  for (const value of values) {
    if (value !== null && value !== undefined && String(value).trim()) {
      return String(value);
    }
  }
  return '';
}

async function syncCurrentData() {
  const row = props.getSelectedRow?.();
  const masterId = Number(row?.id ?? row?.ID);
  const rowKey = row?._rowKey ? String(row._rowKey) : props.runtime?.activeMasterRowKey?.value;
  const workingSet = props.runtime?.workingSet;

  if (!Number.isNaN(masterId) && masterId > 0 && rowKey && workingSet?.reloadMasterRow && workingSet?.loadDetailData) {
    await workingSet.reloadMasterRow(masterId, rowKey);
    await workingSet.loadDetailData(masterId, rowKey);
    props.runtime?.masterGridApi?.value?.refreshCells?.({ force: true });
    return;
  }

  refreshGrid();
}

function refreshGrid() {
  const api = props.runtime?.masterGridApi?.value;
  api?.refreshServerSide?.({ purge: false });
}
</script>

<template>
  <NDropdown v-if="visible" trigger="click" :options="dropdownOptions" @select="handleSelect">
    <NButton type="primary" size="small" :loading="loading">送审</NButton>
  </NDropdown>

  <NModal
    v-model:show="rejectVisible"
    preset="dialog"
    title="驳回审批"
    positive-text="确认驳回"
    negative-text="取消"
    :mask-closable="false"
    @positive-click="submitReject"
  >
    <NInput v-model:value="rejectReason" type="textarea" placeholder="请输入驳回原因" :autosize="{ minRows: 4, maxRows: 8 }" />
  </NModal>

  <NModal
    v-model:show="cancelVisible"
    preset="dialog"
    title="撤销送审"
    positive-text="确认撤销"
    negative-text="取消"
    :mask-closable="false"
    @positive-click="submitCancel"
  >
    <NInput
      v-model:value="cancelReason"
      type="textarea"
      placeholder="请输入撤销原因，可选"
      :autosize="{ minRows: 4, maxRows: 8 }"
    />
  </NModal>

  <ApprovalDecisionDialog ref="decisionDialog" @busy="loading = $event" @complete="decisionCompleted" />

  <NModal v-model:show="progressVisible" preset="card" title="审批进度" class="approval-progress-modal">
    <NSpace vertical size="small">
      <div class="approval-main">
        <span>审批状态：</span>
        <NTag size="small" :type="mainStatus === 'APPROVED' ? 'success' : mainStatus === 'REJECTED' ? 'error' : 'info'">
          {{ mainStatusText }}
        </NTag>
        <span v-if="progressData.main?.approvalId">审批ID：{{ progressData.main.approvalId }}</span>
      </div>
      <NTabs type="line" animated>
        <NTabPane v-if="changeRows.length > 0" name="changes" tab="变更对比">
          <NDataTable size="small" :columns="changeColumns" :data="changeRows" :pagination="false" :scroll-x="760" />
        </NTabPane>
        <NTabPane name="details" tab="审批节点">
          <NDataTable size="small" :columns="detailColumns" :data="groupedDetails" :pagination="false" />
          <ApprovalObjectProgress :progress="progressData.objectProgress" :details="progressData.details" />
        </NTabPane>
        <NTabPane name="logs" tab="审批记录">
          <NDataTable size="small" :columns="logColumns" :data="progressData.logs || []" :pagination="false" />
        </NTabPane>
      </NTabs>
    </NSpace>
  </NModal>
</template>

<style scoped>
.approval-main {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #4b5565;
  font-size: 13px;
}

.action-param-control {
  width: 100%;
}
</style>

<style>
.approval-progress-modal {
  width: min(980px, 92vw);
}
</style>
