/**
 * 汇总行（C06 第 3 节 `aggregate`，同旧系统列配置的"求和"）：表格底部固定的一行，`aggregate` 为 `sum` 的可见列求和，
 * 其他列为空；显示格式同这一列（小数位）。不引用 AG Grid 和 Vue。
 *
 * - 主表区：列表接口的 `aggregates`（全部满足查询条件的行，queries-export 的 QE-04）加上还没保存的修改：
 *   改过的单据加上主表行修改后与正式数据的差（计算字段取预览的值），新增的单据计入，标为删除的单据减去。
 *   对应旧系统 useMasterGridBindings.ts 的 updatePinnedSumRow（编辑和计算联动后重算）。
 * - 明细区：当前单据这个明细的全部行求和，标为删除的行不计入（与 C07 的汇总相同）。
 *   对应旧系统 DetailGridV3.vue 的 grandTotalRow。
 *
 * 数值是十进制文本（C01），用 BigInt 相加，不经过浮点；空值按 0 计入。没有可汇总的值时（没有行）不显示汇总行。
 */
import type { FieldValue, FieldValues } from '../../contracts/command';
import { type DecimalValue, formatDecimal, isDecimalText, parseDecimal } from '../../contracts/decimal-text';
import type { ViewRegion } from '../../contracts/page-view';
import type { PageModel } from './view-model';

/** 汇总行在表格中的行标识 */
export const SUMMARY_ROW_ID = '__aggregates';

/** 区域中求和的列：`aggregate` 为 `sum` 的可见字段，按字段顺序 */
export function sumFields(region: ViewRegion): string[] {
  return region.fields.filter(f => f.visible && f.aggregate === 'sum').map(f => f.name);
}

const ZERO: DecimalValue = { digits: 0n, scale: 0 };

function decimal(value: FieldValue | undefined): DecimalValue {
  return isDecimalText(value) ? parseDecimal(value as string) : ZERO;
}

function plus(a: DecimalValue, b: DecimalValue, sign: 1n | -1n = 1n): DecimalValue {
  const scale = Math.max(a.scale, b.scale);
  const at = (v: DecimalValue) => v.digits * 10n ** BigInt(scale - v.scale);
  return { digits: at(a) + sign * at(b), scale };
}

/** 汇总行的值；全部为空时为 null（不显示汇总行） */
function summaryRow(sums: Map<string, DecimalValue | null>): FieldValues | null {
  if ([...sums.values()].every(v => v === null)) return null;
  return Object.fromEntries([...sums].map(([field, v]) => [field, v === null ? null : formatDecimal(v)]));
}

/** 主表区的汇总行：后端的汇总（`base`，正式数据）加上还没保存的修改；没有求和的列时为 null */
export function masterSummary(model: PageModel, base: FieldValues): FieldValues | null {
  const fields = sumFields(model.view.master);
  if (!fields.length) return null;
  const master = model.master;
  const buffer = model.buffer;
  const sums = new Map<string, DecimalValue | null>(
    fields.map(f => [f, isDecimalText(base[f]) ? parseDecimal(base[f] as string) : null])
  );
  // 有未保存修改的单据（新增行删除后已不在编辑缓冲中）
  for (const id of buffer.dirtyRecords()) {
    const isNew = buffer.isNew(master, id);
    const deleted = buffer.isDeleted(master, id);
    const current = model.values(master, id);
    const committed = buffer.committed(master, id) ?? {};
    for (const field of fields) {
      const sum = sums.get(field) ?? ZERO;
      if (isNew) sums.set(field, plus(sum, decimal(current[field])));
      else if (deleted) sums.set(field, plus(sum, decimal(committed[field]), -1n));
      else sums.set(field, plus(plus(sum, decimal(current[field])), decimal(committed[field]), -1n));
    }
  }
  return summaryRow(sums);
}

/** 明细区的汇总行：单据 `recordId` 这个明细的行（含新增行，不含标为删除的行）；没有求和的列或没有行时为 null */
export function detailSummary(model: PageModel, region: ViewRegion, recordId: string | null): FieldValues | null {
  const fields = sumFields(region);
  const entity = region.entity;
  const ids = recordId ? model.detailIds(entity, recordId) : [];
  if (!fields.length || !ids.length) return null;
  const sums = new Map<string, DecimalValue | null>(fields.map(f => [f, ZERO]));
  for (const id of ids.filter(i => !model.buffer.isDeleted(entity, i))) {
    const values = model.values(entity, id);
    for (const field of fields) sums.set(field, plus(sums.get(field)!, decimal(values[field])));
  }
  return summaryRow(sums);
}
