/**
 * 操作表单（C06 第 4、6 节）中"名称=值"多行文本、逗号列表与配置结构的互转，以及新动作的预填。
 */
import type { ActionStep } from '../core/types';

export const toLines = (map: Record<string, string> | undefined) =>
  Object.entries(map ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');

export const fromLines = (text: string): Record<string, string> =>
  Object.fromEntries(
    text
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(line => line.includes('='))
      .map(line => [line.slice(0, line.indexOf('=')).trim(), line.slice(line.indexOf('=') + 1).trim()])
  );

export const toList = (items: string[] | undefined) => (items ?? []).join(', ');
export const fromList = (text: string) =>
  text
    .split(/[,，]/)
    .map(v => v.trim())
    .filter(Boolean);

export const ACTION_OPTIONS: Array<{ label: string; value: ActionStep['action'] }> = [
  { label: '按计算规则重算（recalculate）', value: 'recalculate' },
  { label: '把来源的值写到目标（updateTargets）', value: 'updateTargets' },
  { label: '找到记录并更新（updateRecords）', value: 'updateRecords' },
  { label: '按 SQL 替换选中单据的明细（replaceDetails）', value: 'replaceDetails' },
  { label: '按 SQL 找到记录并更新，不用选中行（updateRows）', value: 'updateRows' },
  { label: '逃生舱（escapeHatch）', value: 'escapeHatch' }
];

export function newAction(kind: ActionStep['action']): ActionStep {
  switch (kind) {
    case 'recalculate':
      return { action: 'recalculate', target: 'targets' };
    case 'updateTargets':
      return { action: 'updateTargets', targets: [{ entity: '', fieldMapping: [] }] };
    case 'updateRecords':
      return { action: 'updateRecords', find: { kind: 'relationKey', entity: '', targetKey: '', sourceKey: '', rows: 'all' }, fieldMapping: [] };
    case 'replaceDetails':
      return { action: 'replaceDetails', entity: '', sql: '', binds: {} };
    case 'updateRows':
      return { action: 'updateRows', entity: '', sql: '', recordKeyColumn: '', rowKeyColumns: [] };
    default:
      return { action: 'escapeHatch', operation: '' };
  }
}

/** 写入的表和列：`T_COST_PINGGU: PRICE, AMOUNT` 每行一个表（逃生舱登记） */
export const writesToText = (writes: Record<string, string[]> | undefined) =>
  Object.entries(writes ?? {})
    .map(([table, columns]) => `${table}: ${columns.join(', ')}`)
    .join('\n');

export const writesFromText = (text: string): Record<string, string[]> =>
  Object.fromEntries(
    text
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(line => line.includes(':'))
      .map(line => [line.slice(0, line.indexOf(':')).trim(), fromList(line.slice(line.indexOf(':') + 1))])
  );
