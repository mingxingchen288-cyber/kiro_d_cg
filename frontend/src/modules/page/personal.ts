/**
 * 个人列配置（FP-11，C09 第 4 节 PersonalConfig，queries-export QE-07）：列宽、顺序、固定、显隐和明细显示方式。
 * - 上层隐藏的列（页面视图中不可见的字段）不在表格中，个人配置中的这些列不应用、不保存，不能被设为显示。
 * - 保存时只提交改变的部分：与上次保存（或页面默认）不同的表格，以及改变了的明细显示方式。
 * 对照旧系统 useUserGridConfig.ts（按"保存列配置"按钮保存，提示"列配置已保存"）。
 */
import type { PersonalColumn, PersonalConfig, PersonalGrid } from '../../contracts/http';
import type { PageView, ViewRegion } from '../../contracts/page-view';
import { MASTER_GRID, regionKey } from './fields';

/** 页面默认的列状态（个人配置为空时） */
export function defaultColumns(region: ViewRegion): PersonalColumn[] {
  return region.fields
    .filter(f => f.visible)
    .map(f => ({ field: f.name, width: f.width, pinned: f.pinned, hide: false }));
}

/** 个人配置中这个表格要应用的列：只保留页面视图中可见的列 */
export function columnsToApply(region: ViewRegion, grid: PersonalGrid | undefined): PersonalColumn[] {
  const visible = new Set(region.fields.filter(f => f.visible).map(f => f.name));
  return (grid?.columns ?? []).filter(c => visible.has(c.field));
}

function sameColumns(a: PersonalColumn[], b: PersonalColumn[]) {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * 当前的列状态与已保存的个人配置比较，给出要提交的部分。`current` 的键为 `master` 或明细实体，值为表格当前的列
 * （只含可见字段，按显示顺序）。没有要提交的内容时返回 null。
 */
export function personalChanges(
  view: PageView,
  saved: PersonalConfig,
  current: Record<string, PersonalColumn[]>,
  detailMode: 'tabs' | 'stack'
): PersonalConfig | null {
  const grids: Record<string, PersonalGrid> = {};
  for (const region of [view.master, ...view.details]) {
    const key = regionKey(view, region.entity);
    const columns = current[key];
    if (!columns) continue;
    const visible = new Set(region.fields.filter(f => f.visible).map(f => f.name));
    const own = columns.filter(c => visible.has(c.field));
    const before = saved.grids?.[key]?.columns ? columnsToApply(region, saved.grids[key]) : defaultColumns(region);
    if (!sameColumns(own, before)) grids[key] = { columns: own };
  }
  const changes: PersonalConfig = {};
  if (Object.keys(grids).length) changes.grids = grids;
  const savedMode = saved.detailMode ?? view.detailMode;
  if (detailMode !== savedMode) changes.detailMode = detailMode;
  return Object.keys(changes).length ? changes : null;
}

/** 合并保存后的结果，作为下次比较的基准 */
export function mergePersonal(saved: PersonalConfig, changes: PersonalConfig): PersonalConfig {
  return {
    grids: { ...(saved.grids ?? {}), ...(changes.grids ?? {}) },
    detailMode: changes.detailMode ?? saved.detailMode ?? null
  };
}

export { MASTER_GRID };
