/** C02 命令与结果。后端同名类型在 backend/src/cost_platform/contracts/types.py 的"C02 命令与结果"一节。 */
import {
  type Infer,
  array,
  businessValue,
  clientRowId,
  code,
  decimalText,
  int,
  json,
  key,
  literal,
  nullable,
  object,
  oneOf,
  optional,
  record,
  refine,
  str,
  tagged,
  trueValue,
  uuid
} from './schema';

export const FieldValues = record(businessValue);
export type FieldValues = Infer<typeof FieldValues>;
export type FieldValue = FieldValues[string];

/** 新增行；复制出的行带 `copyOf`（源行的主键，同一实体），不可写的复制字段由后端取源行的值（C02 第 1 节） */
export const MasterAdd = object('MasterAdd', {
  op: literal('add'),
  clientRowId,
  copyOf: optional(key),
  values: FieldValues
});
export const MasterModify = object('MasterModify', { op: literal('modify'), rowKey: key, changes: FieldValues });
/** 删除主表行，连同它的全部明细 */
export const MasterDelete = object('MasterDelete', { op: literal('delete'), rowKey: key });
/** 主表不改、只改明细 */
export const MasterNone = object('MasterNone', { op: literal('none'), rowKey: key });
export const MasterChange = tagged('op', {
  add: MasterAdd,
  modify: MasterModify,
  delete: MasterDelete,
  none: MasterNone
});
export type MasterChange = Infer<typeof MasterChange>;

export const DetailAdd = object('DetailAdd', {
  entity: code,
  op: literal('add'),
  clientRowId,
  copyOf: optional(key),
  values: FieldValues
});
export const DetailModify = object('DetailModify', {
  entity: code,
  op: literal('modify'),
  rowKey: key,
  changes: FieldValues
});
export const DetailDelete = object('DetailDelete', { entity: code, op: literal('delete'), rowKey: key });
export const DetailChange = tagged('op', { add: DetailAdd, modify: DetailModify, delete: DetailDelete });
export type DetailChange = Infer<typeof DetailChange>;

/** 一张单据的修改 */
export const DocumentPatch = object('DocumentPatch', {
  entity: code,
  master: MasterChange,
  details: array(DetailChange)
});
export type DocumentPatch = Infer<typeof DocumentPatch>;

export const Command = object('Command', {
  requestKey: uuid,
  page: nullable(code),
  operation: code,
  documents: array(DocumentPatch),
  params: record(json)
});
export type Command = Infer<typeof Command>;

export const FrozenMark = object('FrozenMark', { approvalId: decimalText });
export type FrozenMark = Infer<typeof FrozenMark>;

/** 写入的行或计算带出变化的行：实体的全部字段 */
export const ResultRow = object('ResultRow', {
  entity: code,
  rowKey: key,
  clientRowId: optional(nullable(clientRowId)),
  values: FieldValues,
  frozen: nullable(FrozenMark)
});
export type ResultRow = Infer<typeof ResultRow>;

export const DeletedRow = object('DeletedRow', { entity: code, rowKey: key, deleted: trueValue });
export type DeletedRow = Infer<typeof DeletedRow>;

function atMostOneIdentity(row: { rowKey?: string | null; clientRowId?: string | null }) {
  return row.rowKey != null && row.clientRowId != null ? 'rowKey 和 clientRowId 最多给出一个' : null;
}

export const Prompt = refine(
  object('Prompt', {
    rule: code,
    message: str,
    entity: optional(nullable(code)),
    rowKey: optional(nullable(key)),
    clientRowId: optional(nullable(clientRowId)),
    field: optional(nullable(str))
  }),
  atMostOneIdentity
);
export type Prompt = Infer<typeof Prompt>;

export const SkippedRow = object('SkippedRow', { entity: code, rowKey: key, reason: literal('ROW_NOT_FOUND') });

export const RecordRef = object('RecordRef', { entity: code, recordKey: key });
export type RecordRef = Infer<typeof RecordRef>;

export const ApprovalStatus = literal('pending', 'approved', 'rejected', 'withdrawn');

export const ApprovalRef = object('ApprovalRef', {
  approvalId: decimalText,
  document: RecordRef,
  status: ApprovalStatus,
  level: int,
  flows: array(code)
});
export type ApprovalRef = Infer<typeof ApprovalRef>;

export const CommandResult = object('CommandResult', {
  requestKey: uuid,
  outcome: literal('saved', 'unchanged', 'approvalSubmitted', 'approvalProcessed'),
  rows: array(oneOf(ResultRow, DeletedRow)),
  idMap: record(key, clientRowId),
  prompts: array(Prompt),
  skipped: array(SkippedRow),
  approvals: array(ApprovalRef)
});
export type CommandResult = Infer<typeof CommandResult>;

export { atMostOneIdentity };
