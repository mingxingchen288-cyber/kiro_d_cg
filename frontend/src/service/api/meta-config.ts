import { request } from '../request';

// ==================== 目录管理 ====================

export async function fetchAllResources() {
  const { data } = await request<any[]>({ url: '/meta-config/resources' });
  return data || [];
}

export async function saveResource(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/resource', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteResource(id: number) {
  const { error } = await request<any>({ url: `/meta-config/resource/${id}`, method: 'DELETE' });
  if (error) throw error;
}

// ==================== 表管理 ====================

export async function fetchAllTableMeta() {
  const { data } = await request<any[]>({ url: '/meta-config/tables' });
  return data || [];
}

/** 根据 pageCode 查询关联的表元数据 */
export async function fetchTablesByPageCode(pageCode: string) {
  const { data } = await request<any[]>({ url: '/meta-config/tables-by-page', params: { pageCode } });
  return data || [];
}

export async function saveTableMeta(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/table', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteTableMeta(id: number) {
  const { error } = await request<any>({ url: `/meta-config/table/${id}`, method: 'DELETE' });
  if (error) throw error;
}

export async function fetchColumnsByTableId(tableId: number) {
  const { data } = await request<any[]>({ url: `/meta-config/table/${tableId}/columns` });
  return data || [];
}

export async function saveColumnMeta(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/column', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteColumnMeta(id: number) {
  const { error } = await request<any>({ url: `/meta-config/column/${id}`, method: 'DELETE' });
  if (error) throw error;
}

/** 查询视图/表的物理列结构 */
export async function fetchViewColumns(viewName: string, owner = 'CMX') {
  const { data } = await request<any[]>({ url: '/meta-config/view-columns', params: { viewName, owner } });
  return data || [];
}

/** 根据 pageCode 查询关联的 lookupCode 列表 */
export async function fetchLookupCodesByPageCode(pageCode: string) {
  const { data } = await request<string[]>({ url: '/meta-config/lookup-codes-by-page', params: { pageCode } });
  return data || [];
}

// ==================== 页面管理 ====================

export async function fetchAllPageComponents() {
  const { data } = await request<any[]>({ url: '/meta-config/components' });
  return data || [];
}

export async function savePageComponent(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/component', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deletePageComponent(id: number) {
  const { error } = await request<any>({ url: `/meta-config/component/${id}`, method: 'DELETE' });
  if (error) throw error;
}

export async function fetchRulesByComponent(pageCode: string, componentKey: string) {
  const { data } = await request<any[]>({ url: '/meta-config/rules', params: { pageCode, componentKey } });
  return data || [];
}

export async function savePageRule(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/rule', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deletePageRule(id: number) {
  const { error } = await request<any>({ url: `/meta-config/rule/${id}`, method: 'DELETE' });
  if (error) throw error;
}

// ==================== Lookup管理 ====================

export async function fetchAllLookupConfigs() {
  const { data } = await request<any[]>({ url: '/meta-config/lookups' });
  return data || [];
}

export async function saveLookupConfig(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/lookup', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteLookupConfig(id: number) {
  const { error } = await request<any>({ url: `/meta-config/lookup/${id}`, method: 'DELETE' });
  if (error) throw error;
}

// ==================== 导出配置管理 ====================

export async function fetchAllExportConfigs() {
  const { data } = await request<any[]>({ url: '/meta-config/export-configs' });
  return data || [];
}

export async function saveExportConfig(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/export-config', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteExportConfig(id: number) {
  const { error } = await request<any>({ url: `/meta-config/export-config/${id}`, method: 'DELETE' });
  if (error) throw error;
}

export async function fetchExportConfigDetails(configId: number) {
  const { data } = await request<any[]>({ url: `/meta-config/export-config/${configId}/details` });
  return data || [];
}

export async function saveExportConfigDetail(data: Record<string, any>) {
  const { data: res, error } = await request<any>({
    url: '/meta-config/export-config-detail',
    method: 'POST',
    data
  });
  if (error) throw error;
  return res;
}

export async function deleteExportConfigDetail(id: number) {
  const { error } = await request<any>({ url: `/meta-config/export-config-detail/${id}`, method: 'DELETE' });
  if (error) throw error;
}

// ==================== 审批流配置 ====================

export async function fetchApprovalFlows() {
  const { data } = await request<any[]>({ url: '/meta-config/approval/flows' });
  return data || [];
}

export async function saveApprovalFlow(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/approval/flow', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteApprovalFlow(flowId: number) {
  const { error } = await request<any>({ url: `/meta-config/approval/flow/${flowId}`, method: 'DELETE' });
  if (error) throw error;
}

export async function deleteApprovalPage(pageCode: string) {
  const { error } = await request<any>({
    url: `/meta-config/approval/page/${encodeURIComponent(pageCode)}`,
    method: 'DELETE'
  });
  if (error) throw error;
}

export async function fetchApprovalConditions(flowId: number) {
  const { data } = await request<any[]>({ url: `/meta-config/approval/flow/${flowId}/conditions` });
  return data || [];
}

export async function saveApprovalCondition(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/approval/condition', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteApprovalCondition(conditionId: number) {
  const { error } = await request<any>({ url: `/meta-config/approval/condition/${conditionId}`, method: 'DELETE' });
  if (error) throw error;
}

export async function fetchApprovalNodes(flowId: number) {
  const { data } = await request<any[]>({ url: `/meta-config/approval/flow/${flowId}/nodes` });
  return data || [];
}

export async function saveApprovalNode(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/approval/node', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteApprovalNode(nodeId: number) {
  const { error } = await request<any>({ url: `/meta-config/approval/node/${nodeId}`, method: 'DELETE' });
  if (error) throw error;
}

export async function fetchApprovalApprovers(nodeId: number) {
  const { data } = await request<any[]>({ url: `/meta-config/approval/node/${nodeId}/approvers` });
  return data || [];
}

export async function saveApprovalApprover(data: Record<string, any>) {
  const { data: res, error } = await request<any>({ url: '/meta-config/approval/approver', method: 'POST', data });
  if (error) throw error;
  return res;
}

export async function deleteApprovalApprover(id: number) {
  const { error } = await request<any>({ url: `/meta-config/approval/approver/${id}`, method: 'DELETE' });
  if (error) throw error;
}

export async function fetchApprovalReferenceData() {
  const { data } = await request<Record<string, any[]>>({ url: '/meta-config/approval/reference-data' });
  return data || {};
}

/** 查询数据库表/视图列表（模糊搜索） */
export async function fetchDbObjects(keyword?: string, types = 'TABLE,VIEW', owner = 'CMX') {
  const { data } = await request<any[]>({ url: '/meta-config/db-objects', params: { keyword, types, owner } });
  return data || [];
}
