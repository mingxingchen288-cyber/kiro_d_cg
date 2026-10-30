/** C09 HTTP 接口的请求和响应类型。后端同名类型在 types.py 的"C09 HTTP 接口"一节。 */
import { ApprovalStatus, FieldValues, FrozenMark } from './command';
import { ErrorDetail } from './errors';
import {
  type Infer,
  type Schema,
  array,
  bool,
  code,
  dateTimeText,
  decimalText,
  int,
  json,
  key,
  lazy,
  literal,
  nullable,
  num,
  object,
  oneOf,
  optional,
  record,
  str,
  tagged,
  uuid
} from './schema';

const FieldType = literal('text', 'number', 'date', 'datetime', 'boolean');
const DetailMode = literal('tabs', 'stack');
const PageLayout = literal('single', 'masterDetail');
const ConfigType = literal(
  'entity',
  'page',
  'operation',
  'rule',
  'approvalFlow',
  'role',
  'menu',
  'dict',
  'lookup',
  'export'
);

// ---- 1. 共用类型

export const CurrentUser = object('CurrentUser', {
  userId: decimalText,
  username: str,
  displayName: str,
  departmentId: nullable(key)
});
export type CurrentUser = Infer<typeof CurrentUser>;

export const RoleRef = object('RoleRef', { code, name: str, admin: bool });
export type RoleRef = Infer<typeof RoleRef>;

export interface MenuItem {
  key: string;
  title: string;
  kind: 'group' | 'page' | 'config' | 'admin';
  pageCode?: string | null;
  children?: MenuItem[];
}
export const MenuItem: Schema<MenuItem> = object('MenuItem', {
  key: code,
  title: str,
  kind: literal('group', 'page', 'config', 'admin'),
  pageCode: optional(nullable(code)),
  children: optional(array(lazy(() => MenuItem)))
});

export const CompareResult = object('CompareResult', {
  value: nullable(decimalText),
  diff: nullable(decimalText),
  percent: nullable(decimalText)
});
export type CompareResult = Infer<typeof CompareResult>;

export const DataRow = object('DataRow', {
  rowKey: key,
  values: FieldValues,
  frozen: nullable(FrozenMark),
  compare: optional(nullable(record(CompareResult)))
});
export type DataRow = Infer<typeof DataRow>;

// ---- 2. identity

export const LoginRequest = object('LoginRequest', { username: str, password: str });
export type LoginRequest = Infer<typeof LoginRequest>;
export const LoginResponse = object('LoginResponse', {
  user: CurrentUser,
  roles: array(RoleRef),
  selectedRole: nullable(RoleRef),
  csrfToken: str
});
export type LoginResponse = Infer<typeof LoginResponse>;
export const SelectRoleRequest = object('SelectRoleRequest', { roleCode: code });
export const SelectRoleResponse = object('SelectRoleResponse', { selectedRole: RoleRef });
export type SelectRoleResponse = Infer<typeof SelectRoleResponse>;
export const MeResponse = object('MeResponse', {
  user: CurrentUser,
  role: nullable(RoleRef),
  menus: array(MenuItem),
  configVersion: int,
  csrfToken: str
});
export type MeResponse = Infer<typeof MeResponse>;

export const Account = object('Account', {
  userId: decimalText,
  username: str,
  displayName: str,
  departmentId: nullable(key),
  enabled: bool,
  roleCodes: array(code)
});
export type Account = Infer<typeof Account>;
export const AccountList = object('AccountList', { rows: array(Account), total: int });
export type AccountList = Infer<typeof AccountList>;
export const AccountCreate = object('AccountCreate', {
  username: str,
  displayName: str,
  departmentId: nullable(key),
  password: str,
  roleCodes: array(code)
});
export type AccountCreate = Infer<typeof AccountCreate>;
export const AccountUpdate = object('AccountUpdate', {
  displayName: str,
  departmentId: nullable(key),
  roleCodes: array(code),
  enabled: bool
});
export type AccountUpdate = Infer<typeof AccountUpdate>;
export const PasswordChange = object('PasswordChange', { password: str });
export const Department = object('Department', { departmentId: key, name: str, parentId: nullable(key) });
export const DepartmentList = object('DepartmentList', { items: array(Department) });
export type DepartmentList = Infer<typeof DepartmentList>;

// ---- 3. config

export const ConfigItemSummary = object('ConfigItemSummary', {
  type: ConfigType,
  key: code,
  name: str,
  version: int,
  updatedBy: decimalText,
  updatedAt: dateTimeText
});
export const ConfigItemList = object('ConfigItemList', { items: array(ConfigItemSummary) });
export type ConfigItemList = Infer<typeof ConfigItemList>;
export const ConfigItem = object('ConfigItem', { ...ConfigItemSummary.shape, content: record(json) });
export type ConfigItem = Infer<typeof ConfigItem>;
export const ConfigDraft = object('ConfigDraft', { type: ConfigType, key: code, name: str, content: record(json) });
export const ConfigSaveRequest = object('ConfigSaveRequest', { name: str, content: record(json) });
export type ConfigSaveRequest = Infer<typeof ConfigSaveRequest>;
export const ConfigSaveResponse = object('ConfigSaveResponse', { type: ConfigType, key: code, version: int });
export type ConfigSaveResponse = Infer<typeof ConfigSaveResponse>;
export const ConfigValidateRequest = object('ConfigValidateRequest', { items: array(ConfigDraft) });
export type ConfigValidateRequest = Infer<typeof ConfigValidateRequest>;
export const ConfigValidateResponse = object('ConfigValidateResponse', { ok: bool, errors: array(ErrorDetail) });
export type ConfigValidateResponse = Infer<typeof ConfigValidateResponse>;
export const WizardColumnsRequest = object('WizardColumnsRequest', { readView: optional(nullable(str)), table: str });
export type WizardColumnsRequest = Infer<typeof WizardColumnsRequest>;
export const WizardSequence = object('WizardSequence', { name: str, exists: bool });
export const WizardColumn = object('WizardColumn', { name: str, type: FieldType, label: str, inTable: bool });
export const WizardColumnsResponse = object('WizardColumnsResponse', {
  primaryKey: str,
  sequence: WizardSequence,
  columns: array(WizardColumn)
});
export type WizardColumnsResponse = Infer<typeof WizardColumnsResponse>;
export const SchemaColumnsRequest = object('SchemaColumnsRequest', { name: str });
export const SchemaColumn = object('SchemaColumn', { name: str, type: FieldType });
export const SchemaColumnsResponse = object('SchemaColumnsResponse', {
  objectType: nullable(literal('table', 'view')),
  primaryKey: nullable(str),
  columns: array(SchemaColumn)
});
export type SchemaColumnsResponse = Infer<typeof SchemaColumnsResponse>;
export const WizardGenerateRequest = object('WizardGenerateRequest', {
  parentMenu: code,
  pageCode: code,
  title: str,
  layout: PageLayout,
  detailMode: DetailMode,
  audit: bool,
  master: record(json),
  details: array(record(json))
});
export type WizardGenerateRequest = Infer<typeof WizardGenerateRequest>;

// ---- 4. queries-export

export const SortItem = object('SortItem', { colId: str, sort: literal('asc', 'desc') });
export type SortItem = Infer<typeof SortItem>;

/** 不写 `entity` 时属于主表；同一明细实体的条件由同一条明细行同时满足 */
export const AdvancedCondition = object('AdvancedCondition', {
  entity: optional(nullable(code)),
  group: optional(nullable(str)),
  logic: optional(nullable(literal('and', 'or'))),
  field: str,
  operator: str,
  value: optional(json)
});
export type AdvancedCondition = Infer<typeof AdvancedCondition>;
export const AdvancedQuery = object('AdvancedQuery', {
  op: literal('and', 'or'),
  conditions: array(AdvancedCondition)
});
export type AdvancedQuery = Infer<typeof AdvancedQuery>;

/** `sortModel`、`filterModel` 沿用 AG Grid 服务端行模型的格式；`startRow` 包含，`endRow` 不包含 */
export const ListRequest = object('ListRequest', {
  startRow: int,
  endRow: int,
  sortModel: optional(array(SortItem)),
  filterModel: optional(record(record(json))),
  advanced: optional(nullable(AdvancedQuery))
});
export type ListRequest = Infer<typeof ListRequest>;
export const ListResponse = object('ListResponse', { rows: array(DataRow), total: int, aggregates: FieldValues });
export type ListResponse = Infer<typeof ListResponse>;
export const ByKeysRequest = object('ByKeysRequest', { entity: code, rowKeys: array(key) });
export type ByKeysRequest = Infer<typeof ByKeysRequest>;
export const RowsResponse = object('RowsResponse', { rows: array(DataRow) });
export type RowsResponse = Infer<typeof RowsResponse>;
export const RecordResponse = object('RecordResponse', { master: DataRow, details: record(array(DataRow)) });
export type RecordResponse = Infer<typeof RecordResponse>;
export const LookupSearchFilter = object('LookupSearchFilter', { column: str, value: nullable(str) });
export const LookupSearchRequest = object('LookupSearchRequest', {
  keyword: optional(str),
  filter: optional(nullable(LookupSearchFilter)),
  startRow: int,
  endRow: int
});
export type LookupSearchRequest = Infer<typeof LookupSearchRequest>;
export const LookupRow = object('LookupRow', { values: FieldValues });
/** `keywordSearch` 为 false 时该 Lookup 不支持关键字搜索，前端不显示搜索框 */
export const LookupSearchResponse = object('LookupSearchResponse', {
  rows: array(LookupRow),
  total: int,
  keywordSearch: bool
});
export type LookupSearchResponse = Infer<typeof LookupSearchResponse>;
export const DictItem = object('DictItem', { value: str, label: str });
export type DictItem = Infer<typeof DictItem>;
export const DictResponse = object('DictResponse', { items: array(DictItem) });
export type DictResponse = Infer<typeof DictResponse>;
export const PersonalColumn = object('PersonalColumn', {
  field: str,
  width: nullable(int),
  pinned: nullable(literal('left', 'right')),
  hide: bool
});
export type PersonalColumn = Infer<typeof PersonalColumn>;
export const PersonalGrid = object('PersonalGrid', { columns: array(PersonalColumn) });
export type PersonalGrid = Infer<typeof PersonalGrid>;
/** `grids` 的键为 `master` 或明细实体；保存时只含要替换的部分，没有保存过的部分不出现 */
export const PersonalConfig = object('PersonalConfig', {
  grids: optional(nullable(record(PersonalGrid))),
  detailMode: optional(nullable(DetailMode))
});
export type PersonalConfig = Infer<typeof PersonalConfig>;
export const ExportItem = object('ExportItem', { exportCode: code, name: str });
export const ExportList = object('ExportList', { items: array(ExportItem) });
export type ExportList = Infer<typeof ExportList>;
export const PageExportRequest = object('PageExportRequest', {
  mode: literal('page'),
  request: ListRequest,
  columns: array(str)
});
export const ConfigExportRequest = object('ConfigExportRequest', {
  mode: literal('config'),
  exportCode: code,
  scope: literal('current', 'all'),
  request: ListRequest
});
export const ExportRequest = tagged('mode', { page: PageExportRequest, config: ConfigExportRequest });
export type ExportRequest = Infer<typeof ExportRequest>;

// ---- 6. approval

export const UserBrief = object('UserBrief', { userId: decimalText, displayName: str });
export const SourceRef = object('SourceRef', { entity: code, recordKey: key, label: nullable(str) });
export const ApprovalSummary = object('ApprovalSummary', {
  approvalId: decimalText,
  page: code,
  pageTitle: str,
  operation: code,
  operationLabel: str,
  source: SourceRef,
  applicant: UserBrief,
  submittedAt: dateTimeText,
  status: ApprovalStatus,
  level: int
});
export type ApprovalSummary = Infer<typeof ApprovalSummary>;
export const ApprovalList = object('ApprovalList', { rows: array(ApprovalSummary), total: int });
export type ApprovalList = Infer<typeof ApprovalList>;
export const StepMember = object('StepMember', {
  type: literal('user', 'role'),
  id: key,
  name: str,
  // skipped：或签节点有人通过后，同一节点其余还没处理的审批人（C09 v12）
  status: literal('pending', 'passed', 'rejected', 'withdrawn', 'skipped'),
  processedBy: nullable(UserBrief),
  processedAt: nullable(dateTimeText),
  comment: nullable(str)
});
export type StepMember = Infer<typeof StepMember>;
export const ApprovalStep = object('ApprovalStep', {
  level: int,
  flow: code,
  flowName: str,
  node: str,
  mode: literal('or', 'and'),
  status: literal('passed', 'pending', 'rejected', 'upcoming', 'withdrawn'),
  members: array(StepMember)
});
export type ApprovalStep = Infer<typeof ApprovalStep>;
export const ViewCell = object('ViewCell', { before: nullable(oneOf(str, bool)), after: nullable(oneOf(str, bool)) });
export const RowRef = object('RowRef', { key });
export const ViewRow = object('ViewRow', {
  op: literal('modify', 'add', 'delete', 'none'),
  cells: array(ViewCell),
  flows: optional(nullable(array(code))),
  ref: optional(nullable(RowRef)),
  checked: optional(nullable(bool)),
  missing: optional(nullable(literal(true)))
});
export const ViewMasterTable = object('ViewMasterTable', {
  key: code,
  title: str,
  columns: array(str),
  rows: array(ViewRow)
});
export const ViewDetailTable = object('ViewDetailTable', {
  key: code,
  title: str,
  columns: array(str),
  rows: array(ViewRow)
});
export const ViewAffectedTable = object('ViewAffectedTable', {
  flow: code,
  key: code,
  title: str,
  selection: literal('checked', 'all'),
  editable: bool,
  columns: array(str),
  rows: array(ViewRow)
});
export const ApprovalView = object('ApprovalView', {
  master: ViewMasterTable,
  details: array(ViewDetailTable),
  affected: array(ViewAffectedTable)
});
export const ApprovalActions = object('ApprovalActions', { canPass: bool, canReject: bool, canWithdraw: bool });
/** 人工参数，格式同 C06 7.1 的 `params` */
export const FlowParam = object('FlowParam', {
  name: str,
  label: str,
  type: literal('string', 'number', 'boolean', 'date'),
  source: literal('manual', 'constant', 'expression'),
  required: bool,
  level: optional(nullable(int)),
  value: optional(json)
});
export const ApprovalDetail = object('ApprovalDetail', {
  approvalId: decimalText,
  status: ApprovalStatus,
  page: code,
  pageTitle: str,
  operation: code,
  operationLabel: str,
  source: SourceRef,
  applicant: UserBrief,
  submittedAt: dateTimeText,
  currentLevel: int,
  steps: array(ApprovalStep),
  view: ApprovalView,
  fingerprint: str,
  params: array(FlowParam),
  actions: ApprovalActions,
  /** 已结束的审批没有保存结束那一刻的修改内容时为 true，`view` 的各表为空（C06 7.6） */
  viewUnsaved: optional(nullable(literal(true)))
});
export type ApprovalDetail = Infer<typeof ApprovalDetail>;
export const CheckedRow = object('CheckedRow', { flow: code, block: code, key });
export const PreviewRequest = object('PreviewRequest', { checkedRows: optional(array(CheckedRow)) });
export type PreviewRequest = Infer<typeof PreviewRequest>;
export const PreviewResponse = object('PreviewResponse', { view: ApprovalView, fingerprint: str });
export type PreviewResponse = Infer<typeof PreviewResponse>;
export const PassRequest = object('PassRequest', {
  requestKey: uuid,
  fingerprint: str,
  checkedRows: optional(array(CheckedRow)),
  comment: optional(nullable(str)),
  params: optional(record(json))
});
export type PassRequest = Infer<typeof PassRequest>;
export const RejectRequest = object('RejectRequest', { requestKey: uuid, comment: optional(nullable(str)) });
export type RejectRequest = Infer<typeof RejectRequest>;
export const WithdrawRequest = object('WithdrawRequest', { requestKey: uuid, comment: optional(nullable(str)) });
export type WithdrawRequest = Infer<typeof WithdrawRequest>;

// ---- 7. delivery

export const InboxItem = object('InboxItem', {
  deliveryId: uuid,
  title: str,
  body: str,
  link: nullable(str),
  createdAt: dateTimeText,
  read: bool
});
export const InboxList = object('InboxList', { rows: array(InboxItem), total: int, unread: int });
export type InboxList = Infer<typeof InboxList>;
export const DeliveryRow = object('DeliveryRow', {
  deliveryId: uuid,
  recipient: decimalText,
  status: literal('pending', 'sent', 'failed', 'abandoned'),
  attempts: int,
  nextRetryAt: nullable(dateTimeText),
  lastError: nullable(str)
});
export const DeliveryList = object('DeliveryList', { rows: array(DeliveryRow), total: int });
export type DeliveryList = Infer<typeof DeliveryList>;

// ---- 7a. 命令审查

export const SqlTrace = object('SqlTrace', {
  text: str,
  binds: record(json),
  ms: num,
  rows: nullable(int),
  error: nullable(str)
});
export const CommandLog = object('CommandLog', {
  requestKey: uuid,
  user: str,
  page: nullable(code),
  operation: code,
  result: literal('saved', 'rejected', 'failed'),
  errorCode: nullable(str),
  message: nullable(str),
  startedAt: dateTimeText,
  durationMs: num,
  sqlCount: int,
  sqlMs: num,
  sql: array(SqlTrace)
});
export const CommandReviewList = object('CommandReviewList', { enabled: bool, rows: array(CommandLog), total: int });
export type CommandReviewList = Infer<typeof CommandReviewList>;
export const CommandReviewToggle = object('CommandReviewToggle', { enabled: bool });
export type CommandReviewToggle = Infer<typeof CommandReviewToggle>;

// ---- 8. assembly

export const HealthResponse = object('HealthResponse', {
  status: literal('ok', 'starting'),
  coreVersion: optional(nullable(str)),
  configVersion: optional(nullable(int))
});
export type HealthResponse = Infer<typeof HealthResponse>;
