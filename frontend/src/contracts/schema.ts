/**
 * 契约类型的运行时检查（CT-02 前端部分）。
 *
 * 每个契约类型写成一个 schema，TypeScript 类型由 schema 推出（`Infer`），同一处定义同时给出类型和检查。
 * 检查是严格的，与后端 `parse_wire` 一致：只认 camelCase 字段名，不允许出现没定义的字段，必须写的字段不能缺，
 * 整数和是非必须是 JSON 的数字和布尔（C01 第 1 节）。`parse` 返回一份新值，内容与输入相同，所以"解析后再转回 JSON
 * 内容不变"可以直接比较。
 *
 * `object` 的第一个参数是后端 `backend/src/cost_platform/contracts/types.py` 中对应的类名，契约测试按它核对两端的字段名。
 */

export class ContractViolation extends Error {
  constructor(
    readonly path: string,
    readonly reason: string
  ) {
    super(`${path || '(根)'}：${reason}`);
    this.name = 'ContractViolation';
  }
}

export interface Schema<T, O extends boolean = false> {
  /** 为 true 时，所在对象中可以不写这个字段 */
  readonly optional: O;
  parse(input: unknown, path?: string): T;
}

export type Infer<S> = S extends Schema<infer T, boolean> ? T : never;

type Simplify<T> = { [K in keyof T]: T[K] } & {};
type Shape = Record<string, Schema<unknown, boolean>>;
type RequiredKeys<S extends Shape> = { [K in keyof S]: S[K] extends Schema<unknown, true> ? never : K }[keyof S];
type OptionalKeys<S extends Shape> = Exclude<keyof S, RequiredKeys<S>>;
export type ObjectOf<S extends Shape> = Simplify<
  { [K in RequiredKeys<S>]: Infer<S[K]> } & { [K in OptionalKeys<S>]?: Infer<S[K]> }
>;

function describe(value: unknown) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return '数组';
  return typeof value;
}

function scalar<T>(check: (value: unknown) => boolean, expected: string): Schema<T> {
  return {
    optional: false,
    parse(input, path = '') {
      if (!check(input))
        throw new ContractViolation(path, `应为${expected}，实际是 ${JSON.stringify(input) ?? describe(input)}`);
      return input as T;
    }
  };
}

function pattern(regex: RegExp, expected: string) {
  return scalar<string>(value => typeof value === 'string' && regex.test(value), expected);
}

const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';

export const str = scalar<string>(value => typeof value === 'string', '字符串');
/** 编码、主键：非空字符串 */
export const code = scalar<string>(value => typeof value === 'string' && value.length > 0, '非空字符串');
export const key = code;
/** C01 第 2 节的十进制文本 */
export const decimalText = pattern(/^-?[0-9]+(\.[0-9]+)?$/, '十进制文本');
/** 小写 UUID（C01 第 5 节） */
export const uuid = pattern(new RegExp(`^${UUID}$`), '小写 UUID');
/** 新增行的临时编号：`tmp-` 加小写 UUID */
export const clientRowId = pattern(new RegExp(`^tmp-${UUID}$`), '以 tmp- 开头的临时编号');
/** C01 第 4 节的日期 */
export const dateText = pattern(/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/, 'YYYY-MM-DD 格式的日期');
/** C01 第 4 节的日期时间，不带时区 */
export const dateTimeText = pattern(
  /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$/,
  'YYYY-MM-DDTHH:mm:ss 格式的日期时间'
);
export const int = scalar<number>(value => Number.isInteger(value), '整数');
export const num = scalar<number>(value => typeof value === 'number' && Number.isFinite(value), '数字');
export const bool = scalar<boolean>(value => typeof value === 'boolean', '布尔');
export const trueValue = scalar<true>(value => value === true, 'true');
export const falseValue = scalar<false>(value => value === false, 'false');

/** 业务字段在 JSON 中的值：精确数值和文本都是字符串，是非为布尔，空为 null（C01） */
export type BusinessValue = string | boolean | null;
export const businessValue = scalar<BusinessValue>(
  value => value === null || typeof value === 'string' || typeof value === 'boolean',
  '字符串、布尔或 null'
);

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

function isJson(value: unknown): boolean {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJson);
  if (typeof value === 'object') return Object.values(value as object).every(isJson);
  return false;
}

export const json: Schema<JsonValue> = {
  optional: false,
  parse(input, path = '') {
    if (!isJson(input)) throw new ContractViolation(path, '应为 JSON 值');
    return structuredClone(input) as JsonValue;
  }
};

export function literal<const T extends readonly (string | number | boolean)[]>(...values: T): Schema<T[number]> {
  return scalar<T[number]>(value => values.includes(value as T[number]), values.map(v => JSON.stringify(v)).join('、'));
}

export function nullable<T>(inner: Schema<T, boolean>): Schema<T | null> {
  return {
    optional: false,
    parse(input, path = '') {
      return input === null ? null : inner.parse(input, path);
    }
  };
}

/** 对象中可以不写的字段。写出时按内层检查；可选字段不接受 undefined 以外的"缺省"。 */
export function optional<T>(inner: Schema<T, boolean>): Schema<T, true> {
  return {
    optional: true,
    parse(input, path = '') {
      return inner.parse(input, path);
    }
  };
}

export function array<T>(item: Schema<T, boolean>): Schema<T[]> {
  return {
    optional: false,
    parse(input, path = '') {
      if (!Array.isArray(input)) throw new ContractViolation(path, `应为数组，实际是 ${describe(input)}`);
      return input.map((value, index) => item.parse(value, `${path}[${index}]`));
    }
  };
}

export function record<T>(value: Schema<T, boolean>, keyCheck: Schema<string> = str): Schema<Record<string, T>> {
  return {
    optional: false,
    parse(input, path = '') {
      if (input === null || typeof input !== 'object' || Array.isArray(input)) {
        throw new ContractViolation(path, `应为对象，实际是 ${describe(input)}`);
      }
      const result: Record<string, T> = {};
      for (const [name, item] of Object.entries(input as Record<string, unknown>)) {
        keyCheck.parse(name, `${path}.<键 ${name}>`);
        result[name] = value.parse(item, path ? `${path}.${name}` : name);
      }
      return result;
    }
  };
}

export interface ObjectSchema<S extends Shape> extends Schema<ObjectOf<S>> {
  readonly name: string;
  readonly shape: S;
}

/** 已定义的对象类型：契约测试用它逐个核对后端类的字段名 */
export const objectRegistry = new Map<string, ObjectSchema<Shape>>();

export function object<S extends Shape>(name: string, shape: S): ObjectSchema<S> {
  const schema: ObjectSchema<S> = {
    name,
    shape,
    optional: false,
    parse(input, path = '') {
      if (input === null || typeof input !== 'object' || Array.isArray(input)) {
        throw new ContractViolation(path, `${name} 应为对象，实际是 ${describe(input)}`);
      }
      const source = input as Record<string, unknown>;
      for (const field of Object.keys(source)) {
        if (!(field in shape)) throw new ContractViolation(path, `${name} 没有字段 ${field}`);
      }
      const result: Record<string, unknown> = {};
      for (const [field, fieldSchema] of Object.entries(shape)) {
        const fieldPath = path ? `${path}.${field}` : field;
        if (!(field in source)) {
          if (fieldSchema.optional) continue;
          throw new ContractViolation(fieldPath, `${name} 缺少必须写的字段`);
        }
        result[field] = fieldSchema.parse(source[field], fieldPath);
      }
      return result as ObjectOf<S>;
    }
  };
  objectRegistry.set(name, schema as unknown as ObjectSchema<Shape>);
  return schema;
}

/** 按某个字段的值区分的联合类型，例如命令中各行的 `op` */
export function tagged<K extends string, M extends Record<string, Schema<unknown>>>(
  tag: K,
  members: M
): Schema<Infer<M[keyof M]>> {
  return {
    optional: false,
    parse(input, path = '') {
      const value = input !== null && typeof input === 'object' ? (input as Record<string, unknown>)[tag] : undefined;
      const member = typeof value === 'string' ? members[value] : undefined;
      if (!member) throw new ContractViolation(path, `${tag} 应为 ${Object.keys(members).join('、')} 之一`);
      return member.parse(input, path) as Infer<M[keyof M]>;
    }
  };
}

/** 依次尝试，取第一个能解析的类型（各成员的字段集合互不相同） */
export function oneOf<const M extends readonly Schema<unknown>[]>(...members: M): Schema<Infer<M[number]>> {
  return {
    optional: false,
    parse(input, path = '') {
      const reasons: string[] = [];
      for (const member of members) {
        try {
          return member.parse(input, path) as Infer<M[number]>;
        } catch (error) {
          if (!(error instanceof ContractViolation)) throw error;
          reasons.push(error.message);
        }
      }
      throw new ContractViolation(path, `不符合任何一种形状（${reasons.join('；')}）`);
    }
  };
}

/** 递归类型（例如菜单）用：调用时才取 schema */
export function lazy<T>(get: () => Schema<T>): Schema<T> {
  return {
    optional: false,
    parse(input, path = '') {
      return get().parse(input, path);
    }
  };
}

/** 附加检查：先按内层解析，再检查跨字段的规则 */
export function refine<T>(inner: Schema<T>, check: (value: T) => string | null): Schema<T> {
  return {
    optional: false,
    parse(input, path = '') {
      const value = inner.parse(input, path);
      const problem = check(value);
      if (problem) throw new ContractViolation(path, problem);
      return value;
    }
  };
}
