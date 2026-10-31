/**
 * 改动标记和错误标记：表格的单元格（grid-adapter/columns.ts 的 cellClassRules）和原地表单的字段（record-form.ts）用同一组判断、
 * 同一份样式（marks.css）。颜色沿用旧系统（MasterDetailPageV3.vue）：改过的格绿色、计算带出变化的格黄色、新增行深蓝底白字、
 * 删除行加删除线；保存失败定位到的格红框（FP-06）。不引用 AG Grid 和 Vue。
 */
import type { ViewRegion } from '../../contracts/page-view';
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
