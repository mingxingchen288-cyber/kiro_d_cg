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

/**
 * 新增行的默认值，写法同 C06 第 2 节 `fields[].default`。
 * C05 v3 的页面视图还没有这一项（契约缺口，见 .reports/modules/frontend-page/contract-gaps.md 第 1 项），后端给出时前端照用。
 */
export const FieldDefault = object('FieldDefault', {
  type: literal('static', 'builtin', 'options'),
  value: json
});
export type FieldDefault = Infer<typeof FieldDefault>;

/**
 * 对比的显示方式，取自 C06 第 2 节 `fields[].compare.format`。C05 v3 还没有这一项（契约缺口第 2 项）；
 * 没有时按行中给出的差值和百分比都显示。
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
  lookup: nullable(LookupSetting),
  default: optional(nullable(FieldDefault)),
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
  erpRow: optional(nullable(ErpRow))
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
  erpRow: optional(nullable(ErpRow))
});
export type ViewDetail = Infer<typeof ViewDetail>;

export const PackRef = object('PackRef', { packId: code, version: int });
export type PackRef = Infer<typeof PackRef>;

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
