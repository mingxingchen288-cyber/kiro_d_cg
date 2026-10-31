/** C05 页面视图。后端同名类型在 types.py 的"C05 页面视图"一节。 */
import { type Infer, array, bool, code, int, json, literal, nullable, object, optional, record, str } from './schema';

export const FieldType = literal('text', 'number', 'date', 'datetime', 'boolean');
export type FieldType = Infer<typeof FieldType>;

export const LookupFilter = object('LookupFilter', {
  column: str,
  from: literal('row', 'cell'),
  field: optional(nullable(str))
});
export type LookupFilter = Infer<typeof LookupFilter>;

/** 写法同 C06 第 3 节的 lookup；`multiple`、`filter`、`fillBack` 为默认值（false、无、true）时省略 */
export const LookupSetting = object('LookupSetting', {
  code,
  fill: record(str),
  multiple: optional(bool),
  filter: optional(nullable(LookupFilter)),
  fillBack: optional(bool)
});
export type LookupSetting = Infer<typeof LookupSetting>;

/** C05 v6：Lookup 对话框的一个显示列（C06 第 9 节）；`label` 没配置时为列名，`width` 没配置时省略（各列平分） */
export const LookupColumn = object('LookupColumn', {
  column: str,
  label: optional(nullable(str)),
  width: optional(nullable(int))
});
export type LookupColumn = Infer<typeof LookupColumn>;

/** 页面视图中的 Lookup：页面配置的设置，加上 Lookup 配置的显示列 `columns`（C05 v6） */
export const ViewLookup = object('ViewLookup', {
  ...LookupSetting.shape,
  columns: optional(array(LookupColumn))
});
export type ViewLookup = Infer<typeof ViewLookup>;

/** 新增行的默认值（C05 v9 `fields[].default`），写法同 C06 第 2 节；没有配置时省略 */
export const FieldDefault = object('FieldDefault', {
  type: literal('static', 'builtin', 'options'),
  value: json
});
export type FieldDefault = Infer<typeof FieldDefault>;

/**
 * 对比的显示方式（C05 v9 `fields[].compare`），取自 C06 第 2 节 `fields[].compare.format`；实体字段没有配置对比时省略。
 * v9 之前生成的页面视图没有这一项，前端按都显示。
 */
export const FieldCompareView = object('FieldCompareView', { format: literal('value', 'percent', 'both') });
export type FieldCompareView = Infer<typeof FieldCompareView>;

export const ViewField = object('ViewField', {
  name: str,
  label: str,
  type: FieldType,
  scale: nullable(int),
  source: literal('erp', 'own'),
  calculated: bool,
  visible: bool,
  editable: bool,
  required: bool,
  width: nullable(int),
  pinned: nullable(literal('left', 'right')),
  dictType: nullable(code),
  lookup: nullable(ViewLookup),
  /** 汇总行（C06 第 3 节 `aggregate`）：`sum` 为这一列在表格底部的汇总行中求和；没有设置时省略 */
  aggregate: optional(nullable(literal('sum'))),
  /**
   * C05 v5：不可编辑、但随本区域可编辑字段的 Lookup 回填写库的字段为 true（例如成本核算主表的产品名称）；否则省略。
   * 用户不能直接填写，Lookup 回填和复制带来的值写进命令（authz AZ-04 接受）。
   */
  fillWritable: optional(bool),
  /** C05 v6：千分位（实体字段的 `grouping`），数值显示时整数部分每三位加英文逗号；为 false 时省略 */
  grouping: optional(bool),
  /** C05 v6：字典下拉中可以填写字典以外的值（页面配置的 `dictFreeText`，旧系统"下拉（可填写）"）；为 false 时省略 */
  dictFreeText: optional(bool),
  /**
   * C05 v7：页面配置的 `searchable`（查询，C06 v23 第 3 节）为 true 且字段可见时为 true，否则省略：
   * 高级查询对话框一打开就列出这个字段的条件（旧系统列配置的"查询"）。
   */
  searchable: optional(bool),
  /** C05 v9：新增行的默认值（实体字段的 `default`），新增行时立即填上，`options` 用下拉（frontend-page FP-23） */
  default: optional(nullable(FieldDefault)),
  /** C05 v9：对比的显示方式（实体字段 `compare.format`），value 只显示差值、percent 只显示百分比、both 都显示（FP-24） */
  compare: optional(nullable(FieldCompareView))
});
export type ViewField = Infer<typeof ViewField>;

export const ViewButton = object('ViewButton', {
  key: code,
  action: code,
  label: str,
  operation: nullable(code),
  requiresSelection: bool
});
export type ViewButton = Infer<typeof ViewButton>;

export const GridOptions = object('GridOptions', { sideBar: bool, cellSelection: bool, groupBy: array(str) });
export type GridOptions = Infer<typeof GridOptions>;

/** 24 列网格的一格：x 从 0 起 */
export const FormCell = object('FormCell', { field: str, x: int, y: int, w: int, h: int });
export type FormCell = Infer<typeof FormCell>;

export const ErpRow = object('ErpRow', { column: str, value: str, localValue: str });
export type ErpRow = Infer<typeof ErpRow>;

export const ViewMaster = object('ViewMaster', {
  entity: code,
  primaryKey: str,
  fields: array(ViewField),
  buttons: array(ViewButton),
  grid: GridOptions,
  formLayout: array(FormCell),
  erpRow: optional(nullable(ErpRow)),
  /**
   * C05 v8：当前角色能否修改本区域已经保存的行（角色权限 `<区域>:modify`）。为 false 时这些行整行只读；
   * 新增、复制出的行不受影响，按 `fields[].editable`。为 true 时省略。
   */
  canModify: optional(bool)
});
export type ViewMaster = Infer<typeof ViewMaster>;

export const ViewDetail = object('ViewDetail', {
  entity: code,
  title: str,
  primaryKey: str,
  parentKey: str,
  fields: array(ViewField),
  buttons: array(ViewButton),
  grid: GridOptions,
  formLayout: array(FormCell),
  erpRow: optional(nullable(ErpRow)),
  /** 同 ViewMaster.canModify */
  canModify: optional(bool)
});
export type ViewDetail = Infer<typeof ViewDetail>;

export const PackRef = object('PackRef', { packId: code, version: int });
export type PackRef = Infer<typeof PackRef>;

/**
 * C05 v8 起后端只给出 `save`、`advancedSearch`；新增、删除按区域授权，见区域的 `buttons`。`addRow`、`deleteRow`
 * 留着是为了能读 v8 之前生成、还没重新生成的页面视图，页面不用这两项。
 */
export const SystemButton = literal('save', 'addRow', 'deleteRow', 'advancedSearch');
export type SystemButton = Infer<typeof SystemButton>;

export const PageView = object('PageView', {
  pageCode: code,
  title: str,
  version: int,
  layout: literal('single', 'masterDetail'),
  detailMode: literal('tabs', 'stack'),
  audit: bool,
  saveOperation: code,
  rulesPack: PackRef,
  master: ViewMaster,
  details: array(ViewDetail),
  systemButtons: array(SystemButton)
});
export type PageView = Infer<typeof PageView>;

/** 主表区或某个明细区 */
export type ViewRegion = ViewMaster | ViewDetail;
