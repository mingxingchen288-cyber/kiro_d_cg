/**
 * 入口条件、关联条件、取值中可以插入的参数（C06 7.2）。插入方式沿用旧系统 ApprovalConditionEditor 的
 * "来源 / 表 / 字段 + 插入"：选来源，再选表格和字段，点"插入参数"把参数接到文本末尾。
 */
import type { PageTable } from '../core/catalog';
import type { FlowParam } from '../core/types';

export type ParamSource = 'new' | 'old' | 'master_new' | 'master_old' | 'user' | 'row' | 'params' | 'context';

export type SourceOption = {
  label: string;
  value: ParamSource;
};

/** 入口条件、关联条件可用的来源；取值另外可以用 `:row_`、`:params_` */
export function sourceOptions(forValue: boolean): SourceOption[] {
  const base: SourceOption[] = [
    { label: '本次待审值（:new_）', value: 'new' },
    { label: '送审前原值（:old_）', value: 'old' },
    { label: '主表待审值（:master_new_）', value: 'master_new' },
    { label: '主表原值（:master_old_）', value: 'master_old' },
    { label: '发起人员', value: 'user' },
    { label: '本行操作 / 单据主键', value: 'context' }
  ];
  if (forValue) {
    base.push({ label: '修改表当前值（:row_）', value: 'row' }, { label: '审批流参数（:params_）', value: 'params' });
  }
  return base;
}

/** 选了来源后是否还要选表格 */
export function needsTable(source: ParamSource) {
  return source === 'new' || source === 'old';
}

export type FieldChoice = {
  label: string;
  value: string;
};

/**
 * 来源下可以选的字段：`new`、`old` 取所选表格的字段；`master_*` 取主表实体的字段；`row` 取修改表的列；
 * `params` 取本审批流的参数；`user`、`context` 为固定项。
 */
export function fieldChoices(
  source: ParamSource,
  tables: PageTable[],
  tableEntity: string | null,
  rowColumns: string[],
  params: FlowParam[]
): FieldChoice[] {
  const fieldsOf = (table: PageTable | undefined) =>
    (table?.fields ?? []).map(f => ({ label: `${f.label} · ${f.name}`, value: f.name }));
  switch (source) {
    case 'new':
    case 'old':
      return fieldsOf(tables.find(t => t.entity === tableEntity));
    case 'master_new':
    case 'master_old':
      return fieldsOf(tables.find(t => t.isMaster));
    case 'user':
      return [
        { label: '人员编号 · :user_id', value: 'id' },
        { label: '所在部门 · :user_departmentId', value: 'departmentId' }
      ];
    case 'context':
      return [
        { label: '本行操作（added / modified / deleted）· :operation', value: 'operation' },
        { label: '单据主键 · :billId', value: 'billId' }
      ];
    case 'row':
      return rowColumns.map(c => ({ label: c, value: c }));
    case 'params':
      return params.map(p => ({ label: `${p.label || p.name} · ${p.name}`, value: p.name }));
    default:
      return [];
  }
}

/** 参数文字，例如 `:new_PRICE`、`:master_old_USESTATUS`、`:user_departmentId`、`:billId` */
export function paramToken(source: ParamSource, field: string) {
  if (source === 'context') return `:${field}`;
  return `:${source}_${field}`;
}

/** 接到文本末尾（同旧系统） */
export function insertToken(text: string, token: string) {
  return `${text}${token}`;
}
