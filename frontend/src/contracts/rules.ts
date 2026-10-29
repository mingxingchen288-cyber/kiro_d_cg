/** C07 规则内核接口：规则包、求值请求和结果、前端 Worker 的消息与客户端。后端同名类型在 types.py 的"C07"一节。 */
import { FieldValues, atMostOneIdentity } from './command';
import {
  type Infer,
  type JsonValue,
  array,
  bool,
  clientRowId,
  code,
  dateText,
  decimalText,
  falseValue,
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
  trueValue
} from './schema';

const FieldType = literal('text', 'number', 'date', 'datetime', 'boolean');

export const PackField = object('PackField', {
  type: FieldType,
  scale: optional(nullable(int)),
  role: literal('input', 'calculated', 'system'),
  source: literal('erp', 'own')
});

export const PackRule = object('PackRule', {
  id: code,
  layer: literal('entity', 'operation', 'page'),
  entity: optional(nullable(code)),
  operation: optional(nullable(code)),
  page: optional(nullable(code)),
  category: literal('calc', 'validate', 'ui'),
  order: int,
  serverOnly: bool,
  jdm: code
});

export const JdmGraph = object('JdmGraph', { nodes: array(record(json)), edges: array(record(json)) });

export const RulesPack = object('RulesPack', {
  packId: code,
  version: int,
  coreVersion: str,
  fields: record(record(PackField)),
  rules: array(PackRule),
  jdm: record(JdmGraph)
});
export type RulesPack = Infer<typeof RulesPack>;

export const EvalContext = object('EvalContext', {
  userId: decimalText,
  departmentId: nullable(key),
  role: code,
  today: dateText,
  origin: literal('user', 'approval')
});
export type EvalContext = Infer<typeof EvalContext>;

function exactlyOneIdentity(row: { rowKey?: string | null; clientRowId?: string | null }) {
  return (row.rowKey == null) === (row.clientRowId == null) ? 'rowKey 和 clientRowId 必须且只能给出一个' : null;
}

/** 已保存的行用 rowKey，新增行用 clientRowId；`old` 只列出改过的字段的旧值 */
export const EvalRow = refine(
  object('EvalRow', {
    rowKey: optional(nullable(key)),
    clientRowId: optional(nullable(clientRowId)),
    values: FieldValues,
    old: optional(nullable(FieldValues))
  }),
  exactlyOneIdentity
);
export type EvalRow = Infer<typeof EvalRow>;

export const EvalDocument = object('EvalDocument', { entity: code, master: EvalRow, details: record(array(EvalRow)) });
export type EvalDocument = Infer<typeof EvalDocument>;

export const ChangedRow = object('ChangedRow', {
  entity: code,
  rowKey: optional(nullable(key)),
  clientRowId: optional(nullable(clientRowId)),
  op: literal('add', 'modify', 'delete'),
  fields: array(str)
});
export type ChangedRow = Infer<typeof ChangedRow>;

export const EvaluationRequest = object('EvaluationRequest', {
  purpose: literal('operation'),
  operation: optional(nullable(code)),
  page: optional(nullable(code)),
  phase: literal('preview', 'commit'),
  context: EvalContext,
  document: EvalDocument,
  changed: array(ChangedRow),
  data: record(json)
});
export type EvaluationRequest = Infer<typeof EvaluationRequest>;

export const FieldState = object('FieldState', {
  editable: optional(nullable(bool)),
  required: optional(nullable(bool))
});
export type FieldState = Infer<typeof FieldState>;

export const RowStyle = object('RowStyle', { row: json, cells: record(json) });
export type RowStyle = Infer<typeof RowStyle>;

export const EvalRowResult = refine(
  object('EvalRowResult', {
    entity: code,
    rowKey: optional(nullable(key)),
    clientRowId: optional(nullable(clientRowId)),
    computed: FieldValues,
    fields: record(FieldState),
    style: RowStyle
  }),
  exactlyOneIdentity
);
export type EvalRowResult = Infer<typeof EvalRowResult>;

const effectShape = {
  rule: code,
  message: str,
  entity: optional(nullable(code)),
  rowKey: optional(nullable(key)),
  clientRowId: optional(nullable(clientRowId)),
  field: optional(nullable(str))
};

export const PromptEffect = refine(
  object('PromptEffect', { kind: literal('prompt'), ...effectShape }),
  atMostOneIdentity
);
export const RejectEffect = refine(
  object('RejectEffect', { kind: literal('reject'), ...effectShape }),
  atMostOneIdentity
);
export const RuleEffect = tagged('kind', { prompt: PromptEffect, reject: RejectEffect });
export type RuleEffect = Infer<typeof RuleEffect>;

export const EvalError = object('EvalError', {
  code: literal('PACK_INVALID', 'INPUT_INVALID', 'EVAL_FAILED'),
  message: str
});

/** 计算和规则的结果：`rows`、`effects` 总会出现 */
export const EvalComputed = object('EvalComputed', {
  ok: trueValue,
  rows: array(EvalRowResult),
  effects: array(RuleEffect)
});
export type EvalComputed = Infer<typeof EvalComputed>;

/** 规则包或请求本身有问题，不返回部分结果 */
export const EvalFailure = object('EvalFailure', { ok: falseValue, error: EvalError });
export type EvalFailure = Infer<typeof EvalFailure>;

export const EvaluationResult = oneOf(EvalComputed, EvalFailure);
export type EvaluationResult = Infer<typeof EvaluationResult>;

// ---- 第 5 节 前端 Worker（Worker 脚本和客户端由 rules-core 交付在 rules-core/dist/web/）

export interface CalcPack {
  packId: string;
  version: number;
  /** 规则包（第 1 节）JSON 的 UTF-8 字节 */
  bytes: ArrayBuffer | Uint8Array;
}

/** C11 的 `ShellApi.calc`；与 rules-core 交付的 `createCalcWorkerClient` 返回值的接口相同 */
export interface CalcWorkerClient {
  /** 加载规则包，同一 packId + version 只加载一次，返回句柄；不合法时以带 `code` 的错误拒绝 */
  load(pack: CalcPack): Promise<number>;
  /** request 为第 2 节的 JSON 文本，结果为第 3 节的 JSON 文本 */
  evaluate(handle: number, request: string): Promise<string>;
  dispose(handle: number): void;
  terminate(): void;
}

/** 主线程与 Worker 之间的消息（第 5 节）；由 rules-core 的客户端收发，页面不直接使用 */
export type WorkerRequest =
  | { id: number; type: 'load'; packId: string; version: number; bytes: ArrayBuffer }
  | { id: number; type: 'evaluate'; handle: number; request: string }
  | { type: 'dispose'; handle: number };

export type WorkerResponse =
  | { id: number; ok: true; handle: number }
  | { id: number; ok: true; result: string }
  | { id: number; ok: false; error: { code: string; message: string } };

export type { JsonValue };
