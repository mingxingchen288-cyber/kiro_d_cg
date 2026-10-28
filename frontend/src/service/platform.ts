/**
 * 平台后端的 HTTP 客户端（C09）：会话 Cookie 由浏览器带上；POST 请求带 X-CSRF-Token；错误体按 C03 解析。
 * 目前用到登录、/api/me、页面视图、列表、单据加载和命令。
 */
import { sessionStg } from '@/utils/storage';
import { getServiceBaseURL } from '@/utils/service';

const isHttpProxy = import.meta.env.DEV && import.meta.env.VITE_HTTP_PROXY === 'Y';
const { baseURL } = getServiceBaseURL(import.meta.env, isHttpProxy);

/** C03 的错误体 */
export interface PlatformErrorBody {
  code: string;
  message: string;
  details: Array<Record<string, string | null>>;
}

export class PlatformRequestError extends Error {
  constructor(
    readonly status: number,
    readonly body: PlatformErrorBody
  ) {
    super(body.message);
  }
}

/** 登录响应和 /api/me 中的 csrfToken，存在会话存储里，与旧外壳判断是否登录用的 token 是同一项 */
export function setCsrfToken(token: string) {
  sessionStg.set('token', token);
}

function csrfToken() {
  return sessionStg.get('token') || '';
}

export async function platformRequest<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method === 'POST') {
    headers['Content-Type'] = 'application/json';
    headers['X-CSRF-Token'] = csrfToken();
  }
  const response = await fetch(`${baseURL}${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    throw new PlatformRequestError(response.status, data as PlatformErrorBody);
  }
  return data as T;
}

// ---- C09 第 2 节 identity

export interface CurrentUser {
  userId: string;
  username: string;
  displayName: string;
  departmentId: string | null;
}

export interface RoleRef {
  code: string;
  name: string;
  admin: boolean;
}

export interface LoginResponse {
  user: CurrentUser;
  roles: RoleRef[];
  selectedRole: RoleRef | null;
  csrfToken: string;
}

export interface MeResponse {
  user: CurrentUser;
  role: RoleRef | null;
  menus: unknown[];
  configVersion: number;
  csrfToken: string;
}

export function login(username: string, password: string) {
  return platformRequest<LoginResponse>('POST', '/api/auth/login', { username, password });
}

export function me() {
  return platformRequest<MeResponse>('GET', '/api/me');
}

// ---- C05 页面视图、C09 第 4 节列表

export type FieldValue = string | boolean | null;

export interface ViewField {
  name: string;
  label: string;
  type: 'text' | 'number' | 'date' | 'datetime' | 'boolean';
  scale: number | null;
  calculated: boolean;
  visible: boolean;
  editable: boolean;
  required: boolean;
  width: number | null;
  pinned: 'left' | 'right' | null;
}

export interface ViewMaster {
  entity: string;
  primaryKey: string;
  fields: ViewField[];
}

export interface ViewDetail {
  entity: string;
  title: string;
  primaryKey: string;
  parentKey: string;
  fields: ViewField[];
}

export interface PageView {
  pageCode: string;
  title: string;
  version: number;
  layout: 'single' | 'masterDetail';
  detailMode: 'tabs' | 'stack';
  saveOperation: string;
  master: ViewMaster;
  details: ViewDetail[];
  systemButtons: string[];
}

export interface DataRow {
  rowKey: string;
  values: Record<string, FieldValue>;
  frozen: { approvalId: string } | null;
}

/** 单据加载：主表行和每个明细实体的行 */
export interface RecordResponse {
  master: DataRow;
  details: Record<string, DataRow[]>;
}

export interface ListRequest {
  startRow: number;
  endRow: number;
  sortModel: Array<{ colId: string; sort: 'asc' | 'desc' }>;
}

export function pageView(pageCode: string) {
  return platformRequest<PageView>('GET', `/api/pages/${pageCode}/view`);
}

export function listRows(pageCode: string, request: ListRequest) {
  return platformRequest<{ rows: DataRow[]; total: number }>('POST', `/api/pages/${pageCode}/rows`, request);
}

export function loadRecord(pageCode: string, recordKey: string) {
  return platformRequest<RecordResponse>(
    'GET',
    `/api/pages/${encodeURIComponent(pageCode)}/records/${encodeURIComponent(recordKey)}`
  );
}

// ---- C02 命令与结果

export interface MasterModify {
  op: 'modify';
  rowKey: string;
  changes: Record<string, FieldValue>;
}

/** 主表不改、只改明细 */
export interface MasterNone {
  op: 'none';
  rowKey: string;
}

export interface DetailModify {
  entity: string;
  op: 'modify';
  rowKey: string;
  changes: Record<string, FieldValue>;
}

export interface DocumentPatch {
  entity: string;
  master: MasterModify | MasterNone;
  details: DetailModify[];
}

export interface Command {
  requestKey: string;
  page: string;
  operation: string;
  documents: DocumentPatch[];
  params: Record<string, never>;
}

export interface CommandResult {
  requestKey: string;
  outcome: 'saved' | 'unchanged' | 'approvalSubmitted' | 'approvalProcessed';
  rows: Array<{ entity: string; rowKey: string; values: Record<string, FieldValue>; frozen: unknown }>;
}

export function runCommand(command: Command) {
  return platformRequest<CommandResult>('POST', '/api/commands', command);
}
