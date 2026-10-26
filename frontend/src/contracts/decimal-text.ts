/**
 * 十进制文本（C01 第 2、3 节）：解析、格式化和数值一致的判定。
 *
 * 精确数值在 JSON 中都是 `^-?[0-9]+(\.[0-9]+)?$` 格式的字符串。这里用 BigInt 表示，全程不经过二进制浮点。
 * 后端的同名实现在 backend/src/cost_platform/contracts/decimal_text.py，三端用 C01 的同一批样例测试。
 */

const PATTERN = /^(-?)([0-9]+)(?:\.([0-9]+))?$/;

/** 数值一致判定比较的小数位数（C01 第 3 节）。 */
const CONSISTENT_PLACES = 15;

/** 值为 digits / 10^scale。 */
export interface DecimalValue {
  readonly digits: bigint;
  readonly scale: number;
}

export class DecimalTextError extends Error {
  constructor(value: unknown) {
    super(`不是十进制文本：${JSON.stringify(value)}`);
    this.name = 'DecimalTextError';
  }
}

/** 返回 boolean 而不是类型谓词：不合法的字符串返回 false 时，不能把 `string | null` 收窄成 `null`。 */
export function isDecimalText(value: unknown): boolean {
  return typeof value === 'string' && PATTERN.test(value);
}

function match(text: unknown): RegExpExecArray {
  const found = typeof text === 'string' ? PATTERN.exec(text) : null;
  if (!found) throw new DecimalTextError(text);
  return found;
}

/** 把十进制文本解析为 DecimalValue；格式不合法时抛 DecimalTextError。 */
export function parseDecimal(text: string): DecimalValue {
  const [, sign, integer, fraction = ''] = match(text);
  const digits = BigInt(integer + fraction);
  return { digits: sign ? -digits : digits, scale: fraction.length };
}

/** 把 DecimalValue 格式化为十进制文本：保留原有的小数位，零不带负号。 */
export function formatDecimal(value: DecimalValue): string {
  if (!Number.isInteger(value.scale) || value.scale < 0) throw new RangeError(`小数位数不合法：${value.scale}`);
  const negative = value.digits < 0n;
  let text = (negative ? -value.digits : value.digits).toString();
  if (value.scale > 0) {
    text = text.padStart(value.scale + 1, '0');
    text = `${text.slice(0, -value.scale)}.${text.slice(-value.scale)}`;
  }
  return negative ? `-${text}` : text;
}

/** 正负号、整数部分、截断（不舍入）到 15 位的小数部分；截断后为零的数不区分正负。 */
function consistencyKey(text: string): string {
  const [, sign, rawInteger, rawFraction = ''] = match(text);
  const integer = rawInteger.replace(/^0+/, '') || '0';
  const fraction = rawFraction.slice(0, CONSISTENT_PLACES).padEnd(CONSISTENT_PLACES, '0');
  const isZero = integer === '0' && /^0+$/.test(fraction);
  return `${sign && !isZero ? '-' : ''}${integer}.${fraction}`;
}

/** C01 第 3 节：两个数值是否一致。都为空时一致，一方为空时不一致；文本格式不合法时抛 DecimalTextError。 */
export function numbersConsistent(a: string | null, b: string | null): boolean {
  if (a === null || b === null) {
    if (a !== null) match(a);
    if (b !== null) match(b);
    return a === null && b === null;
  }
  return consistencyKey(a) === consistencyKey(b);
}
