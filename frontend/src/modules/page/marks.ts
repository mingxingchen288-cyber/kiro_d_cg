/**
 * 表格的单元格（grid-adapter/columns.ts、PageGrid.vue）和原地表单的字段（record-form.ts）共用的显示，同一组判断：
 * - 改动标记和错误标记（样式 marks.css）：颜色沿用旧系统（MasterDetailPageV3.vue），改过的格绿色、计算带出变化的格黄色、
 *   新增行深蓝底白字、删除行加删除线；保存失败定位到的格红框（FP-06）。
 * - 行的标记（样式 marks.css）：删除的行半透明、新增的行斜体、被冻结的单据灰字。表格加在行上，表单加在表单主体上。
 * - 悬停时的错误提示、对比（FP-15、FP-24）、界面规则的行样式和单元格样式（FP-18）。
 * 依据用户 2026-11-01"表单和表格可以公用一个元数据，表单唯一的区别仅仅是可以调整每个表单列的位置和带线（即大小，用户 2026-11-01 确认）"。
 * 不引用 AG Grid 和 Vue。
 */
import type { ViewRegion } from '../../contracts/page-view';
import { type CompareDisplay, compareDisplay } from './fields';
import type { CellError, PageModel } from './view-model';

/** 一格：区域、行标识、字段 */
export interface CellRef {
  region: ViewRegion;
  id: string;
  field: string;
}

/** 保存失败定位到这一格的错误：指向这个字段的，以及不指向字段、标在主键上的 */
function cellErrors(model: PageModel, { region, id, field }: CellRef): CellError[] {
  return model
    .errorsOf(region.entity, id)
    .filter(e => e.field === field || (e.field === null && field === region.primaryKey));
}

/** 样式名 → 这一格是否带这个标记 */
export const CELL_MARKS: Record<string, (model: PageModel, cell: CellRef) => boolean> = {
  'cell-user-changed': (model, { region, id, field }) => model.buffer.isChanged(region.entity, id, field),
  'cell-calc-changed': (model, { region, id, field }) => model.isCalcChanged(region.entity, id, field),
  'cell-new': (model, { region, id }) => model.buffer.isNew(region.entity, id),
  'cell-deleted': (model, { region, id }) => model.buffer.isDeleted(region.entity, id),
  'cell-error': (model, cell) => cellErrors(model, cell).length > 0
};

/** 这一格带的标记（样式名） */
export function cellMarks(model: PageModel, cell: CellRef): string[] {
  return Object.entries(CELL_MARKS)
    .filter(([, test]) => test(model, cell))
    .map(([name]) => name);
}

/** 这一格标红的错误的文字；没有时为 undefined */
export function cellErrorText(model: PageModel, cell: CellRef): string | undefined {
  const errors = cellErrors(model, cell);
  return errors.length ? errors.map(e => e.message).join('；') : undefined;
}

/** 悬停这一格时提示的错误：指向这个字段的，以及不指向字段的（整行的）；没有时为 undefined */
export function cellTooltip(model: PageModel, { region, id, field }: CellRef): string | undefined {
  const errors = model.errorsOf(region.entity, id).filter(e => e.field === field || e.field === null);
  return errors.length ? errors.map(e => e.message).join('；') : undefined;
}

/** 样式名 → 这一行是否带这个标记（区域实体、行标识） */
export const ROW_MARKS: Record<string, (model: PageModel, entity: string, id: string) => boolean> = {
  'row-deleted': (model, entity, id) => model.buffer.isDeleted(entity, id),
  'row-new': (model, entity, id) => model.buffer.isNew(entity, id),
  'row-frozen': (model, entity, id) => Boolean(model.frozenBy(entity, id))
};

/** 这一行带的标记（样式名） */
export function rowMarks(model: PageModel, entity: string, id: string): string[] {
  return Object.entries(ROW_MARKS)
    .filter(([, test]) => test(model, entity, id))
    .map(([name]) => name);
}

/**
 * 这一格的对比：行中带的对比值（C09 DataRow.compare）按字段的 `compare.format` 显示（fields.ts 的 compareDisplay）；
 * 没有对比值或差值为 0 时为 null。布尔字段是复选框，不显示对比。
 */
export function cellCompare(model: PageModel, { region, id, field }: CellRef): CompareDisplay | null {
  const meta = region.fields.find(f => f.name === field);
  if (!meta || meta.type === 'boolean') return null;
  return compareDisplay(meta, model.compare(region.entity, id)?.[field]);
}

type Style = Record<string, string>;

function styleOf(value: unknown): Style | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Style) : undefined;
}

/** 界面规则给这一行的样式（有修改时取预览，否则取显示求值，见 PageModel.ruleView）；没有时为 undefined */
export function ruleRowStyle(model: PageModel, entity: string, id: string): Style | undefined {
  return styleOf(model.ruleView(entity, id)?.style.row);
}

/** 界面规则给这一格的样式；没有时为 undefined */
export function ruleCellStyle(model: PageModel, { region, id, field }: CellRef): Style | undefined {
  return styleOf(model.ruleView(region.entity, id)?.style.cells[field]);
}
