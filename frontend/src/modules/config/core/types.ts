/**
 * C06 配置项 `content` 的前端类型（v17）。字段名与后端 `contracts/types.py` 的 wire 写法（camelCase）相同；
 * 可以省略的字段按 C06 第 1.1 节标为可选。配置界面只读写这些结构，校验和保存由后端 config 负责。
 */

export type ConfigType =
  | 'entity'
  | 'page'
  | 'operation'
  | 'rule'
  | 'approvalFlow'
  | 'role'
  | 'menu'
  | 'dict'
  | 'lookup'
  | 'export';

export const CONFIG_TYPE_LABELS: Record<ConfigType, string> = {
  entity: '实体',
  page: '页面',
  operation: '操作',
  rule: '规则',
  approvalFlow: '审批流',
  role: '角色',
  menu: '菜单',
  dict: '字典',
  lookup: 'Lookup',
  export: '导出'
};

export type FieldType = 'text' | 'number' | 'date' | 'datetime' | 'boolean';
export type CompareOp = 'eq' | 'ne' | 'gt' | 'ge' | 'lt' | 'le' | 'like' | 'in' | 'isNull' | 'isNotNull';
export type Logic = 'AND' | 'OR';
export type RowOp = 'add' | 'modify' | 'delete';

// ---- 2. entity

export type DefaultValue =
  | { type: 'static'; value: string }
  | {
      type: 'builtin';
      value: 'currentUserId' | 'currentUserName' | 'currentDeptId' | 'currentDeptName' | 'currentRoleCode' | 'currentTime';
    }
  | { type: 'options'; value: string[] };

export type CompareFormat = 'value' | 'percent' | 'both';
export type FieldCompare =
  | { mode: 'field'; field: string; format: CompareFormat }
  | { mode: 'query'; source: string; keys: Array<{ current: string; compare: string }>; field: string; format: CompareFormat };

export interface EntityField {
  name: string;
  column: string | null;
  label: string;
  type: FieldType;
  scale?: number | null;
  /** 千分位（C06 第 2 节）：数值显示时整数部分每三位加英文逗号；省略时为 false */
  grouping?: boolean;
  source: 'erp' | 'own';
  role: 'input' | 'calculated' | 'system';
  default?: DefaultValue | null;
  compare?: FieldCompare | null;
}

export interface FieldFlags {
  visible?: boolean | null;
  editable?: boolean | null;
  required?: boolean | null;
}

export interface RequiredCondition {
  logic: Logic;
  conditions: Array<{ field: string; op: 'eq' | 'ne' | 'isNull' | 'isNotNull'; value?: string | null }>;
}

export interface ApprovalRequiredRule {
  fields: string[];
  when?: RequiredCondition | null;
  sourcePages: string[];
}

export interface EntityContent {
  table: string;
  primaryKey: string;
  freezable: boolean;
  readView?: string | null;
  erpRow?: { column: string; value: string; localValue: string } | null;
  /** 写入修改人的列（表中的列名，不是字段），新增、修改时由写入管道写当前用户的登录名（C06 第 2 节） */
  updatedByColumn?: string | null;
  fields: EntityField[];
  details?: Array<{ entity: string; parentKey: string }>;
  fieldDefaults?: Record<string, FieldFlags>;
  approvalRequired?: ApprovalRequiredRule[];
}

// ---- 3. page

export interface LookupSetting {
  code: string;
  fill: Record<string, string>;
  multiple?: boolean;
  filter?: { column: string; from: 'row' | 'cell'; field?: string | null } | null;
  fillBack?: boolean;
}

export interface FieldSetting extends FieldFlags {
  width?: number | null;
  pinned?: 'left' | 'right' | null;
  dictType?: string | null;
  /** 字典下拉中可以填写字典以外的值（C06 第 3 节，旧系统"下拉（可填写）"）；省略时为 false */
  dictFreeText?: boolean;
  lookup?: LookupSetting | null;
  /** 汇总行求和（C06 第 3 节），只能用于数值字段 */
  aggregate?: 'sum' | null;
  /** 查询（C06 v23 第 3 节）：为 true 时高级查询对话框一打开就列出这个字段的条件 */
  searchable?: boolean | null;
}

export interface ButtonConfig {
  action: string;
  label: string;
  operation?: string | null;
  requiresSelection?: boolean | null;
}

export interface GridOptions {
  sideBar: boolean;
  cellSelection: boolean;
  groupBy: string[];
}

export interface FormCell {
  field: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PageArea {
  entity: string;
  fields?: Record<string, FieldSetting>;
  buttons?: ButtonConfig[];
  grid: GridOptions;
  formLayout?: FormCell[];
}

export interface PageDetailArea extends PageArea {
  title: string;
}

export interface PageContent {
  title: string;
  layout: 'single' | 'masterDetail';
  detailMode: 'tabs' | 'stack';
  audit: boolean;
  /** 为 null 时是只读页面（C06 v29 第 3 节，例如审计追踪） */
  saveOperation: string | null;
  master: PageArea;
  details?: PageDetailArea[];
}

// ---- 4. operation、6. 通用动作

export type ActionStep =
  | { action: 'recalculate'; target: 'source' | 'targets' }
  | {
      action: 'updateTargets';
      targets: Array<{
        entity: string;
        detailEntity?: string | null;
        match?: Record<string, string>;
        fieldMapping: Array<{ from: string; to: string }>;
      }>;
    }
  | {
      action: 'updateRecords';
      find:
        | { kind: 'relationKey'; entity: string; targetKey: string; sourceKey: string; rows: 'all' }
        | {
            kind: 'sql';
            entity: string;
            sql: string;
            binds?: Record<string, string>;
            recordKeyColumn: string;
            rowKeyColumns?: string[];
            labelColumn?: string | null;
            displayColumns?: string[];
          };
      fieldMapping: Array<{ from: string; to: string }>;
    }
  /** C06 v18：替换选中单据的一个明细，SQL 的每一行新增为一行，列名就是字段名；binds 只引用主表字段 */
  | { action: 'replaceDetails'; entity: string; sql: string; binds?: Record<string, string> }
  /** C06 v18：不看选中行，SQL 执行一次，每一行是一条要改的记录和新值 */
  | { action: 'updateRows'; entity: string; sql: string; recordKeyColumn: string; rowKeyColumns?: string[] }
  | { action: 'escapeHatch'; operation: string };

export interface OperationContent {
  label: string;
  kind: 'save' | 'action' | 'escapeHatch';
  writableFields?: Record<string, string[]>;
  impact?: string[];
  actions?: ActionStep[];
  rowNotFound?: 'skip' | 'reject';
  propagation: 'continue' | 'end';
  procedure?: string | null;
  writes?: Record<string, string[]>;
}

// ---- 5. rule

export interface RuleConditionItem {
  source: 'row' | 'master';
  field: string;
  op: CompareOp;
  value?: unknown;
}

export interface VisualCondition {
  logic: Logic;
  conditions: RuleConditionItem[];
}

export type Condition = string | VisualCondition;

export interface CellStyle {
  backgroundColor?: string;
  color?: string;
  fontWeight?: string;
  fontStyle?: string;
}

export interface RuleContent {
  layer: 'entity' | 'operation' | 'page';
  target: string;
  category: 'calc' | 'validate' | 'ui';
  field: string | null;
  order: number;
  when?: Condition | null;
  expression?: string | null;
  branches?: Array<{ when?: Condition | null; expression: string }> | null;
  level?: 'reject' | 'prompt' | null;
  message?: string | null;
  effect?: { editable?: boolean | null; required?: boolean | null; rowStyle?: CellStyle | null; cellStyle?: CellStyle | null } | null;
}

// ---- 7. approvalFlow

export type Approver =
  | { type: 'user'; userId: string }
  | { type: 'role'; role: string }
  | { type: 'sql'; sql: string; binds?: Record<string, string> };

export interface FlowNode {
  name: string;
  conditionType: 'always' | 'sql';
  condition?: string | null;
  department?: string | null;
  approvers: Approver[];
  mode: 'or' | 'and';
  enabled?: boolean;
}

export interface FlowLevel {
  level: number;
  nodes: FlowNode[];
}

export interface FreezeItem {
  table: string;
  condition: string;
  enabled?: boolean;
}

export interface DisplayColumn {
  field: string;
  label: string;
  precision?: number | null;
  width?: number | null;
  targetColumn?: string | null;
}

export interface FieldWrite {
  column: string;
  value: string;
}

export type BlockAction =
  | { action: 'updateFields'; fields: FieldWrite[] }
  | { action: 'insertRows'; table: string; fields: FieldWrite[] }
  | { action: 'deleteRows' }
  | { action: 'escapeHatch'; operation: string };

export interface DisplayBlock {
  key: string;
  title: string;
  region: 'master' | 'detail' | 'affected';
  source: string;
  condition?: string | null;
  targetTable?: string | null;
  keyColumn?: string | null;
  columns: DisplayColumn[];
  selection?: 'checked' | 'all' | 'hidden' | null;
  actions?: BlockAction[];
}

export interface FlowParam {
  name: string;
  label: string;
  type: 'string' | 'number' | 'boolean' | 'date';
  source: 'manual' | 'constant' | 'expression';
  required: boolean;
  level?: number | null;
  value?: unknown;
}

export type NotifyTarget = 'levelApprovers' | 'applicant' | { users: string[] } | { role: string };

export interface NotifyRule {
  event: 'submitted' | 'levelEntered' | 'passed' | 'rejected' | 'withdrawn';
  to: NotifyTarget;
}

export interface ApprovalFlowContent {
  page: string;
  order: number;
  enabled?: boolean;
  operations: Record<string, RowOp[]>;
  levels: FlowLevel[];
  freeze?: FreezeItem[];
  display?: DisplayBlock[];
  params?: FlowParam[];
  propagation?: 'end';
  notify?: NotifyRule[];
}

// ---- 8. role

export interface RowConditionItem {
  field: string;
  fieldLabel: string;
  op: CompareOp;
  valueType: 'static' | 'dynamic';
  value?: unknown;
}

export interface VisualRowPolicy {
  mode: 'visual';
  logic: Logic;
  conditions: RowConditionItem[];
  sql: string;
}

export interface RolePage {
  buttons?: string[];
  rows?: VisualRowPolicy | string | null;
  columns?: Record<string, Record<string, FieldFlags>>;
}

export interface RoleContent {
  name: string;
  admin: boolean;
  pages?: Record<string, RolePage>;
}

// ---- 9. menu、dict、lookup、export

export interface MenuNode {
  key: string;
  title: string;
  kind: 'group' | 'page' | 'config' | 'admin';
  pageCode?: string | null;
  /** 菜单图标（C06 v26），Iconify 图标名，例如 mdi:calculator-variant；省略时外壳用默认图标 */
  icon?: string | null;
  children?: MenuNode[];
}

export interface MenuContent {
  items: MenuNode[];
}

export interface DictContent {
  items: Array<{ value: string; label: string; order: number }>;
}

/** Lookup 的显示列写成对象时（C06 第 9 节）：`label` 为对话框中的列标题，`width` 为列宽，省略时分别为列名、平分 */
export interface LookupColumnItem {
  column: string;
  label?: string | null;
  width?: number | null;
}

export interface LookupContent {
  table: string;
  /** 列名，或带标题、宽度的对象 */
  columns: Array<string | LookupColumnItem>;
  keywordColumns: string[];
  orderBy?: string | null;
}

export interface ExportColumn {
  field: string;
  header: string;
}

export interface ExportContent {
  page: string;
  name: string;
  fileName: string;
  font?: string;
  detailLayout?: 'perMaster' | 'perDetail';
  master: { sheet: string; sql: string; keyColumn: string; columns: ExportColumn[] };
  details?: Array<{ sheet: string; sql: string; linkColumn: string; columns: ExportColumn[] }>;
}

export interface ContentByType {
  entity: EntityContent;
  page: PageContent;
  operation: OperationContent;
  rule: RuleContent;
  approvalFlow: ApprovalFlowContent;
  role: RoleContent;
  menu: MenuContent;
  dict: DictContent;
  lookup: LookupContent;
  export: ExportContent;
}
