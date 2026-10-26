<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import {
  NBadge,
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NModal,
  NScrollbar,
  NSpace,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  useMessage
} from 'naive-ui';
import type { DataTableColumns } from 'naive-ui';
import {
  type ApprovalNotificationItem,
  type ApprovalNotificationScope,
  type ApprovalNotificationSummary,
  type ApprovalNotificationTab,
  type ApprovalRuntimePayload,
  fetchApprovalNotificationSummary,
  fetchApprovalNotifications,
  fetchApprovalProgress
} from '@/service/api/approval-runtime';
import ApprovalDecisionDialog from '@/components/approval/ApprovalDecisionDialog.vue';
import ApprovalObjectProgress from '@/components/approval/ApprovalObjectProgress.vue';

defineOptions({
  name: 'ApprovalNotificationCenter'
});

type ApprovalDetailRow = {
  roundNo?: number | string;
  approvalLevel?: number | string;
  nodeName?: string;
  targetType?: string;
  targetUserName?: string;
  targetRoleName?: string;
  status?: string;
  operateUsername?: string;
  operateRealName?: string;
};

const router = useRouter();
const message = useMessage();

const drawerVisible = ref(false);
const detailVisible = ref(false);
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const decisionDialog = ref<InstanceType<typeof ApprovalDecisionDialog>>();
const activeTab = ref<ApprovalNotificationTab>('approval');
const activeScope = ref<ApprovalNotificationScope>('pending');
const items = ref<ApprovalNotificationItem[]>([]);
const summary = ref<ApprovalNotificationSummary>({});
const selectedItem = ref<ApprovalNotificationItem | null>(null);
const progressData = ref<any>({ main: {}, details: [], logs: [] });
const decisionComment = ref('');
let summaryTimer: number | null = null;

const unreadCount = computed(() => Number(summary.value.unreadCount || 0));
const pendingOnly = computed(() => activeScope.value === 'pending');
const approvalTabLabel = computed(() => (pendingOnly.value ? '待审批' : '全部审批'));
const initiatedTabLabel = computed(() => (pendingOnly.value ? '我的发起（待审批）' : '我的发起'));
const approvalSummaryCount = computed(() =>
  pendingOnly.value ? Number(summary.value.approvalCount || 0) : Number(summary.value.allApprovalCount || 0)
);
const initiatedSummaryCount = computed(() =>
  pendingOnly.value ? Number(summary.value.pendingInitiatedCount || 0) : Number(summary.value.initiatedCount || 0)
);
const changeRows = computed(() => {
  const rows = progressData.value?.changePreview?.rows;
  return Array.isArray(rows) ? rows : [];
});
const changePreviewError = computed(() => progressData.value?.changePreview?.error || '');
const groupedDetails = computed(() => buildGroupedDetails(progressData.value?.details || [], progressData.value?.main));
const canDecide = computed(
  () =>
    selectedItem.value?.type === 'APPROVAL' &&
    selectedItem.value?.detailStatus === 'PENDING' &&
    selectedItem.value.detailId !== null &&
    selectedItem.value.detailId !== undefined
);

const changeColumns: DataTableColumns<any> = [
  {
    title: '表',
    key: 'tableName',
    width: 150,
    ellipsis: { tooltip: true },
    render: row => row.tableName || row.tableCode || '-'
  },
  { title: '记录ID', key: 'recordId', width: 100 },
  {
    title: '字段',
    key: 'fieldLabel',
    width: 150,
    ellipsis: { tooltip: true },
    render: row => row.fieldLabel || row.field || '-'
  },
  {
    title: '当前值',
    key: 'oldValue',
    minWidth: 180,
    ellipsis: { tooltip: true },
    render: row => displayValue(row.oldValue)
  },
  {
    title: '拟修改值',
    key: 'newValue',
    minWidth: 180,
    ellipsis: { tooltip: true },
    render: row => displayValue(row.newValue)
  }
];

const detailColumns: DataTableColumns<any> = [
  { title: '级别', key: 'approvalLevel', width: 70 },
  { title: '节点', key: 'nodeName', minWidth: 140, ellipsis: { tooltip: true } },
  { title: '预计审批人', key: 'expectedApprovers', minWidth: 220, ellipsis: { tooltip: true } },
  { title: '实际审批人', key: 'actualApprovers', minWidth: 180, ellipsis: { tooltip: true } },
  { title: '状态', key: 'status', width: 110, render: row => renderStatus(row.status) }
];

const logColumns: DataTableColumns<any> = [
  { title: '动作', key: 'actionType', width: 120 },
  {
    title: '操作人',
    key: 'actionRealName',
    width: 120,
    render: row => row.actionRealName || row.actionUsername || '-'
  },
  { title: '状态', key: 'toStatus', width: 120, render: row => statusText(row.toStatus || row.fromStatus) },
  { title: '意见', key: 'actionComment', minWidth: 180, ellipsis: { tooltip: true } },
  { title: '说明', key: 'detailMessage', minWidth: 220, ellipsis: { tooltip: true } }
];

watch([activeTab, activeScope], () => {
  if (drawerVisible.value) {
    loadItems();
  }
});

onMounted(() => {
  loadSummary();
  summaryTimer = window.setInterval(() => {
    loadSummary();
  }, 60_000);
});

onBeforeUnmount(() => {
  if (summaryTimer !== null) {
    window.clearInterval(summaryTimer);
  }
});

async function openDrawer() {
  drawerVisible.value = true;
  await Promise.all([loadSummary(), loadItems()]);
}

async function loadSummary() {
  const { data, error } = await fetchApprovalNotificationSummary();
  if (!error) {
    summary.value = data || {};
  }
}

async function loadItems() {
  loading.value = true;
  try {
    const { data, error } = await fetchApprovalNotifications({
      tab: activeTab.value,
      scope: activeScope.value,
      limit: 80
    });
    if (error) {
      message.error(error.message || '读取消息失败');
      return;
    }
    items.value = Array.isArray(data?.items) ? data.items : [];
    summary.value = data?.summary || summary.value;
  } finally {
    loading.value = false;
  }
}

function toggleScope() {
  activeScope.value = pendingOnly.value ? 'all' : 'pending';
  activeTab.value = 'approval';
}

async function openDetail(item: ApprovalNotificationItem) {
  const payload = payloadFromItem(item);
  if (!payload) return;

  selectedItem.value = item;
  decisionComment.value = '';
  detailLoading.value = true;
  detailVisible.value = true;
  try {
    const { data, error } = await fetchApprovalProgress({
      pageCode: payload.pageCode,
      tableCode: payload.tableCode,
      billId: payload.billId
    });
    if (error) {
      message.error(error.message || '读取审批详情失败');
      return;
    }
    progressData.value = data || { main: {}, details: [], logs: [] };
  } finally {
    detailLoading.value = false;
  }
}

async function submitDecision(action: 'approve' | 'reject') {
  const item = selectedItem.value;
  if (!item) return;
  if (action === 'reject' && !decisionComment.value.trim()) {
    message.warning('请填写驳回原因');
    return;
  }

  const payload = payloadFromItem(item);
  if (!payload) return;

  await decisionDialog.value?.open(payload, action, decisionComment.value.trim());
}

async function decisionCompleted() {
  detailVisible.value = false;
  selectedItem.value = null;
  await Promise.all([loadSummary(), loadItems()]);
}

function payloadFromItem(item: ApprovalNotificationItem): ApprovalRuntimePayload | null {
  const pageCode = item.pageCode || item.sourcePageCode || '';
  const tableCode = item.tableCode || item.masterTableCode || '';
  const billId = item.billId ?? item.masterId;

  if (!pageCode || !tableCode || billId === null || billId === undefined) {
    message.warning('当前消息缺少审批参数');
    return null;
  }

  return {
    pageCode,
    pageName: item.pageName || pageCode,
    tableCode,
    billId,
    billNo: item.billNo,
    billTitle: item.billTitle,
    detailId: item.detailId ?? undefined,
    approvalId: item.approvalId ?? undefined,
    conditionJson: ''
  };
}

function openOriginal(item: ApprovalNotificationItem) {
  const pageCode = item.sourcePageCode || item.pageCode;
  if (!pageCode) {
    message.warning('当前消息缺少原单据页面');
    return;
  }
  const originalRoute = router.getRoutes().find(route => route.meta.pageCode === pageCode);
  if (!originalRoute) {
    message.warning('当前账号没有可打开的原单据页面');
    return;
  }
  const id = item.masterId ?? item.billId;
  const query: Record<string, string> = {};
  if (id !== null && id !== undefined) query.focusId = String(id);
  if (item.approvalId !== null && item.approvalId !== undefined) query.approvalId = String(item.approvalId);
  drawerVisible.value = false;
  detailVisible.value = false;
  router.push({ path: originalRoute.path, query });
}

function itemTitle(item: ApprovalNotificationItem) {
  return item.billTitle || item.billNo || `${item.pageName || item.pageCode || '审批'} #${item.billId || ''}`;
}

function itemSubTitle(item: ApprovalNotificationItem) {
  if (item.type === 'APPROVAL') {
    return `${statusText(item.detailStatus || item.approvalStatus)} · ${
      item.startRealName || item.startUsername || '发起人'
    } 发起`;
  }
  return `${statusText(item.approvalStatus)} · ${item.startRealName || item.startUsername || '我'} 发起`;
}

function itemTagText(item: ApprovalNotificationItem) {
  if (item.type === 'APPROVAL') return pendingOnly.value ? '待审批' : '审批记录';
  if (item.noticeKind === 'INITIATED_APPROVAL') return pendingOnly.value ? '我发起待审批' : '我发起';
  return '通知';
}

function itemTagType(item: ApprovalNotificationItem) {
  if (item.type === 'APPROVAL') return statusTagType(item.detailStatus || item.approvalStatus);
  if (item.approvalStatus === 'APPROVED') return 'success';
  if (item.approvalStatus === 'REJECTED') return 'error';
  return 'info';
}

function statusTagType(status?: string) {
  if (status === 'APPROVED' || status === 'AUTO_APPROVED') return 'success';
  if (status === 'REJECTED') return 'error';
  if (status === 'PENDING' || status === 'APPROVING') return 'warning';
  return 'default';
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

function renderStatus(status: string) {
  return h(
    NTag,
    { size: 'small', type: statusTagType(status), bordered: false },
    { default: () => statusText(status) }
  );
}

function displayValue(value: any) {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function formatTime(value?: string) {
  if (!value) return '-';
  return String(value).replace('T', ' ').slice(0, 19);
}

function detailDisplayName(row: ApprovalDetailRow) {
  if (row.targetType === 'ROLE') {
    return row.targetRoleName || '-';
  }
  return row.targetUserName || '-';
}

function uniqueJoin(values: Array<string | null | undefined>) {
  const texts = Array.from(new Set(values.map(value => (value || '').trim()).filter(Boolean)));
  return texts.length ? texts.join('、') : '-';
}

function buildGroupedDetails(details: ApprovalDetailRow[], main?: any) {
  const rows = Array.isArray(details) ? details : [];
  const latestRound =
    Number(main?.currentRound || 0) || rows.reduce((max, row) => Math.max(max, Number(row.roundNo || 0)), 0);
  const roundRows = latestRound > 0 ? rows.filter(row => Number(row.roundNo || 0) === latestRound) : rows;
  const groups = new Map<string, ApprovalDetailRow[]>();

  for (const row of roundRows) {
    const key = `${row.approvalLevel || 0}|${row.nodeName || '-'}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(row);
  }

  return Array.from(groups.values()).map(groupRows => {
    const actualRows = groupRows.filter(row => ['APPROVED', 'REJECTED'].includes(row.status || ''));
    return {
      approvalLevel: groupRows[0]?.approvalLevel,
      nodeName: groupRows.find(row => row.nodeName)?.nodeName || '-',
      expectedApprovers: uniqueJoin(groupRows.map(row => detailDisplayName(row))),
      actualApprovers: uniqueJoin(actualRows.map(row => row.operateRealName || row.operateUsername || '-')),
      status: summarizeGroupStatus(groupRows)
    };
  });
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
</script>

<template>
  <ButtonIcon tooltip-content="消息中心" @click="openDrawer">
    <NBadge :value="unreadCount" :show="unreadCount > 0" type="error" :max="99">
      <SvgIcon icon="ph:bell" class="text-icon-large" />
    </NBadge>
  </ButtonIcon>

  <NDrawer v-model:show="drawerVisible" :width="520" placement="right">
    <NDrawerContent title="消息中心" closable>
      <div class="notice-summary">
        <div>
          <span class="summary-value">{{ approvalSummaryCount }}</span>
          <span class="summary-label">{{ approvalTabLabel }}</span>
        </div>
        <div>
          <span class="summary-value">{{ initiatedSummaryCount }}</span>
          <span class="summary-label">{{ initiatedTabLabel }}</span>
        </div>
      </div>

      <div class="notice-toolbar">
        <span>{{ pendingOnly ? '当前只显示需要处理的审批' : '当前显示全部审批历史' }}</span>
        <NButton size="tiny" secondary @click="toggleScope">
          {{ pendingOnly ? '查看全部' : '只看待审批' }}
        </NButton>
      </div>

      <NTabs v-model:value="activeTab" type="line" animated>
        <NTabPane name="approval" :tab="approvalTabLabel" />
        <NTabPane name="initiated" :tab="initiatedTabLabel" />
      </NTabs>

      <NSpin :show="loading">
        <NScrollbar class="notice-scroll">
          <NEmpty v-if="items.length === 0" description="暂无消息" class="empty-state" />
          <div
            v-for="item in items"
            :key="`${item.type}-${item.approvalId}-${item.detailId || item.billId}`"
            class="notice-item"
          >
            <div class="notice-item-head">
              <button class="notice-title" type="button" @click="openDetail(item)">
                {{ itemTitle(item) }}
              </button>
              <NTag size="small" :type="itemTagType(item)" :bordered="false">{{ itemTagText(item) }}</NTag>
            </div>
            <div class="notice-item-meta">
              <span>单号：{{ item.billNo || item.approvalId || '-' }}</span>
              <span>时间：{{ formatTime(item.createTime || item.startTime) }}</span>
            </div>
            <div class="notice-item-foot">
              <span>{{ itemSubTitle(item) }}</span>
              <NSpace size="small">
                <NButton size="tiny" secondary @click="openOriginal(item)">原单据</NButton>
                <NButton size="tiny" type="primary" secondary @click="openDetail(item)">
                  {{ item.type === 'APPROVAL' ? '处理' : '查看' }}
                </NButton>
              </NSpace>
            </div>
          </div>
        </NScrollbar>
      </NSpin>
    </NDrawerContent>
  </NDrawer>

  <NModal v-model:show="detailVisible" preset="card" title="审批详情" class="approval-notice-detail-modal">
    <NSpin :show="detailLoading">
      <NSpace vertical size="small">
        <div class="approval-main">
          <span>审批状态：</span>
          <NTag size="small" :type="statusTagType(progressData.main?.status)">
            {{ statusText(progressData.main?.status) }}
          </NTag>
          <span v-if="progressData.main?.approvalId">审批ID：{{ progressData.main.approvalId }}</span>
          <NButton v-if="selectedItem" size="tiny" secondary @click="openOriginal(selectedItem)">原单据</NButton>
        </div>

        <NTabs type="line" animated>
          <NTabPane v-if="changeRows.length > 0 || changePreviewError" name="changes" tab="变更对比">
            <NEmpty v-if="changePreviewError && changeRows.length === 0" :description="changePreviewError" />
            <NDataTable
              v-else
              size="small"
              :columns="changeColumns"
              :data="changeRows"
              :pagination="false"
              :scroll-x="760"
            />
          </NTabPane>
          <NTabPane name="details" tab="审批节点">
            <NDataTable size="small" :columns="detailColumns" :data="groupedDetails" :pagination="false" />
            <ApprovalObjectProgress :progress="progressData.objectProgress" :details="progressData.details" />
          </NTabPane>
          <NTabPane name="logs" tab="审批记录">
            <NDataTable size="small" :columns="logColumns" :data="progressData.logs || []" :pagination="false" />
          </NTabPane>
        </NTabs>

        <div v-if="canDecide" class="decision-panel">
          <NInput
            v-model:value="decisionComment"
            type="textarea"
            placeholder="审批意见；驳回时必填"
            :autosize="{ minRows: 3, maxRows: 6 }"
          />
          <NSpace justify="end">
            <NButton :loading="actionLoading" @click="submitDecision('reject')">驳回</NButton>
            <NButton type="primary" :loading="actionLoading" @click="submitDecision('approve')">批准</NButton>
          </NSpace>
        </div>
      </NSpace>
    </NSpin>
  </NModal>
  <ApprovalDecisionDialog ref="decisionDialog" @busy="actionLoading = $event" @complete="decisionCompleted" />
</template>

<style scoped>
.notice-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}

.notice-summary > div {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #f8fafc;
}

.summary-value {
  display: block;
  color: #1f2937;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.2;
}

.summary-label {
  color: #667085;
  font-size: 12px;
}

.notice-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
  color: #667085;
  font-size: 12px;
}

.notice-scroll {
  height: calc(100vh - 226px);
  padding-right: 4px;
}

.empty-state {
  padding-top: 80px;
}

.notice-item {
  padding: 12px 0;
  border-bottom: 1px solid #edf0f5;
}

.notice-item-head,
.notice-item-foot,
.notice-item-meta,
.approval-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notice-item-head,
.notice-item-foot {
  justify-content: space-between;
}

.notice-title {
  min-width: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  color: #1f2937;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notice-title:hover {
  color: #3f55ff;
}

.notice-item-meta {
  margin-top: 6px;
  color: #667085;
  font-size: 12px;
}

.notice-item-foot {
  margin-top: 10px;
  color: #4b5565;
  font-size: 13px;
}

.approval-main {
  color: #4b5565;
  font-size: 13px;
}

.decision-panel {
  display: grid;
  gap: 10px;
  padding-top: 8px;
}
</style>

<style>
.approval-notice-detail-modal {
  width: min(980px, 92vw);
}
</style>
