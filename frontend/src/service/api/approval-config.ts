import { request } from '../request';

export type ApprovalConditionType = 'ALWAYS' | 'EXPRESSION' | 'SQL';
export type ApprovalMode = 'OR' | 'AND';
export type ApprovalDecisionMode = 'WHOLE' | 'SELECTED';
export type ApprovalDirection = 'NONE' | 'COST_TO_GOODS' | 'GOODS_TO_COST';
export interface ApprovalObjectSource {
  key: string;
  name: string;
  tableCode: string;
  sql: string;
  idColumn: string;
  labelColumn: string;
  displayFields: string[];
}
export interface ApprovalApprover {
  type: 'USER' | 'ROLE' | 'SQL';
  userId?: number | null;
  roleId?: number | null;
  sql?: string;
}
export interface ApprovalEntry {
  nodeId?: number | null;
  level: number;
  name: string;
  mode: ApprovalMode;
  conditionType: ApprovalConditionType;
  condition: string;
  enabled: boolean;
  departmentId?: number | null;
  approvers: ApprovalApprover[];
}
export interface ApprovalDataItem {
  name: string;
  sql: string;
  resultType: 'SCALAR' | 'USER_IDS';
}
export interface ApprovalLock {
  key: string;
  enabled: boolean;
  target: 'MASTER' | 'ALL_DETAILS' | 'CHANGED_DETAILS' | 'RELATED';
  tableCode: string;
  relationField: string;
  sourceField: string;
  fields: string[];
}
export interface ApprovalActionParam {
  name: string;
  label: string;
  type: 'STRING' | 'NUMBER' | 'BOOLEAN' | 'DATE';
  required: boolean;
  source: string;
  value: string | number | boolean | null;
}
export interface ApprovalAction {
  key: string;
  enabled: boolean;
  event: 'NODE_COMPLETED' | 'FLOW_APPROVED' | 'FLOW_REJECTED' | 'FLOW_CANCELED';
  level?: number | null;
  code: 'APPLY_PENDING_CHANGE' | 'PROCEDURE';
  procedure: string;
  mode: 'AUTO' | 'MANUAL';
  params: ApprovalActionParam[];
}
export interface ApprovalDefinition {
  flowId?: number | null;
  pageCode: string;
  flowName: string;
  flowVersion: number;
  flowPriority: number;
  enabled: boolean;
  emptyPolicy: 'AUTO_APPROVE' | 'BLOCK';
  tableCode: string;
  trigger: {
    event: 'MANUAL' | 'SAVE';
    requireApplicantForSubmit?: boolean;
    operations: Array<'modified' | 'added' | 'deleted'>;
    conditionType: ApprovalConditionType;
    condition: string;
  };
  entries: ApprovalEntry[];
  dataItems: ApprovalDataItem[];
  locks: ApprovalLock[];
  actions: ApprovalAction[];
  direction: ApprovalDirection;
  decisionMode: ApprovalDecisionMode;
  objects: ApprovalObjectSource[];
}
export interface ApprovalCatalogTable {
  tableCode: string;
  tableName?: string;
  tableType?: string;
  parentTableCode?: string;
  parentFkColumn?: string;
  columns: Array<{ columnName: string; label?: string; headerText?: string; isVirtual?: boolean }>;
}
export interface ApprovalCatalog {
  tableCode?: string;
  tables: ApprovalCatalogTable[];
  users: Array<{ id: number; realName?: string; username?: string }>;
  roles: Array<{ id: number; roleName?: string; roleCode?: string }>;
  departments: Array<{ id: number; deptName?: string; deptCode?: string }>;
  actions: Array<{ code: string; name: string; procedure?: string }>;
  procedures?: Array<{ name: string; label?: string }>;
  systemParams: Array<{ name: string; label: string }>;
}
export interface ApprovalDefinitionList {
  ready: boolean;
  message?: string;
  items: ApprovalDefinition[];
}
export interface ApprovalValidation {
  valid: boolean;
  errors: string[];
  warnings?: string[];
}

const root = '/meta-config/approval';

export async function fetchApprovalDefinitions(pageCode: string) {
  const { data, error } = await request<ApprovalDefinitionList>({ url: `${root}/definitions`, params: { pageCode } });
  if (error) throw error;
  if (!data) throw new Error('审批定义接口未返回数据');
  return data;
}

export async function fetchApprovalDefinition(flowId: number) {
  const { data, error } = await request<ApprovalDefinition>({ url: `${root}/definitions/${flowId}` });
  if (error) throw error;
  if (!data) throw new Error('未读取到审批定义');
  return data;
}

export async function fetchApprovalCatalog(pageCode: string) {
  const { data, error } = await request<ApprovalCatalog>({ url: `${root}/catalog`, params: { pageCode } });
  if (error) throw error;
  if (!data) throw new Error('审批字段与人员目录未返回数据');
  return data;
}

export async function saveApprovalDefinition(definition: ApprovalDefinition) {
  const { data, error } = await request<ApprovalDefinition>({ url: `${root}/definitions`, method: 'POST', data: definition });
  if (error) throw error;
  if (!data) throw new Error('保存接口未返回审批定义，请刷新核对后再操作');
  return data;
}

export async function validateApprovalDefinition(definition: ApprovalDefinition) {
  const { data, error } = await request<ApprovalValidation>({ url: `${root}/definitions/validate`, method: 'POST', data: definition });
  if (error) throw error;
  if (!data) throw new Error('校验接口未返回结果');
  return data;
}

export async function deleteApprovalDefinition(flowId: number) {
  const { error } = await request({ url: `${root}/definitions/${flowId}`, method: 'DELETE' });
  if (error) throw error;
}
