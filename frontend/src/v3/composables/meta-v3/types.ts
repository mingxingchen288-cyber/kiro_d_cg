export type RawRules = string | unknown;

export type PageRule = {
  id?: number;
  pageCode?: string;
  componentKey?: string;
  ruleType?: string;
  rules?: RawRules;
  sortOrder?: number;
};

export type PageComponentWithRules = Api.Metadata.PageComponent & {
  rules?: PageRule[];
  children?: PageComponentWithRules[];
};

export type ColumnOverrideRule = {
  columnId?: number;
  columnName?: string;
  width?: number;
  visible?: boolean;
  editable?: boolean;
  searchable?: boolean;
  required?: boolean;
  cellEditor?: string;
  cellEditorParams?: Record<string, any>;
  /** 聚合函数：sum 表示底部汇总求和 */
  aggFunc?: 'sum';
  /** 显示精度（小数位数），仅影响显示，不影响计算 */
  precision?: number | null;
  /** 取整方式：round=四舍五入, ceil=向上取整, floor=向下取整 */
  roundMode?: 'round' | 'ceil' | 'floor';
  /** 是否显示千分位分隔符，仅影响显示，不影响计算 */
  useGrouping?: boolean;
  rulesConfig?: {
    compare?: {
      enabled: boolean;
      mode?: 'viewField' | 'dynamicQuery';
      compareField: string;
      format?: 'value' | 'percent' | 'both';
      upColor?: string;
      downColor?: string;
    };
    [key: string]: any;
  };
};

/**
 * Lookup 弹窗规则配置
 *
 * 筛选相关字段说明：
 * - filterField: 从"当前行数据"取哪个字段的值作为筛选值
 *   生效场景：filterValueFrom 没写或为 'row'
 *   例：filterField: "id" → 用当前行的 rowData.id 作为筛选值
 *
 * - filterColumn: 弹窗数据源里要过滤的列名（SQL 中的列名）
 *   例：filterColumn: "GOODSID" → 最终会拼成 AND GOODSID = <filterValue>
 *
 * - filterValueFrom: 筛选值来源
 *   'row': 用 rowData[filterField]
 *   'cell': 用你点击的单元格的值（不需要 filterField）
 */
export type LookupRuleConfig = {
  columnName: string;
  lookupCode: string;
  mapping: Record<string, string>;
  /** 是否允许弹窗多选，回填时同字段用逗号分隔 */
  multiple?: boolean;
  /** 是否禁止回填（仅查看模式） */
  noFillback?: boolean;
  /** 从当前行取哪个字段的值作为筛选值，生效于 filterValueFrom='row' 或未配置时 */
  filterField?: string;
  /** 弹窗数据源的筛选列名（SQL列名），如 "GOODSID" */
  filterColumn?: string;
  /** 筛选值来源：'row' 用行数据字段，'cell' 用点击单元格的值 */
  filterValueFrom?: 'row' | 'cell';
};

export type RoleBindingRule = {
  role: string;
  masterKey?: string;
  detailKey?: string;
};

export type SplitLayoutConfig = {
  defaultSize?: number;
  min?: number;
  max?: number;
};

export type GridOptionsRule = {
  sideBar?: boolean | Record<string, any>;
  enableSidebar?: boolean;
  cellSelection?: boolean | Record<string, any>;
  rowModelType?: 'clientSide' | 'serverSide';
  cacheBlockSize?: number;
  maxBlocksInCache?: number;
  /** SSRM: 最大并发请求数 */
  maxConcurrentDatasourceRequests?: number;
  /** SSRM: 请求防抖毫秒数 */
  blockLoadDebounceMillis?: number;
  groupBy?: string[];
  groupColumnName?: string;
  groupDefaultExpanded?: number;
  autoSizeColumns?: boolean;
  autoSizeMode?: 'fitCellContents' | 'fitGridWidth';
};

export type RelationRule = {
  masterKey?: string;
  detailKey?: string;
  detailType?: string;
  splitConfig?: SplitLayoutConfig;
};

/** 统一按钮规则项（支持 position 区分显示位置） */
export type ButtonItemRule = {
  type?: 'action' | 'separator' | 'group';
  action?: string;
  label?: string;
  /** 显示位置：context=右键菜单, toolbar=页面工具栏, both=两处都显示 */
  position?: 'context' | 'toolbar' | 'both';
  items?: ButtonItemRule[];
  visible?: boolean;
  disabled?: boolean;
  requiresRow?: boolean;
  requiresSelection?: boolean;
  permission?: string;
  /** 工具栏按钮类型 */
  buttonType?: 'default' | 'primary' | 'info' | 'success' | 'warning' | 'error';
  /** 工具栏下拉别名（多 tab 同名按钮合并时显示） */
  toolbarAlias?: string;
  sql?: string;
  script?: string;
  procedure?: string;
  params?: any[];
  confirm?: string;
};

/** 统一按钮规则 */
export type ButtonRule = {
  items: ButtonItemRule[];
};

/** @deprecated 使用 ButtonItemRule 代替 */
export type ContextMenuItemRule = ButtonItemRule;

/** @deprecated 使用 ButtonRule 代替 */
export type ContextMenuRule = ButtonRule;

export type EditableCondition = {
  /** 条件值来源；旧配置未设置时默认读取当前行字段 */
  source?: 'row' | 'currentUser' | 'currentDepartment';
  field: string;
  operator: 'notNull' | 'isNull' | 'eq' | 'ne' | 'in' | 'notIn';
  value?: any;
};

/** 行级可编辑规则 */
export type RowEditableRule = {
  logic?: 'AND' | 'OR';
  conditions?: EditableCondition[];
  condition?: EditableCondition;
  /** SQL 判断（后端执行） */
  sqlCheck?: string;
};

/** 单元格级可编辑规则 - 条件匹配时只允许编辑指定字段 */
export type CellEditableCondition = EditableCondition;

export type CellEditableRule = {
  /** 审批编辑例外只开放命中的字段，不改变其他行或字段的原编辑规则。 */
  requireApproval?: boolean;
  /** 新格式：多条件 + 逻辑组合 */
  logic?: 'AND' | 'OR';
  conditions?: EditableCondition[];
  /** 旧格式兼容：单条件 */
  condition?: EditableCondition;
  /** SQL 判断（后端执行） */
  sqlCheck?: string;
  editableFields: string[];
};

export type EditableRule = {
  scope: 'row' | 'cell';
  logic?: 'AND' | 'OR';
  conditions?: EditableCondition[];
  condition?: EditableCondition;
  sqlCheck?: string;
  editableFields?: string[];
};

/** Grid 样式规则（行颜色、单元格颜色、字体颜色） */
export type GridStyleRule = {
  /** 条件判断字段 */
  field: string;
  operator: 'notNull' | 'eq' | 'ne' | 'in' | 'notIn';
  value?: any;
  /** 作用范围：row=整行, cell=指定单元格 (默认 row) */
  scope?: 'row' | 'cell';
  /** scope=cell 时，样式作用于哪些字段 */
  targetFields?: string[];
  /** 样式 */
  style?: {
    backgroundColor?: string;
    color?: string;
    fontWeight?: string;
    fontStyle?: string;
  };
  /** @deprecated 使用 style 代替 */
  className?: string;
};

/** @deprecated 使用 GridStyleRule */
export type RowClassRule = GridStyleRule;

/** @deprecated 使用 ButtonItemRule 代替 */
export type ToolbarItemRule = ButtonItemRule;

/** @deprecated 使用 ButtonRule 代替 */
export type ToolbarRule = ButtonRule;
