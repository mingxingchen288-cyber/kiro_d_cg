/**
 * 表单布局编辑（FC-03、C05 `formLayout`）：24 列网格，`x` 从 0 起，`x + w` 不超过 24，`w`、`h` 不小于 1。
 * 拖动和缩放都按整列、整行取整（像素换算成格子后四舍五入），越界时贴边；放下后与别的字段重叠时，把被压住的字段
 * 往下推（与 grid-layout-plus 的默认行为相同：垂直方向避让）。保存后所有人共用；退出编辑而不保存时恢复原布局。
 *
 * 旧系统没有表单布局拖动编辑（cost-web 源码中没有 formLayout），这里按模块说明实现；
 * 模块说明指定的 grid-layout-plus 没有安装（见 contract-gaps），拖动由 FormLayoutEditor.vue 用指针事件实现，规则都在本文件。
 */
import { reactive } from 'vue';
import type { FormCell } from '../core/types';

export const GRID_COLUMNS = 24;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/** 页面视图中 formLayout 为空时每行 3 个字段（frontend-page RecordForm 的默认排法），编辑从这个排法开始 */
export function defaultLayout(fields: string[]): FormCell[] {
  return fields.map((field, i) => ({ field, x: (i % 3) * 8, y: Math.floor(i / 3), w: 8, h: 1 }));
}

/** 把一格修正到网格内：整数、不越界 */
export function normalizeCell(cell: FormCell): FormCell {
  const w = clamp(Math.round(cell.w), 1, GRID_COLUMNS);
  const h = Math.max(1, Math.round(cell.h));
  const x = clamp(Math.round(cell.x), 0, GRID_COLUMNS - w);
  const y = Math.max(0, Math.round(cell.y));
  return { field: cell.field, x, y, w, h };
}

const overlaps = (a: FormCell, b: FormCell) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** 放下 `moved` 后，与它重叠的格子依次往下推到不重叠为止 */
export function resolveCollisions(cells: FormCell[], moved: string): FormCell[] {
  const result = cells.map(c => ({ ...c }));
  const queue = [moved];
  let guard = 0;
  while (queue.length && guard++ < 1000) {
    const name = queue.shift();
    const current = result.find(c => c.field === name)!;
    for (const other of result) {
      if (other.field === current.field || !overlaps(current, other)) continue;
      other.y = current.y + current.h;
      queue.push(other.field);
    }
  }
  return result;
}

/** 像素位移换算成格子数（四舍五入到整列、整行） */
export function toGrid(deltaPx: number, unitPx: number) {
  return unitPx > 0 ? Math.round(deltaPx / unitPx) : 0;
}

export function sortCells(cells: FormCell[]) {
  return [...cells].sort((a, b) => a.y - b.y || a.x - b.x);
}

export class FormLayoutModel {
  readonly state = reactive({
    editing: false,
    dirty: false,
    cells: [] as FormCell[]
  });

  private original: FormCell[] = [];

  constructor(
    /** 区域中可以放进表单的字段（按字段顺序） */
    readonly fields: string[],
    layout: FormCell[]
  ) {
    this.original = layout.map(c => ({ ...c }));
    this.state.cells = this.original.map(c => ({ ...c }));
  }

  /** 进入编辑：布局为空时从默认排法开始 */
  begin() {
    this.original = this.state.cells.map(c => ({ ...c }));
    if (!this.state.cells.length) this.state.cells = defaultLayout(this.fields);
    this.state.editing = true;
    this.state.dirty = false;
  }

  /** 拖动到 (x, y)：取整、贴边、避让 */
  move(field: string, x: number, y: number) {
    const cell = this.state.cells.find(c => c.field === field);
    if (!cell) return;
    const next = normalizeCell({ ...cell, x, y });
    this.state.cells = resolveCollisions(
      this.state.cells.map(c => (c.field === field ? next : c)),
      field
    );
    this.state.dirty = true;
  }

  /** 缩放到宽 w、高 h：不超出 24 列，不小于 1 */
  resize(field: string, w: number, h: number) {
    const cell = this.state.cells.find(c => c.field === field);
    if (!cell) return;
    const width = clamp(Math.round(w), 1, GRID_COLUMNS - cell.x);
    const next = normalizeCell({ ...cell, w: width, h });
    this.state.cells = resolveCollisions(
      this.state.cells.map(c => (c.field === field ? next : c)),
      field
    );
    this.state.dirty = true;
  }

  /** 没放进表单的字段 */
  unplaced() {
    const placed = new Set(this.state.cells.map(c => c.field));
    return this.fields.filter(f => !placed.has(f));
  }

  /** 把字段放到最下面一行 */
  add(field: string) {
    if (this.state.cells.some(c => c.field === field)) return;
    const bottom = Math.max(0, ...this.state.cells.map(c => c.y + c.h));
    this.state.cells.push({ field, x: 0, y: bottom, w: 8, h: 1 });
    this.state.dirty = true;
  }

  remove(field: string) {
    this.state.cells = this.state.cells.filter(c => c.field !== field);
    this.state.dirty = true;
  }

  /** 要保存的布局（C05）：按行、列排序 */
  result(): FormCell[] {
    return sortCells(this.state.cells.map(normalizeCell));
  }

  /** 保存成功后：当前布局成为原布局，退出编辑 */
  commit() {
    this.original = this.result();
    this.state.cells = this.original.map(c => ({ ...c }));
    this.state.editing = false;
    this.state.dirty = false;
  }

  /** 退出编辑而不保存：恢复原布局 */
  cancel() {
    this.state.cells = this.original.map(c => ({ ...c }));
    this.state.editing = false;
    this.state.dirty = false;
  }
}
