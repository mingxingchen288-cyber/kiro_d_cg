/**
 * 保存、业务按钮失败时顶部的提示（FP-06）：同样的话只出现一次，并指出是哪些行。不引用 AG Grid 和 Vue。
 *
 * 例：成本单 2919 保存被规则拒绝，错误为"每片含量必填且必须大于0"，明细指向原辅料的比沙可啶、一水乳糖（200目）两行，
 * 提示为"每片含量必填且必须大于0（原料/辅料 比沙可啶、一水乳糖（200目））"；原来把错误和每条明细的文字拼在一起，同一句话出现三次。
 *
 * 行的名称（rowLabelField）：页面视图没有专门的名称字段，取这一区域 Lookup 回填的第一个可见文本字段（成本核算明细为
 * 物料名称，主表为产品名称），没有时取第一个可见的文本字段。主表行前面加单据号（工具栏和审批提示都按单据号称呼单据）。
 */
import type { FieldValues } from '../../contracts/command';
import type { ErrorDetail } from '../../contracts/errors';
import type { PageView, ViewRegion } from '../../contracts/page-view';
import { regionOf } from './fields';

/** 能让用户认出这一行的文本字段 */
export function rowLabelField(region: ViewRegion): string | null {
  const shownText = (name: string) => region.fields.some(f => f.name === name && f.visible && f.type === 'text');
  const filled = region.fields
    .filter(f => f.lookup && f.lookup.fillBack !== false)
    .flatMap(f => Object.keys(f.lookup!.fill))
    .find(shownText);
  if (filled) return filled;
  const keys = new Set([region.primaryKey, 'parentKey' in region ? region.parentKey : '']);
  return region.fields.find(f => f.visible && f.type === 'text' && !keys.has(f.name))?.name ?? null;
}

const isClientRowId = (id: string) => id.startsWith('tmp-');

/** 一行的称呼：主表为"单据号 名称"（新增的为"新增的 名称"），明细为名称；没有名称时用主键 */
export function rowLabel(view: PageView, row: { entity: string; id: string; values: FieldValues }): string {
  const { entity, id, values } = row;
  const region = regionOf(view, entity);
  const field = region && rowLabelField(region);
  const raw = field ? values[field] : null;
  const name = typeof raw === 'string' && raw.trim() ? raw.trim() : '';
  if (entity === view.master.entity) {
    if (isClientRowId(id)) return name ? `新增的 ${name}` : '新增的一张';
    return name ? `${id} ${name}` : id;
  }
  if (name) return name;
  return isClientRowId(id) ? '新增的一行' : `ID ${id}`;
}

function regionName(view: PageView, entity: string) {
  if (entity === view.master.entity) return '单据';
  return view.details.find(d => d.entity === entity)?.title ?? entity;
}

/**
 * 失败提示的文字：错误明细按文字分组，每组列出涉及的行（按区域，同一行只列一次）；错误本身的文字与某组相同时不再重复，
 * 不同时放在最前面。`valuesOf` 给出行的当前值（取不到时为空，用主键称呼）。
 */
export function failureText(
  view: PageView,
  error: { message: string; details: ErrorDetail[] },
  valuesOf: (entity: string, id: string) => FieldValues
): string {
  const groups = new Map<string, Map<string, string[]>>();
  for (const detail of error.details) {
    const message = detail.message || error.message;
    const rows = groups.get(message) ?? new Map<string, string[]>();
    groups.set(message, rows);
    const id = detail.rowKey ?? detail.clientRowId;
    if (detail.entity && id) {
      const region = regionName(view, detail.entity);
      const labels = rows.get(region) ?? [];
      const label = rowLabel(view, { entity: detail.entity, id, values: valuesOf(detail.entity, id) });
      if (!labels.includes(label)) labels.push(label);
      rows.set(region, labels);
    }
  }
  const parts = [...groups].map(([message, rows]) => {
    const where = [...rows].map(([region, labels]) => `${region} ${labels.join('、')}`).join('，');
    return where ? `${message}（${where}）` : message;
  });
  if (!parts.length) return error.message;
  const text = parts.join('；');
  return groups.has(error.message) || !error.message ? text : `${error.message}：${text}`;
}
