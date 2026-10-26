/**
 * T-CT-2：十进制文本的解析、格式化和数值一致判定（C01 第 2、3 节）。
 *
 * 样例直接从 docs/契约/C01-数据格式.md 读取；后端 backend/tests/contracts/test_decimal_text.py 读取同一批样例。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  DecimalTextError,
  type DecimalValue,
  formatDecimal,
  isDecimalText,
  numbersConsistent,
  parseDecimal
} from '../../src/contracts/decimal-text';

const C01 = fileURLToPath(new URL('../../../docs/契约/C01-数据格式.md', import.meta.url));

function quoted(text: string): string[] {
  return [...text.matchAll(/`([^`]*)`/g)].map(m => m[1]);
}

function readC01() {
  const text = readFileSync(C01, 'utf-8');
  const valid = quoted(/^\s*- 合法：(.*)$/m.exec(text)![1]);
  const invalid = quoted(/^\s*- 不合法：(.*)$/m.exec(text)![1]);
  const trailing = /^- 末尾零不影响数值是否相等，例如 `([^`]*)` 与 `([^`]*)` 相等/m.exec(text)!;
  const section = text.split('## 3.')[1].split('## 4.')[0];
  const table: [string, string, boolean][] = [];
  for (const line of section.split(/\r?\n/)) {
    const cells = line
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map(c => c.trim());
    if (cells.length === 3 && (cells[2] === '一致' || cells[2] === '不一致')) {
      for (const a of quoted(cells[0])) for (const b of quoted(cells[1])) table.push([a, b, cells[2] === '一致']);
    }
  }
  // 第 2 节"末尾零不影响数值是否相等"的样例也按一致处理
  table.push([trailing[1], trailing[2], true]);
  return { valid, invalid, table };
}

const { valid, invalid, table } = readC01();

/**
 * 独立的参考实现：把整个数换成以 1E-45 为单位的 BigInt，再用整数除法（向零截断）得到以 1E-15 为单位的值。
 * 与被测实现"按字符串截取前 15 位小数"的做法不同。
 */
function oracleKey(text: string): bigint {
  const negative = text.startsWith('-');
  const [int, frac = ''] = text.replace(/^-/, '').split('.');
  const units = BigInt(int + frac.padEnd(45, '0')) * (negative ? -1n : 1n);
  return units / 10n ** 30n;
}

/** 规整写法：去掉整数部分的前导零，保留小数位，零不带负号。只做字符串运算。 */
function normalized(text: string): string {
  const [, sign, integer, fraction] = /^(-?)([0-9]+)(?:\.([0-9]+))?$/.exec(text)!;
  const int = integer.replace(/^0+/, '') || '0';
  const isZero = /^0*$/.test(int + (fraction ?? ''));
  return `${sign && !isZero ? '-' : ''}${int}${fraction === undefined ? '' : `.${fraction}`}`;
}

/** 先抽长度再生成数字串，让超过 28 位的长数稳定出现。 */
function digits(min: number, max: number) {
  return fc.integer({ min, max }).chain(n => fc.string({ unit: fc.constantFrom(...'0123456789'), minLength: n, maxLength: n }));
}

const texts = fc
  .tuple(fc.boolean(), digits(1, 45), digits(0, 40))
  .map(([negative, integer, fraction]) => `${negative ? '-' : ''}${integer}${fraction ? `.${fraction}` : ''}`);

/** 把以 1E-20 为单位的 BigInt 写成十进制文本，只做字符串运算。 */
function textOf(units: bigint): string {
  const abs = (units < 0n ? -units : units).toString().padStart(21, '0');
  return `${units < 0n ? '-' : ''}${abs.slice(0, -20)}.${abs.slice(-20)}`;
}

describe('C01 样例', () => {
  it('从文档读到全部样例', () => {
    expect(valid).toHaveLength(3);
    expect(invalid).toHaveLength(6);
    expect(table).toHaveLength(10);
  });

  it.each(valid)('合法文本 %j 能解析', text => {
    expect(isDecimalText(text)).toBe(true);
    expect(() => parseDecimal(text)).not.toThrow();
  });

  it.each(invalid)('不合法文本 %j 被拒绝', text => {
    expect(isDecimalText(text)).toBe(false);
    expect(() => parseDecimal(text)).toThrow(DecimalTextError);
  });

  // C01 第 2 节样例之外常见的不合法写法：换行、非 ASCII 数字、空串、只有符号、下划线分隔。
  it.each(['1\n', '\n1', '\u0661\u0662', '\uff11', '1\n2', 'abc\n1', '', '-', '-.5', '1_000', ' 1', '1 '])(
    '不合法文本 %j 被拒绝',
    text => {
      expect(isDecimalText(text)).toBe(false);
      expect(() => parseDecimal(text)).toThrow(DecimalTextError);
      expect(() => numbersConsistent(text, '1')).toThrow(DecimalTextError);
    }
  );

  it.each([1, 1.5, null, true, undefined])('非文本 %j 被拒绝', value => {
    expect(isDecimalText(value)).toBe(false);
    expect(() => parseDecimal(value as unknown as string)).toThrow(DecimalTextError);
  });

  it.each(table)('%j 与 %j 一致为 %j', (a, b, expected) => {
    expect(numbersConsistent(a, b)).toBe(expected);
    expect(numbersConsistent(b, a)).toBe(expected);
  });

  it('空值规则', () => {
    expect(numbersConsistent(null, null)).toBe(true);
    expect(numbersConsistent(null, '0')).toBe(false);
    expect(numbersConsistent('0', null)).toBe(false);
  });

  it('判定时拒绝不合法的文本，另一侧为空时也一样', () => {
    expect(() => numbersConsistent('1e5', '100000')).toThrow(DecimalTextError);
    expect(() => numbersConsistent(null, 'abc')).toThrow(DecimalTextError);
    expect(() => numbersConsistent('abc', null)).toThrow(DecimalTextError);
  });

  // 跨越第 15 位截断边界的数对：差值不到 1E-15，但整数部分或前 15 位小数不同。
  it.each([
    ['0.9999999999999999', '1', false],
    ['1.0000000000000009', '1.000000000000001', false],
    ['-0.9999999999999999', '-1', false],
    ['123.4567890123456789', '123.456789012345679', false],
    ['0.0000000000000009', '-0.0000000000000009', true],
    ['1.0000000000000001', '1.0000000000000009', true],
    // 正负号：只有截断到 15 位后为零的数不比较正负号
    ['-0.5', '0.5', false],
    ['-0.000000000000001', '0.000000000000001', false],
    ['007', '7', true],
    // 长数：超过 28 位有效数字的部分也参与判定
    [`1${'0'.repeat(40)}`, `1${'0'.repeat(39)}1`, false],
    [`${'1'.repeat(30)}.000000000000001`, '1'.repeat(30), false],
    [`${'1'.repeat(30)}.0000000000000001`, '1'.repeat(30), true]
  ] as const)('边界 %j 与 %j 一致为 %j', (a, b, expected) => {
    expect(numbersConsistent(a, b)).toBe(expected);
    expect(numbersConsistent(b, a)).toBe(expected);
  });

  it.each([
    '12345678901234567890123456789012345.123456789012345678901234567890',
    '-0.00000000000000000000000000000000000001',
    '99999999999999999999999999999999999999999'
  ])('长数 %j 解析再格式化后每一位都不变', text => {
    expect(formatDecimal(parseDecimal(text))).toBe(text);
  });

  it.each([
    ['1.50', '1.50'],
    ['007', '7'],
    ['-0.00', '0.00'],
    ['-12.30', '-12.30'],
    ['0', '0']
  ])('%j 格式化为 %j', (text, expected) => {
    expect(formatDecimal(parseDecimal(text))).toBe(expected);
  });
});

describe('基于属性的测试', () => {
  it('任意合法文本格式化后再解析，数值相等', () => {
    fc.assert(
      fc.property(texts, text => {
        const value: DecimalValue = parseDecimal(text);
        const formatted = formatDecimal(value);
        expect(isDecimalText(formatted)).toBe(true);
        expect(formatted).toBe(normalized(text));
        expect(numbersConsistent(formatted, text)).toBe(true);
        expect(oracleKey(formatted)).toBe(oracleKey(text));
        const again = parseDecimal(formatted);
        expect(again.digits * 10n ** BigInt(value.scale)).toBe(value.digits * 10n ** BigInt(again.scale));
      })
    );
  });

  it('与按 15 位小数向零截断的参考实现结论相同', () => {
    fc.assert(
      fc.property(texts, texts, (a, b) => {
        expect(numbersConsistent(a, b)).toBe(oracleKey(a) === oracleKey(b));
      })
    );
  });

  it('绝对值相同、正负号相反的数对，与参考实现结论相同', () => {
    fc.assert(
      fc.property(texts, a => {
        const b = a.startsWith('-') ? a.slice(1) : `-${a}`;
        expect(numbersConsistent(a, b)).toBe(oracleKey(a) === oracleKey(b));
      })
    );
  });

  it('只有一位数字不同时（整数部分可以超过 28 位），与参考实现结论相同', () => {
    const numbers = fc
      .tuple(fc.boolean(), digits(1, 45), digits(20, 20))
      .map(([negative, integer, fraction]) => `${negative ? '-' : ''}${integer}.${fraction}`);
    fc.assert(
      fc.property(numbers, fc.nat(), fc.integer({ min: 1, max: 9 }), (a, pick, step) => {
        const positions = [...a].map((c, i) => (/[0-9]/.test(c) ? i : -1)).filter(i => i >= 0);
        const pos = positions[pick % positions.length];
        const b = a.slice(0, pos) + String((Number(a[pos]) + step) % 10) + a.slice(pos + 1);
        expect(numbersConsistent(a, b)).toBe(oracleKey(a) === oracleKey(b));
      })
    );
  });

  it('生成器会产生超过 28 位的长数', () => {
    const samples = fc.sample(texts, 500);
    expect(samples.some(s => s.replace(/[-.]/g, '').length > 60)).toBe(true);
  });

  it('跨越第 15 位边界的数对，与参考实现结论相同', () => {
    const k = fc.bigInt({ min: -(10n ** 25n), max: 10n ** 25n });
    fc.assert(
      fc.property(k, fc.bigInt({ min: 1n, max: 99_999n }), fc.bigInt({ min: 0n, max: 99_999n }), (b, d1, d2) => {
        const boundary = b * 100_000n;
        const below = textOf(boundary - d1);
        const above = textOf(boundary + d2);
        expect(numbersConsistent(below, above)).toBe(oracleKey(below) === oracleKey(above));
      })
    );
  });

  it('跨越边界的三个数：一致只能来自同一截断类，不能沿差值传递', () => {
    const k = fc.bigInt({ min: -(10n ** 25n), max: 10n ** 25n });
    const near = fc.bigInt({ min: 50_000n, max: 99_999n });
    fc.assert(
      fc.property(k, near, near, (b, left, right) => {
        const [x, y, z] = [b * 100_000n - left, b * 100_000n, b * 100_000n + right].map(textOf);
        if (numbersConsistent(x, y) && numbersConsistent(y, z)) expect(numbersConsistent(x, z)).toBe(true);
        expect(numbersConsistent(x, y)).toBe(oracleKey(x) === oracleKey(y));
        expect(numbersConsistent(y, z)).toBe(oracleKey(y) === oracleKey(z));
        expect(numbersConsistent(x, z)).toBe(oracleKey(x) === oracleKey(z));
      })
    );
  });

  it('自反', () => {
    fc.assert(fc.property(texts, a => numbersConsistent(a, a)));
  });

  it('对称', () => {
    fc.assert(fc.property(texts, texts, (a, b) => numbersConsistent(a, b) === numbersConsistent(b, a)));
  });

  it('传递', () => {
    const heads = fc.stringMatching(/^-?[0-9]{1,20}\.[0-9]{15}$/);
    const tails = fc.tuple(...[0, 1, 2].map(() => fc.stringMatching(/^[0-9]{0,10}$/)));
    const signs = fc.tuple(fc.boolean(), fc.boolean(), fc.boolean());
    fc.assert(
      fc.property(heads, tails, signs, fc.boolean(), texts, (head, tail, sign, zero, other) => {
        const [x, y, z] = tail.map((t, i) => (zero ? `${sign[i] ? '-' : ''}0.${'0'.repeat(15)}${t}` : head + t));
        expect(numbersConsistent(x, y) && numbersConsistent(y, z) && numbersConsistent(x, z)).toBe(true);
        for (const [a, b, c] of [
          [x, y, other],
          [other, x, y],
          [x, other, y]
        ]) {
          if (numbersConsistent(a, b) && numbersConsistent(b, c)) expect(numbersConsistent(a, c)).toBe(true);
        }
      })
    );
  });
});
