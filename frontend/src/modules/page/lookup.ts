/**
 * Lookup（FP-15，C06 第 3 节、C09 第 4 节）：对话框打开时先用空关键字查询；响应的 `keywordSearch` 为 false 时不显示
 * 搜索框；`filter` 按当前行的字段或点开的单元格的值过滤，值为空时不过滤；多选时同一个回填字段的值用英文逗号连接；
 * `fillBack` 为 false 时只查看、不回填，只读的单元格也能打开。对照旧系统 LookupDialog.vue、useLookupDialog.ts。
 */
import type { FieldValue, FieldValues } from '../../contracts/command';
import type { LookupSearchRequest } from '../../contracts/http';
import type { LookupSetting } from '../../contracts/page-view';

/** 旧系统一次取 500 行（LookupDialog.vue 的 pageSize） */
export const LOOKUP_PAGE_SIZE = 500;

export const fillsBack = (setting: LookupSetting) => setting.fillBack !== false;

/** 能否打开：回填的 Lookup 要求单元格可编辑；只查看的 Lookup 总能打开 */
export function canOpenLookup(setting: LookupSetting, editable: boolean) {
  return !fillsBack(setting) || editable;
}

export function lookupRequest(
  setting: LookupSetting,
  keyword: string,
  row: FieldValues,
  cellValue: FieldValue,
  startRow = 0
): LookupSearchRequest {
  const request: LookupSearchRequest = { keyword, startRow, endRow: startRow + LOOKUP_PAGE_SIZE };
  if (setting.filter) {
    const raw = setting.filter.from === 'cell' ? cellValue : row[setting.filter.field ?? ''];
    const value = raw === null || raw === undefined || raw === '' ? null : String(raw);
    if (value !== null) request.filter = { column: setting.filter.column, value };
  }
  return request;
}

/** 选中的 Lookup 行按回填映射得出要写入本行的值；多选时用英文逗号连接 */
export function lookupFill(setting: LookupSetting, selected: FieldValues[]): FieldValues {
  const values: FieldValues = {};
  for (const [pageField, lookupColumn] of Object.entries(setting.fill)) {
    const picked = selected.map(row => row[lookupColumn] ?? null);
    if (setting.multiple) {
      const texts = picked.filter((v): v is string | boolean => v !== null).map(v => String(v));
      values[pageField] = texts.length ? texts.join(',') : null;
    } else {
      values[pageField] = picked[0] ?? null;
    }
  }
  return values;
}
