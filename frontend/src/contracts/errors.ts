/**
 * C03 错误：错误体的类型、错误码与 HTTP 状态，以及前端接收错误体时的严格检查（C03 第 1 节"生成和接收的分工"）。
 *
 * 前端收到的错误体必须：`code` 是第 2 节的错误码，`message` 是字符串，`details` 每项九个字段都出现。
 * 不符合时（包括响应不是 JSON），不使用其中的内容，给出带 HTTP 状态码的通用提示。
 */
import { type Infer, array, clientRowId, code, decimalText, key, literal, nullable, object, str } from './schema';

/** C03 第 2 节：每个错误码只对应一个 HTTP 状态 */
export const ERROR_STATUS = {
  INVALID_REQUEST: 400,
  SESSION_REQUIRED: 401,
  SESSION_ROLE_REVOKED: 401,
  LOGIN_FAILED: 401,
  PERMISSION_DENIED: 403,
  CSRF_FAILED: 403,
  ORIGIN_REJECTED: 403,
  ROLE_SELECTION_REQUIRED: 403,
  NOT_FOUND: 404,
  DOCUMENT_BUSY: 409,
  REQUEST_IN_PROGRESS: 409,
  FROZEN_BY_APPROVAL: 409,
  RECONFIRM_REQUIRED: 409,
  ROW_NOT_FOUND: 409,
  APPROVAL_REQUIRED: 409,
  IDEMPOTENCY_KEY_REUSED: 422,
  RULE_REJECTED: 422,
  VALIDATION_FAILED: 422,
  FIELD_NOT_WRITABLE: 422,
  CONFIG_UNAVAILABLE: 503,
  DATABASE_UNAVAILABLE: 503,
  INTERNAL_ERROR: 500
} as const;

export type ErrorCode = keyof typeof ERROR_STATUS;

const ERROR_CODES = Object.keys(ERROR_STATUS) as ErrorCode[];

/** 接收时九个字段都必须出现，用不到的为 null */
export const ErrorDetail = object('ErrorDetail', {
  message: nullable(str),
  entity: nullable(code),
  rowKey: nullable(key),
  clientRowId: nullable(clientRowId),
  field: nullable(str),
  approvalId: nullable(decimalText),
  configType: nullable(str),
  configKey: nullable(str),
  path: nullable(str)
});
export type ErrorDetail = Infer<typeof ErrorDetail>;

export const ErrorResponse = object('ErrorResponse', {
  code: literal(...ERROR_CODES),
  message: str,
  details: array(ErrorDetail)
});
export type ErrorResponse = Infer<typeof ErrorResponse>;

/**
 * HTTP 请求失败。错误体合法时 `code`、`details` 来自后端；不合法或不是 JSON 时 `code` 为 null、`details` 为空，
 * `message` 是带 HTTP 状态码的通用提示。没有收到响应（网络中断）时 `status` 为 0。
 */
export class PlatformError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode | null,
    message: string,
    readonly details: ErrorDetail[] = []
  ) {
    super(message);
    this.name = 'PlatformError';
  }

  /** 冻结它的审批（FROZEN_BY_APPROVAL 的明细中给出的 approvalId，去重，按出现顺序） */
  get frozenBy(): string[] {
    if (this.code !== 'FROZEN_BY_APPROVAL') return [];
    return [...new Set(this.details.map(d => d.approvalId).filter((id): id is string => id !== null))];
  }
}

/** 通用提示：错误体不能用时显示 */
export function genericErrorMessage(status: number) {
  return status === 0
    ? '没有收到服务器的响应，请检查网络后重试'
    : `请求失败（HTTP ${status}），服务器返回的错误信息无法识别`;
}

/**
 * 按 C03 第 1 节严格检查错误体。`bodyText` 为响应的原始文本。
 * 合法时返回带错误码和明细的 PlatformError；不合法时返回带 HTTP 状态码的通用提示。
 */
export function parseErrorResponse(status: number, bodyText: string): PlatformError {
  let data: unknown;
  try {
    data = JSON.parse(bodyText);
  } catch {
    return new PlatformError(status, null, genericErrorMessage(status));
  }
  try {
    const body = ErrorResponse.parse(data);
    return new PlatformError(status, body.code, body.message, body.details);
  } catch {
    return new PlatformError(status, null, genericErrorMessage(status));
  }
}

/** 没有收到响应（网络中断、超时）时的错误 */
export function networkError(): PlatformError {
  return new PlatformError(0, null, genericErrorMessage(0));
}
