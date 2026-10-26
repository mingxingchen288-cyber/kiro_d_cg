import { request } from '../request';

export interface DynamicQueryCondition {
  tableKey?: string;
  field: string;
  operator: string;
  value: any;
  value2?: any;
  groupId?: string;
  logicOperator?: 'AND' | 'OR';
}

/** 查询动态数据列表 */
export function fetchDynamicData(tableCode: string, params?: Record<string, any>) {
  return request<Api.Common.PageResult<any>>({
    url: `/api/data/${tableCode}`,
    params
  });
}

/** 高级查询（支持 pageCode 数据权限） */
export function searchDynamicData(
  tableCode: string,
  params: {
    page?: number;
    pageSize?: number;
    sortField?: string;
    sortOrder?: string;
    pageCode?: string;
    conditions?: DynamicQueryCondition[];
  }
) {
  return request<Api.Common.PageResult<any>>({
    url: `/api/data/${tableCode}/search`,
    method: 'POST',
    data: params
  });
}

/** 查询单条数据 */
export function fetchDynamicDataById(tableCode: string, id: number | string) {
  return request<any>({
    url: `/api/data/${tableCode}/${id}`
  });
}

/** 新增数据 */
export function createDynamicData(tableCode: string, data: Record<string, any>) {
  return request<any>({
    url: `/api/data/${tableCode}`,
    method: 'POST',
    data
  });
}

/** 更新数据 */
export function updateDynamicData(tableCode: string, id: number | string, data: Record<string, any>) {
  return request<any>({
    url: `/api/data/${tableCode}/${id}`,
    method: 'PUT',
    data
  });
}

/** 删除数据 */
export function deleteDynamicData(tableCode: string, id: number | string) {
  return request<any>({
    url: `/api/data/${tableCode}/${id}`,
    method: 'DELETE'
  });
}

/** 通用保存（支持单表/主从表/主从多Tab，含变更追踪和乐观锁） */
export interface DynamicSaveResult {
  masterId: number;
  idMapping?: Record<number, number>;
  committed?: boolean;
  pendingApproval?: boolean;
  changeRequestId?: number;
  approvalId?: number | string;
  approvalStatus?: string;
  message?: string;
  masterRow?: Record<string, any>;
  detailRows?: Record<string, any[]>;
}

export interface DynamicSaveParam {
  pageCode: string;
  requestId: string;
  master: any;
  details?: Record<string, any[]>;
}

export function createDynamicSaveRequestId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function saveDynamicData(param: DynamicSaveParam) {
  return request<DynamicSaveResult>({
    url: '/api/data/save',
    method: 'POST',
    // 送审需获取关联单据快照并建立冻结，批量对象可能超过普通查询的超时。
    timeout: 180_000,
    data: param
  });
}

/** 执行页面规则中的 Action（TOOLBAR/CONTEXT_MENU） */
export function executePageRuleAction(
  pageCode: string,
  params: {
    componentKey?: string;
    actionCode: string;
    data?: Record<string, any>;
  }
) {
  return request<any>({
    url: `/api/data/page/${pageCode}/execute`,
    method: 'POST',
    data: params
  });
}
