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
  return { valid, invalid, table };
}

const { valid, invalid, table } = readC01();

/** 独立的参考实现：把文本换成按 10^15 放大后向零截断的整数。 */
function oracleKey(text: string): bigint {
  const negative = text.startsWith('-');
  const [int, frac = ''] = text.replace(/^-/, '').split('.');
  const scaled = BigInt(int + frac.padEnd(15, '0').slice(0, 15));
  return negative ? -scaled : scaled;
}

const texts = fc.stringMatching(/^-?[0-9]{1,40}(\.[0-9]{1,40})?$/);

describe('C01 样例', () => {
  it('从文档读到全部样例', () => {
    expect(valid).toHaveLength(3);
    expect(invalid).toHaveLength(6);
    expect(table).toHaveLength(9);
  });

  it.each(valid)('合法文本 %j 能解析', text => {
    expect(isDecimalText(text)).toBe(true);
    expect(() => parseDecimal(text)).not.toThrow();
  });

  it.each(invalid)('不合法文本 %j 被拒绝', text => {
    expect(isDecimalText(text)).toBe(false);
    expect(() => parseDecimal(text)).toThrow(DecimalTextError);
  });

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

  it('判定时拒绝不合法的文本', () => {
    expect(() => numbersConsistent('1e5', '100000')).toThrow(DecimalTextError);
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

  it('只在小数第 10–20 位中的某一位不同时，与参考实现结论相同', () => {
    const heads = fc.stringMatching(/^-?[0-9]{1,20}\.[0-9]{20}$/);
    fc.assert(
      fc.property(heads, fc.integer({ min: 10, max: 20 }), fc.integer({ min: 1, max: 9 }), (a, place, step) => {
        const pos = a.indexOf('.') + place;
        const b = a.slice(0, pos) + String((Number(a[pos]) + step) % 10) + a.slice(pos + 1);
        expect(numbersConsistent(a, b)).toBe(oracleKey(a) === oracleKey(b));
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
