/**
 * 保存、业务按钮失败时顶部的提示（FP-06）：同样的话只出现一次，并指出是哪些行。不引用 AG Grid 和 Vue。
 *
 * 例：成本单 2919 保存被规则拒绝，错误为"每片含量必填且必须大于0"，明细指向原辅料的比沙可啶、一水乳糖（200目）两行，
 * 提示为"每片含量必填且必须大于0（原料/辅料 比沙可啶、一水乳糖（200目））"；原来把错误和每条明细的文字拼在一起，同一句话出现三次。
 *
 * 行的名称（rowLabelField）：页面视图没有专门的名称字段，取这一区域 Lookup 回填的第一个可见文本字段（成本核算明细为
 * 物料名称，主表为产品名称），没有时取第一个可见的文本字段。主表行前面加单据号（工具栏和审批提示都按单据号称呼单据）。
 */
import type { DocumentFailure, FieldValues } from '../../contracts/command';
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

/**
 * 按单据提交（C02 v10 第 1 节）有单据没成功时的提示，同旧系统 useWorkingSetStore.ts 第 1169–1186 行：第一行为张数，
 * 下面每张没成功的单据一行"单据 2551 250mg乙酰唑胺片：原因"。
 *
 * - 原因按 `failureText`；指向这张单据主表行本身的明细只留文字，不再列出单据（这一行开头已经说了）。
 * - 被审批冻结的单据说明是哪个审批（进度另外弹出，同只保存一张单据时）。
 * - `action` 为 null 时是保存，否则为按钮名称；`done` 为成功、没有提交审批的张数。
 */
export function documentFailuresText(
  view: PageView,
  failed: DocumentFailure[],
  counts: { done: number; submitted: number },
  valuesOf: (entity: string, id: string) => FieldValues,
  action: string | null = null
): string {
  const submitted = counts.submitted ? `，提交审批 ${counts.submitted} 张` : '';
  const head =
    action === null
      ? `${counts.submitted ? '保存' : '保存成功'} ${counts.done} 张${submitted}，失败 ${failed.length} 张`
      : `${action}：完成 ${counts.done} 张${submitted}，失败 ${failed.length} 张`;
  const lines = failed.map(failure => {
    const id = (failure.rowKey ?? failure.clientRowId)!;
    const { error } = failure;
    let reason: string;
    if (error.code === 'FROZEN_BY_APPROVAL') {
      const approvals = [...new Set(error.details.map(d => d.approvalId).filter(Boolean))];
      reason = approvals.length ? `${error.message}（审批 ${approvals.join('、')}）` : error.message;
    } else {
      const details = error.details.map(d =>
        d.entity === failure.entity && (d.rowKey ?? d.clientRowId) === id
          ? { ...d, entity: null, rowKey: null, clientRowId: null }
          : d
      );
      reason = failureText(view, { message: error.message, details }, valuesOf);
    }
    return `单据 ${rowLabel(view, { entity: failure.entity, id, values: valuesOf(failure.entity, id) })}：${reason}`;
  });
  return [head, ...lines].join('\n');
}
