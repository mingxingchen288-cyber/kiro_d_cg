import { request } from '../request';
import type { ApprovalDecisionMode, ApprovalDirection } from './approval-config';

export type ApprovalRuntimePayload = {
  pageCode: string;
  pageName?: string;
  tableCode: string;
  billId: number | string;
  billNo?: string;
  billTitle?: string;
  conditionJson?: string;
  detailId?: number | string;
  approvalId?: number | string;
  comment?: string;
  actionParams?: Record<string, unknown> | string;
  actionParamsJson?: string;
  selectedObjectKeys?: string[];
};

export interface ApprovalRuntimeObject {
  key: string;
  tableCode: string;
  id: number | string;
  label: string;
  values: Record<string, unknown>;
  status: string;
  decisions?: ApprovalObjectDecision[];
}

export interface ApprovalObjectDecision {
  detailId: number | string;
  level: number;
  selected: boolean;
  mode: 'AND' | 'OR';
  levelComplete: boolean;
  effective: boolean;
}

export interface ApprovalObjectProgressData {
  direction?: ApprovalDirection;
  decisionMode?: ApprovalDecisionMode;
  objects?: ApprovalRuntimeObject[];
}

export interface ApprovalRuntimeObjectColumn {
  field: string;
  label?: string;
  headerName?: string;
}

export interface ApprovalRuntimeParameter {
  name: string;
  label?: string;
  type?: string;
  required?: boolean;
  defaultValue?: unknown;
}

export interface ApprovalRuntimeActionConfig {
  enabled?: boolean;
  mode?: 'AUTO' | 'MANUAL';
  params?: ApprovalRuntimeParameter[];
  rejectionParams?: ApprovalRuntimeParameter[];
  decisionMode?: ApprovalDecisionMode;
  allowSourceOnlyApproval?: boolean;
  objects?: ApprovalRuntimeObject[];
  objectColumns?: ApprovalRuntimeObjectColumn[];
}

export type ApprovalNotificationTab = 'approval' | 'initiated';
export type ApprovalNotificationScope = 'pending' | 'all';

export type ApprovalNotificationItem = {
  type?: 'APPROVAL' | 'NOTICE';
  noticeKind?: string;
  detailId?: number | string | null;
  approvalId?: number | string | null;
  pageCode?: string;
  pageName?: string;
  tableCode?: string;
  billId?: number | string | null;
  billNo?: string;
  billTitle?: string;
  sourcePageCode?: string;
  masterTableCode?: string;
  masterId?: number | string | null;
  approvalStatus?: string;
  currentLevel?: number | string | null;
  currentRound?: number | string | null;
  nodeName?: string;
  approvalLevel?: number | string | null;
  approvalMode?: string;
  detailStatus?: string;
  targetType?: string;
  targetUserName?: string;
  targetRoleName?: string;
  startUserId?: number | string | null;
  startUsername?: string;
  startRealName?: string;
  startTime?: string;
  createTime?: string;
  finishedTime?: string;
  changeType?: string;
  targetTableCode?: string;
  targetRecordId?: number | string | null;
  targetDocid?: number | string | null;
  targetGoodsid?: number | string | null;
};

export type ApprovalNotificationSummary = {
  unreadCount?: number;
  approvalCount?: number;
  allApprovalCount?: number;
  noticeCount?: number;
  initiatedCount?: number;
  pendingInitiatedCount?: number;
};

export function fetchApprovalNotificationSummary() {
  return request<ApprovalNotificationSummary>({
    url: '/approval/notifications/summary'
  });
}

export function fetchApprovalNotifications(params: {
  tab?: ApprovalNotificationTab;
  scope?: ApprovalNotificationScope;
  limit?: number;
}) {
  return request<{
    tab: string;
    scope: ApprovalNotificationScope;
    items: ApprovalNotificationItem[];
    summary: ApprovalNotificationSummary;
  }>({
    url: '/approval/notifications/list',
    params
  });
}

export function applyApproval(data: ApprovalRuntimePayload) {
  return request<any>({
    url: '/approval/runtime/apply',
    method: 'POST',
    data
  });
}

export function approveApproval(data: ApprovalRuntimePayload) {
  return request<any>({
    url: '/approval/runtime/approve',
    method: 'POST',
    // 批量对象审批包含快照复核、定向同步和重算，需等待整个事务完成。
    timeout: 180_000,
    data
  });
}

export function rejectApproval(data: ApprovalRuntimePayload) {
  return request<any>({
    url: '/approval/runtime/reject',
    method: 'POST',
    timeout: 180_000,
    data
  });
}

export function cancelApproval(data: ApprovalRuntimePayload) {
  return request<any>({
    url: '/approval/runtime/cancel',
    method: 'POST',
    data
  });
}

export function fetchApprovalProgress(params: { pageCode: string; tableCode: string; billId: number | string }) {
  return request<any>({
    url: '/approval/runtime/progress',
    params
  });
}

export function fetchApprovalActionConfig(params: {
  pageCode: string;
  tableCode: string;
  billId: number | string;
  action: 'approve' | 'reject';
}) {
  return request<ApprovalRuntimeActionConfig>({
    url: '/approval/runtime/action-config',
    params
  });
}
