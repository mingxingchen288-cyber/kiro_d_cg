/**
 * C09 的每个接口：方法、路径、请求和响应类型。前端模块经 `createPlatformApi(shell.http)` 调用，不自己拼路径。
 * 路径中的参数都经 encodeURIComponent。
 */
import type { Command, CommandResult } from './command';
import type {
  Account,
  AccountCreate,
  AccountList,
  AccountUpdate,
  ApprovalDetail,
  ApprovalList,
  ByKeysRequest,
  CommandReviewList,
  ConfigItem,
  ConfigItemList,
  ConfigSaveRequest,
  ConfigSaveResponse,
  ConfigValidateRequest,
  ConfigValidateResponse,
  DeliveryList,
  DepartmentList,
  DictResponse,
  ExportList,
  ExportRequest,
  HealthResponse,
  InboxList,
  ListRequest,
  ListResponse,
  LoginResponse,
  LookupSearchRequest,
  LookupSearchResponse,
  MeResponse,
  PassRequest,
  PersonalConfig,
  PreviewRequest,
  PreviewResponse,
  RecordResponse,
  RejectRequest,
  RowsResponse,
  SchemaColumnsResponse,
  SelectRoleResponse,
  WithdrawRequest,
  WizardColumnsRequest,
  WizardColumnsResponse,
  WizardGenerateRequest
} from './http';
import type { PageView } from './page-view';
import type { RulesPack } from './rules';
import type { HttpClient, HttpRequestOptions } from './shell';

const e = encodeURIComponent;

/** 后台请求（C09 第 1 节）：配置变更后重新读取页面视图和规则包、读取未读数等 */
const BACKGROUND: HttpRequestOptions = { background: true };

export function createPlatformApi(http: HttpClient) {
  const bg = (background?: boolean) => (background ? BACKGROUND : undefined);
  return {
    // ---- 2. identity
    login: (username: string, password: string) => http.post<LoginResponse>('/api/auth/login', { username, password }),
    selectRole: (roleCode: string) => http.post<SelectRoleResponse>('/api/auth/role', { roleCode }),
    logout: () => http.post<void>('/api/auth/logout'),
    me: (background?: boolean) => http.get<MeResponse>('/api/me', bg(background)),
    listAccounts: (query: { keyword?: string; startRow: number; endRow: number }) =>
      http.get<AccountList>('/api/admin/accounts', { query }),
    createAccount: (body: AccountCreate) => http.post<Account>('/api/admin/accounts', body),
    updateAccount: (userId: string, body: AccountUpdate) => http.put<Account>(`/api/admin/accounts/${e(userId)}`, body),
    changePassword: (userId: string, password: string) =>
      http.post<void>(`/api/admin/accounts/${e(userId)}/password`, { password }),
    departments: () => http.get<DepartmentList>('/api/admin/departments'),

    // ---- 3. config
    pageView: (pageCode: string, background?: boolean) =>
      http.get<PageView>(`/api/pages/${e(pageCode)}/view`, bg(background)),
    rulesPack: (packId: string, version: number, background?: boolean) =>
      http.get<RulesPack>(`/api/rules-packs/${e(packId)}/${version}`, bg(background)),
    configItems: (type?: string) => http.get<ConfigItemList>('/api/config/items', { query: { type } }),
    configItem: (type: string, key: string) => http.get<ConfigItem>(`/api/config/items/${e(type)}/${e(key)}`),
    saveConfigItem: (type: string, key: string, body: ConfigSaveRequest) =>
      http.put<ConfigSaveResponse>(`/api/config/items/${e(type)}/${e(key)}`, body),
    deleteConfigItem: (type: string, key: string) => http.delete<void>(`/api/config/items/${e(type)}/${e(key)}`),
    validateConfig: (body: ConfigValidateRequest) => http.post<ConfigValidateResponse>('/api/config/validate', body),
    wizardColumns: (body: WizardColumnsRequest) => http.post<WizardColumnsResponse>('/api/config/wizard/columns', body),
    schemaColumns: (name: string) => http.post<SchemaColumnsResponse>('/api/config/schema/columns', { name }),
    wizardGenerate: (body: WizardGenerateRequest) => http.post<unknown>('/api/config/wizard/generate', body),

    // ---- 4. queries-export
    listRows: (pageCode: string, body: ListRequest) => http.post<ListResponse>(`/api/pages/${e(pageCode)}/rows`, body),
    rowsByKeys: (pageCode: string, body: ByKeysRequest) =>
      http.post<RowsResponse>(`/api/pages/${e(pageCode)}/rows/by-keys`, body),
    loadRecord: (pageCode: string, recordKey: string) =>
      http.get<RecordResponse>(`/api/pages/${e(pageCode)}/records/${e(recordKey)}`),
    lookupSearch: (lookupCode: string, body: LookupSearchRequest) =>
      http.post<LookupSearchResponse>(`/api/lookups/${e(lookupCode)}/search`, body),
    dict: (dictType: string) => http.get<DictResponse>(`/api/dicts/${e(dictType)}`),
    personal: (pageCode: string) => http.get<PersonalConfig>(`/api/pages/${e(pageCode)}/personal`),
    savePersonal: (pageCode: string, body: PersonalConfig) =>
      http.put<PersonalConfig>(`/api/pages/${e(pageCode)}/personal`, body),
    exports: (pageCode: string) => http.get<ExportList>(`/api/pages/${e(pageCode)}/exports`),
    exportFile: (pageCode: string, body: ExportRequest) => http.download(`/api/pages/${e(pageCode)}/export`, body),

    // ---- 5. 命令
    runCommand: (command: Command) => http.post<CommandResult>('/api/commands', command),

    // ---- 6. approval
    approvals: (query: { box: 'todo' | 'mine'; startRow: number; endRow: number }) =>
      http.get<ApprovalList>('/api/approvals', { query }),
    approvalDetail: (approvalId: string) => http.get<ApprovalDetail>(`/api/approvals/${e(approvalId)}`),
    approvalPreview: (approvalId: string, body: PreviewRequest) =>
      http.post<PreviewResponse>(`/api/approvals/${e(approvalId)}/preview`, body),
    passApproval: (approvalId: string, body: PassRequest) =>
      http.post<CommandResult>(`/api/approvals/${e(approvalId)}/pass`, body),
    rejectApproval: (approvalId: string, body: RejectRequest) =>
      http.post<CommandResult>(`/api/approvals/${e(approvalId)}/reject`, body),
    withdrawApproval: (approvalId: string, body: WithdrawRequest) =>
      http.post<CommandResult>(`/api/approvals/${e(approvalId)}/withdraw`, body),

    // ---- 7. delivery
    inbox: (query: { unread?: boolean; startRow: number; endRow: number }, background?: boolean) =>
      http.get<InboxList>('/api/inbox', { query, background }),
    markRead: (deliveryId: string) => http.post<void>(`/api/inbox/${e(deliveryId)}/read`),
    deliveries: (query: { status?: string; startRow: number; endRow: number }) =>
      http.get<DeliveryList>('/api/admin/deliveries', { query }),
    requeueDelivery: (deliveryId: string) => http.post<void>(`/api/admin/deliveries/${e(deliveryId)}/requeue`),

    // ---- 7a. 命令审查
    commandReview: (query: { startRow: number; endRow: number; user?: string; result?: string }) =>
      http.get<CommandReviewList>('/api/admin/command-review', { query }),
    setCommandReview: (enabled: boolean) => http.put<void>('/api/admin/command-review', { enabled }),

    // ---- 8. assembly
    health: () => http.get<HealthResponse>('/health')
  };
}

export type PlatformApi = ReturnType<typeof createPlatformApi>;
