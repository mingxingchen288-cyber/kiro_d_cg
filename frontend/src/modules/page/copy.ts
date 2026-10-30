/**
 * 复制（FP-13）：只在区域的 `buttons` 含 `copyRow` 时提供。对照旧系统 useWorkingSetStore.ts 的
 * copyMasterRow / copyDetailRow 和 copy-row-fields.ts。
 *
 * - 主表区复制一行：勾选要复制的主表字段，以及每个明细要复制的行和字段；明细区复制：勾选行（默认是选中的行）和字段。默认全选。
 * - 只有主键不复制；明细的关联字段指向新的主表行（编辑缓冲按单据记录，命令中不带关联字段）；没勾选的字段留空。
 *   复制出的行标为 copied：命令中为空的可写字段写成 null，后端不补默认值（WP-16），保存后仍为空（T-AS-7 发现：
 *   原来这些字段不写进命令，后端把为空的数值字段补成 0，例如没勾的"年需求量"保存后为 0）。
 * - 勾选的字段不论能不能编辑都写进新行（同旧系统 copy-row-fields.ts 复制源行全部字段、useWorkingSetStore.ts 新增行
 *   提交全部字段）：复制出的行记下来源（源行主键和勾选的字段），命令中带 `copyOf`，不可写的复制字段（例如成本单的币种、
 *   项目号）也写进命令，后端取源行的值（C02 第 1 节、WP-21）。源行是还没保存的复制行时沿用它的来源，复制的字段取两次
 *   勾选都有的；源行是还没保存的新增行（不是复制来的）时没有来源，不可写的字段不写。
 * - 复制的是当前显示的值（含未保存的修改和预览算出的计算字段），标为删除的行不复制。
 * - `erpRow.column` 由平台设为本地值，不从源行复制；ERP 列照样复制，新行是本地行，可以编辑。
 * - 复制出的主表行放在源行下方，明细行放在最后一个选中行的下方；撤销一次撤回整个复制。
 */
import type { FieldValues } from '../../contracts/command';
import type { ViewRegion } from '../../contracts/page-view';
import type { CopyOrigin } from './edit-buffer';
import type { PageModel } from './view-model';

export interface FieldChoice {
  name: string;
  label: string;
}

export interface CopySelection {
  /** 要复制的主表字段（主表区复制）或明细字段（明细区复制） */
  fields: string[];
  /** 主表区复制时每个明细实体要复制的行和字段 */
  details?: Record<string, { rows: string[]; fields: string[] }>;
}

/** 复制对话框中可以勾选的字段：可见、不是主键、不是关联字段、不是 erpRow.column */
export function copyableFields(region: ViewRegion): FieldChoice[] {
  return region.fields
    .filter(f => f.visible)
    .filter(f => f.name !== region.primaryKey)
    .filter(f => !('parentKey' in region) || f.name !== region.parentKey)
    .filter(f => !region.erpRow || f.name !== region.erpRow.column)
    .map(f => ({ name: f.name, label: f.label }));
}

/** 默认全选：主表区复制时每个明细的全部未删除行和全部字段 */
export function defaultMasterSelection(model: PageModel, recordId: string): CopySelection {
  const view = model.view;
  return {
    fields: copyableFields(view.master).map(f => f.name),
    details: Object.fromEntries(
      view.details.map(d => [
        d.entity,
        {
          rows: model.detailIds(d.entity, recordId).filter(id => !model.buffer.isDeleted(d.entity, id)),
          fields: copyableFields(d).map(f => f.name)
        }
      ])
    )
  };
}

function copiedValues(model: PageModel, region: ViewRegion, sourceId: string, fields: string[]): FieldValues {
  const source = model.values(region.entity, sourceId);
  const chosen = new Set(fields);
  const values: FieldValues = {};
  for (const field of region.fields) {
    values[field.name] = chosen.has(field.name) ? (source[field.name] ?? null) : null;
  }
  // 不在页面视图中的字段（不可见的字段也在视图里）不复制；主键、关联字段留空
  values[region.primaryKey] = null;
  if ('parentKey' in region) values[region.parentKey] = null;
  if (region.erpRow) values[region.erpRow.column] = region.erpRow.localValue;
  return values;
}

/** 复制出的行的来源：源行已保存时为它的主键和勾选的字段；源行是没保存的复制行时沿用它的来源 */
function originOf(model: PageModel, entity: string, sourceId: string, fields: string[]): CopyOrigin {
  if (!model.buffer.isNew(entity, sourceId)) return { copyOf: sourceId, fields: [...fields] };
  const previous = model.buffer.copyOrigin(entity, sourceId);
  if (!previous?.copyOf) return { copyOf: null, fields: [] };
  return { copyOf: previous.copyOf, fields: fields.filter(f => previous.fields.includes(f)) };
}

/** 主表区复制一行：返回新主表行的 clientRowId。调用前源单据的明细必须已加载 */
export function copyMaster(model: PageModel, sourceId: string, selection: CopySelection): string {
  const view = model.view;
  return model.buffer.batch(() => {
    const newId = model.buffer.addRow(
      view.master.entity,
      null,
      copiedValues(model, view.master, sourceId, selection.fields),
      sourceId,
      { copied: true, origin: originOf(model, view.master.entity, sourceId, selection.fields) }
    );
    model.ensureNewRecord(newId);
    for (const detail of view.details) {
      const chosen = selection.details?.[detail.entity];
      if (!chosen) continue;
      const rows = model
        .detailIds(detail.entity, sourceId)
        .filter(id => chosen.rows.includes(id) && !model.buffer.isDeleted(detail.entity, id));
      let after: string | null = null;
      for (const rowId of rows) {
        after = model.buffer.addRow(detail.entity, newId, copiedValues(model, detail, rowId, chosen.fields), after, {
          copied: true,
          origin: originOf(model, detail.entity, rowId, chosen.fields)
        });
      }
    }
    return newId;
  });
}

/** 明细区复制：选中的行复制到同一张单据，放在最后一个选中行的下方；返回新行 */
export function copyDetailRows(
  model: PageModel,
  entity: string,
  recordId: string,
  rows: string[],
  fields: string[]
): string[] {
  const region = model.region(entity)!;
  const order = model.detailIds(entity, recordId);
  const sources = order.filter(id => rows.includes(id) && !model.buffer.isDeleted(entity, id));
  if (!sources.length) return [];
  return model.buffer.batch(() => {
    let after: string | null = sources[sources.length - 1];
    return sources.map(sourceId => {
      after = model.buffer.addRow(entity, recordId, copiedValues(model, region, sourceId, fields), after, {
        copied: true,
        origin: originOf(model, entity, sourceId, fields)
      });
      return after;
    });
  });
}
