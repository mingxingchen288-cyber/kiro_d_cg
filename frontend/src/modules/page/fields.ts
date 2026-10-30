/**
 * 字段的规则：哪些字段能写进命令、单元格能不能编辑、新增行的默认值（FP-15、C06 第 2 节）、数值的显示小数位、
 * 对比的显示（FP-15，与旧系统 useMetaColumns.ts 的 renderCompareValue 相同）。不引用 AG Grid 和 Vue。
 */
import type { FieldValue, FieldValues } from '../../contracts/command';
import type { CompareResult, CurrentUser, RoleRef } from '../../contracts/http';
import type { FieldDefault, PageView, ViewField, ViewRegion } from '../../contracts/page-view';

export const MASTER_GRID = 'master';

/** 页面中的区域：主表区为 `master`，明细区为明细实体编码（也用作个人列配置中 grids 的键） */
export function regionKey(view: PageView, entity: string) {
  return entity === view.master.entity ? MASTER_GRID : entity;
}

export function regionOf(view: PageView, entity: string): ViewRegion | undefined {
  return entity === view.master.entity ? view.master : view.details.find(d => d.entity === entity);
}

export function fieldOf(view: PageView, entity: string, field: string): ViewField | undefined {
  return regionOf(view, entity)?.fields.find(f => f.name === field);
}

export function primaryKeyOf(view: PageView, entity: string) {
  return regionOf(view, entity)?.primaryKey ?? '';
}

export function parentKeyOf(view: PageView, entity: string) {
  const region = regionOf(view, entity);
  return region && 'parentKey' in region ? region.parentKey : null;
}

/** 这一行是不是 ERP 行（C05 `erpRow`：该列等于 `value` 的行）。新增行由平台设为本地行 */
export function isErpRow(region: ViewRegion, values: FieldValues, isNew: boolean) {
  if (isNew || !region.erpRow) return false;
  return String(values[region.erpRow.column] ?? '') === region.erpRow.value;
}

/**
 * 主键、主从关联字段、计算字段、`erpRow.column` 都不能写；ERP 列在没有 `erpRow` 的实体上不能写，有时只在 ERP 行上不能写。
 * 区域的 `canModify` 为 false（角色没有 `<区域>:modify`，C05 v8）时，已经保存的行整行不能写；新增、复制出的行不受影响。
 */
function writableOnRow(region: ViewRegion, field: ViewField, values: FieldValues, isNew: boolean) {
  if (!isNew && region.canModify === false) return false;
  if (field.name === region.primaryKey) return false;
  if ('parentKey' in region && field.name === region.parentKey) return false;
  if (field.calculated) return false;
  if (region.erpRow && field.name === region.erpRow.column) return false;
  if (field.source === 'erp') return Boolean(region.erpRow) && !isErpRow(region, values, isNew);
  return true;
}

/**
 * 字段在这一行上是否由用户填写（C02 第 1 节、C06 第 2 节）：主键、主从关联字段、计算字段、`erpRow.column` 不能；
 * ERP 列在没有 `erpRow` 的实体上都不能，有 `erpRow` 时只在 ERP 行上不能；角色不能修改这个区域时已经保存的行都不能；
 * 其余按页面视图的 `editable`。
 */
export function fieldEditable(region: ViewRegion, field: ViewField, values: FieldValues, isNew: boolean) {
  return field.editable && writableOnRow(region, field, values, isNew);
}

/**
 * 字段能否写进命令：用户能填写的字段（fieldEditable），以及不能直接填写、但随 Lookup 回填写库的字段
 * （C05 `fillWritable`，例如成本核算主表的产品名称；旧系统 useLookupDialog.ts 回填不看目标列能否编辑，
 * DynamicDataService 照样写入）。
 */
export function fieldWritable(region: ViewRegion, field: ViewField, values: FieldValues, isNew: boolean) {
  return (field.editable || Boolean(field.fillWritable)) && writableOnRow(region, field, values, isNew);
}

/**
 * 复制出的行中，不可写的复制字段能否写进命令（C02 `copyOf`，FP-13）：可见、能写进表的字段（不是主键、关联字段、
 * 计算字段、`erpRow.column`，没有 `erpRow` 时不是 ERP 列），后端取源行的值。同旧系统复制源行全部字段、新增行提交全部字段。
 */
export function fieldCopyable(region: ViewRegion, field: ViewField) {
  return field.visible && writableOnRow(region, field, {}, true);
}

// ---- 默认值（FP-15，C06 第 2 节；旧系统 useWorkingSetStore.ts 的 resolveColumnDefaultValue）

export interface DefaultContext {
  user: CurrentUser | null;
  role: RoleRef | null;
  now: Date;
}

const pad = (n: number) => String(n).padStart(2, '0');

export function localDate(now: Date) {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function localDateTime(now: Date) {
  return `${localDate(now)}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

/** `options` 写法的下拉值；没有时为 null */
export function optionValues(field: ViewField): string[] | null {
  const config = field.default;
  if (config?.type !== 'options' || !Array.isArray(config.value)) return null;
  return config.value.map(v => String(v));
}

function builtinValue(code: string, field: ViewField, ctx: DefaultContext): FieldValue {
  switch (code) {
    case 'currentUserId':
      return ctx.user?.userId ?? null;
    case 'currentUserName':
      return ctx.user?.displayName ?? null;
    case 'currentDeptId':
      return ctx.user?.departmentId ?? null;
    case 'currentRoleCode':
      return ctx.role?.code ?? null;
    case 'currentTime':
      return field.type === 'date' ? localDate(ctx.now) : localDateTime(ctx.now);
    // currentDeptName：C09 的 CurrentUser 没有部门名称，取不到时为空（契约缺口第 3 项）
    default:
      return null;
  }
}

function defaultValue(config: FieldDefault | null | undefined, field: ViewField, ctx: DefaultContext): FieldValue {
  if (!config) return field.type === 'number' ? '0' : null;
  if (config.type === 'builtin') return builtinValue(String(config.value), field, ctx);
  if (config.type === 'options') return optionValues(field)?.[0] ?? null;
  const value = config.value;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  return typeof value === 'number' ? String(value) : null;
}

/** 新增行的初始值：按字段的 `default`；没有配置时数值字段为 0、其他为空；主键和关联字段为空 */
export function newRowValues(region: ViewRegion, ctx: DefaultContext): FieldValues {
  const values: FieldValues = {};
  for (const field of region.fields) {
    const isKey = field.name === region.primaryKey || ('parentKey' in region && field.name === region.parentKey);
    values[field.name] = isKey ? null : defaultValue(field.default, field, ctx);
  }
  if (region.erpRow) values[region.erpRow.column] = region.erpRow.localValue;
  return values;
}

// ---- 显示

/** 十进制文本按小数位四舍五入显示（只用于显示，C05 `scale`）；不是十进制文本时原样返回 */
export function formatScale(text: string, scale: number | null): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match || scale === null) return text;
  const [, sign, integer, fraction = ''] = match;
  if (fraction.length <= scale) return `${sign}${integer}${scale > 0 ? `.${fraction.padEnd(scale, '0')}` : ''}`;
  const digits = BigInt(integer + fraction.slice(0, scale));
  const roundUp = Number(fraction[scale]) >= 5;
  const rounded = (digits + (roundUp ? 1n : 0n)).toString().padStart(scale + 1, '0');
  const intPart = scale > 0 ? rounded.slice(0, -scale) : rounded;
  const fracPart = scale > 0 ? `.${rounded.slice(-scale)}` : '';
  const isZero = /^0*$/.test(intPart + fracPart.slice(1));
  return `${sign && !isZero ? '-' : ''}${intPart}${fracPart}`;
}

export function displayText(field: ViewField, value: FieldValue, dict?: Map<string, string>): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (dict?.has(value)) return dict.get(value)!;
  if (field.type === 'number') return formatScale(value, field.scale);
  if (field.type === 'datetime') return value.replace('T', ' ');
  return value;
}

/** 编辑框给出的文本转成字段值：空为 null；数值去掉首尾空白，不是十进制文本时返回 undefined（不接受） */
export function parseInput(field: ViewField, input: unknown): FieldValue | undefined {
  if (input === null || input === undefined) return null;
  if (typeof input === 'boolean') return field.type === 'boolean' ? input : String(input);
  const text = String(input).trim() === '' ? '' : String(input);
  if (text === '') return null;
  if (field.type === 'number') {
    const trimmed = text.trim();
    return /^-?[0-9]+(\.[0-9]+)?$/.test(trimmed) ? trimmed : undefined;
  }
  if (field.type === 'datetime') return text.trim().replace(' ', 'T');
  return text;
}

// ---- 对比（与旧系统相同：上升红色 ↑，下降绿色 ↓）

export const COMPARE_UP_COLOR = '#e53935';
export const COMPARE_DOWN_COLOR = '#43a047';

export interface CompareDisplay {
  arrow: '↑' | '↓';
  color: string;
  text: string;
}

/**
 * 字段的 `compare.format` 为 value 时只显示差值，percent 时只显示百分比，both 时都显示（"0.30 (8.57%)"）；
 * 页面视图没有给出 format 时按 both（契约缺口第 2 项）。差值为 0 或没有差值时不显示箭头和差值。
 */
export function compareDisplay(field: ViewField, compare: CompareResult | undefined): CompareDisplay | null {
  if (!compare?.diff || /^-?0+(\.0+)?$/.test(compare.diff)) return null;
  const format = field.compare?.format ?? 'both';
  const up = !compare.diff.startsWith('-');
  const diff = compare.diff.replace(/^-/, '');
  const percent = compare.percent === null ? null : `${compare.percent.replace(/^-/, '')}%`;
  let text = diff;
  if (format === 'percent') text = percent ?? '';
  else if (format === 'both' && percent) text = `${diff} (${percent})`;
  if (!text) return null;
  return { arrow: up ? '↑' : '↓', color: up ? COMPARE_UP_COLOR : COMPARE_DOWN_COLOR, text };
}
