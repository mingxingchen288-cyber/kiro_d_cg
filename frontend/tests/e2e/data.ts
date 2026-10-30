/**
 * 端到端用例准备数据、核对结果用的纯函数（不引用 Playwright，用 vitest 测：tests/e2e/data.test.ts）。
 *
 * - 测试成本单：按一张已有的成本单生成"新增"命令（只带新单据能写的字段），明细只带单价等于物料清单执行价的行，
 *   保存时不触发成本明细改价审批（COST_TO_GOODS：单价与 NVL(ZX_PRICE, PRICE) 不同时提交审批并冻结单据）。
 * - 备注带 PF_TEST 标记，跑完用只读查询核对没有残留。
 */
import type { FieldValue, FieldValues } from '../../src/contracts/command';
import type { PageView, ViewField, ViewRegion } from '../../src/contracts/page-view';
import { fieldWritable, formatScale } from '../../src/modules/page/fields';

/** 测试成本单备注的标记 */
export const MARKER = 'PF_TEST';

export type Row = { entity: string; rowKey?: string; values: FieldValues };
export type DocRecord = { master: Row; details: Record<string, Row[]> };

/** 两个十进制文本是否相等（"75" 与 "75.00" 相等）；任一为空时不相等 */
export function samePrice(a: FieldValue | undefined, b: FieldValue | undefined) {
  if (a === null || a === undefined || b === null || b === undefined || a === '' || b === '') return false;
  const norm = (v: FieldValue) => {
    const text = String(v).trim();
    if (!/^-?\d+(?:\.\d+)?$/.test(text)) return text;
    const [int, frac = ''] = text.replace(/^(-?)0+(?=\d)/, '$1').split('.');
    const trimmed = frac.replace(/0+$/, '');
    return trimmed ? `${int}.${trimmed}` : int;
  };
  return norm(a) === norm(b);
}

/** 新单据能写的字段（与页面上新增行相同的判断），去掉空值和 `skip` 里的字段 */
export function writableValues(region: ViewRegion, values: FieldValues, skip: string[] = []) {
  const out: FieldValues = {};
  for (const field of region.fields) {
    const value = values[field.name];
    const wanted = value !== null && value !== undefined && !skip.includes(field.name);
    if (wanted && fieldWritable(region, field, values, true)) out[field.name] = value;
  }
  return out;
}

export interface CopyPlan {
  /** 保存命令中的单据（主表新增、明细新增） */
  document: { entity: string; master: Record<string, unknown>; details: Array<Record<string, unknown>> };
  masterId: string;
  /** 来源明细的主键 → 新行的临时编号 */
  rows: Map<string, string>;
}

/**
 * 按来源单据生成"复制为新单据"的命令。`keep` 决定带哪些明细行；`master` 覆盖主表的值（备注等）。
 * 临时编号由 `tmp()` 生成，命令结果的 idMap 把它们换成新主键。
 */
export function copyPlan(
  view: PageView,
  source: DocRecord,
  options: { keep: (row: Row) => boolean; master?: FieldValues; tmp: () => string }
): CopyPlan {
  const masterId = options.tmp();
  const rows = new Map<string, string>();
  const details: Array<Record<string, unknown>> = [];
  for (const region of view.details) {
    for (const row of (source.details[region.entity] ?? []).filter(options.keep)) {
      const id = options.tmp();
      rows.set(row.rowKey!, id);
      details.push({ entity: region.entity, op: 'add', clientRowId: id, values: writableValues(region, row.values) });
    }
  }
  const values = { ...writableValues(view.master, source.master.values), ...options.master };
  return {
    document: { entity: view.master.entity, master: { op: 'add', clientRowId: masterId, values }, details },
    masterId,
    rows
  };
}

/** 单价等于物料清单执行价（`zx`：物料 → T_COST_GOODS_PRICE_V.ZX_PRICE）的明细行 */
export function pricedRow(zx: Map<string, FieldValue>) {
  return (row: Row) => samePrice(row.values.PRICE, zx.get(String(row.values.GOODSID)));
}

/** WP-15：最多保留 8 位小数，按第 9 位四舍五入（负数按绝对值） */
export function wp15(text: string) {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return text;
  const [, sign, integer, fraction = ''] = match;
  if (fraction.length <= 8) return text;
  const digits = BigInt(integer + fraction.slice(0, 8)) + (Number(fraction[8]) >= 5 ? 1n : 0n);
  const padded = digits.toString().padStart(9, '0');
  return `${sign}${padded.slice(0, -8)}.${padded.slice(-8)}`;
}

/** 复制对话框中明细行的文字（CopyDialog.vue 的 rowLabel：除主键外前三个可见字段，按小数位显示） */
export function copyRowLabel(region: { primaryKey: string; fields: ViewField[] }, values: FieldValues) {
  return region.fields
    .filter(f => f.visible && f.name !== region.primaryKey)
    .slice(0, 3)
    .map(f =>
      values[f.name] === null || values[f.name] === undefined ? '' : formatScale(String(values[f.name]), f.scale)
    )
    .filter(Boolean)
    .join(' / ');
}

/** 汇总行应显示的文字：后端 aggregates（或前端求和）按字段的小数位显示 */
export function summaryTexts(fields: ViewField[], sums: FieldValues) {
  const out: Record<string, string> = {};
  for (const field of fields) {
    const value = sums[field.name];
    if (value !== null && value !== undefined) out[field.name] = formatScale(String(value), field.scale);
  }
  return out;
}
