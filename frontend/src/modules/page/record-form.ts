/**
 * 原地表单（FP-03）的内容，主表区和每个明细区用同一套。不引用 AG Grid 和 Vue；界面在 renderers/RecordForm.vue。
 *
 * 表单和表格用同一份区域元数据：页面视图里这个区域的 `fields`（可见、可编辑、字典、Lookup、必填、默认值的下拉），界面规则给出的
 * 可编辑和必填、冻结、区域的 `canModify`（都经 PageRuntime.cellEditable、PageModel.cellRequired，同表格的单元格）；改值经同一个
 * 编辑缓冲（PageRuntime.editForm → edit）。字段显示的内容与表格同一格用同一组判断（marks.ts）：改动标记和错误标记、悬停时的
 * 错误提示、对比（箭头和差值，FP-15、FP-24）、界面规则的单元格样式；行的标记（删除、新增、冻结）和界面规则的行样式加在表单主体上，
 * 对应表格的行。唯一不同的是排布：按这个区域的 `formLayout`（C05，24 列网格，每个字段的位置和大小），没有配置时可见字段按顺序
 * 每行 3 个。
 *
 * 依据：用户 2026-11-01"表单和表格可以公用一个元数据，表单唯一的区别仅仅是可以调整每个表单列的位置和带线（大小）"。
 * 旧系统没有行表单（主表、明细都没有），这是新平台的能力。
 */
import type { FieldValue, FieldValues } from '../../contracts/command';
import type { FormCell, PageView, ViewField, ViewRegion } from '../../contracts/page-view';
import { rowLabel } from './failure';
import { type CompareDisplay, displayText, optionValues } from './fields';
import { cellCompare, cellErrorText, cellMarks, cellTooltip, rowMarks, ruleCellStyle, ruleRowStyle } from './marks';
import type { PageRuntime } from './page-runtime';

/** formLayout 的列数（C05） */
const GRID_COLUMNS = 24;

/** 没有配置 formLayout 时每行几个字段 */
const PER_ROW = 3;

/** 表单中的一个字段 */
export interface FormItem {
  field: ViewField;
  /** 在 24 列网格中的位置和大小 */
  cell: FormCell;
  value: FieldValue;
  /** 只读时显示的文字（字典标签、小数位、千分位，同表格） */
  text: string;
  editable: boolean;
  required: boolean;
  /** 下拉的选项：字典（可填写的字典把字典以外的当前值也列出），或 `default` 为 `options` 的值；都没有时为 null */
  options: Array<{ value: string; label: string }> | null;
  /** 改动标记和错误标记的样式名（marks.ts） */
  marks: string[];
  /** 保存失败定位到这个字段的错误 */
  error: string | undefined;
  /** 悬停时提示的错误，同表格这一格的提示（含整行的错误） */
  tooltip: string | undefined;
  /** 对比的箭头、差值和颜色，同表格这一格；没有对比或差值为 0 时为 null */
  compare: CompareDisplay | null;
  /** 界面规则给这一格的样式（同表格这一格） */
  style: Record<string, string> | undefined;
}

export interface FormView {
  entity: string;
  /** 表格行标识（新增行保存后不变） */
  gridId: string;
  /** 行标识 */
  id: string;
  title: string;
  /** 行所在单据被冻结时，冻结它的审批 */
  frozenBy: string | null;
  /** 行的标记的样式名（删除、新增、冻结，同表格的行） */
  rowMarks: string[];
  /** 界面规则给这一行的样式（同表格的行） */
  rowStyle: Record<string, string> | undefined;
  items: FormItem[];
}

/** 表单中的字段和位置：按区域的 `formLayout`，只取可见字段；为空时可见字段按顺序每行 3 个，每个占 8 列、1 行 */
export function formLayoutOf(region: ViewRegion): Array<{ field: ViewField; cell: FormCell }> {
  const visible = region.fields.filter(f => f.visible);
  if (region.formLayout.length) {
    return region.formLayout
      .map(cell => ({ field: visible.find(f => f.name === cell.field), cell }))
      .filter((item): item is { field: ViewField; cell: FormCell } => Boolean(item.field));
  }
  const width = GRID_COLUMNS / PER_ROW;
  return visible.map((field, index) => ({
    field,
    cell: { field: field.name, x: (index % PER_ROW) * width, y: Math.floor(index / PER_ROW), w: width, h: 1 }
  }));
}

/**
 * 表单标题：主表为"单据 2550"，新增的为"新增的单据（未保存）"；明细为明细标题加行的名称（failure.ts 的 rowLabel），
 * 例如"原料/辅料 聚维酮K30"，新增的为"原料/辅料 新增的一行（未保存）"。
 */
export function formTitle(view: PageView, row: { entity: string; id: string; values: FieldValues; isNew: boolean }) {
  const { entity, id, values, isNew } = row;
  if (entity === view.master.entity) {
    const key = values[view.master.primaryKey];
    return key ? `单据 ${key}` : '新增的单据（未保存）';
  }
  const title = view.details.find(d => d.entity === entity)?.title ?? entity;
  return isNew ? `${title} 新增的一行（未保存）` : `${title} ${rowLabel(view, { entity, id, values })}`;
}

function optionsOf(field: ViewField, value: FieldValue, dict: Map<string, string> | undefined) {
  if (dict) {
    const list = [...dict].map(([key, label]) => ({ value: key, label }));
    // 可填写的字典下拉（C05 dictFreeText）：当前值不在字典中时也列出，同表格中的编辑器
    if (field.dictFreeText && typeof value === 'string' && value && !dict.has(value))
      list.unshift({ value, label: value });
    return list;
  }
  const options = optionValues(field);
  return options ? options.map(option => ({ value: option, label: option })) : null;
}

/** 这个区域打开的表单的内容；没打开时为 null */
export function formView(runtime: PageRuntime, entity: string): FormView | null {
  const view = runtime.view.value;
  const gridId = runtime.state.forms[entity];
  const region = view && runtime.model.region(entity);
  if (!view || !gridId || !region) return null;
  const model = runtime.model;
  const id = model.rowIdOf(gridId);
  const values = model.values(entity, id);
  const items = formLayoutOf(region).map(({ field, cell }): FormItem => {
    const dict = field.dictType ? runtime.dicts.get(field.dictType) : undefined;
    const value = values[field.name] ?? null;
    const ref = { region, id, field: field.name };
    return {
      field,
      cell,
      value,
      text: displayText(field, value, dict),
      editable: runtime.cellEditable(entity, gridId, field.name),
      required: model.cellRequired(entity, id, field.name),
      options: optionsOf(field, value, dict),
      marks: cellMarks(model, ref),
      error: cellErrorText(model, ref),
      tooltip: cellTooltip(model, ref),
      compare: cellCompare(model, ref),
      style: ruleCellStyle(model, ref)
    };
  });
  const isNew = model.buffer.isNew(entity, id);
  return {
    entity,
    gridId,
    id,
    title: formTitle(view, { entity, id, values, isNew }),
    frozenBy: model.frozenBy(entity, id),
    rowMarks: rowMarks(model, entity, id),
    rowStyle: ruleRowStyle(model, entity, id),
    items
  };
}
