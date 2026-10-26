/**
 * Pure formula engine with no Vue/AG Grid dependency.
 */
import { type EvalFunction, compile } from 'mathjs';

export type FormulaMatchType = 'equals' | 'regex' | 'contains' | 'notContains';

export interface FormulaDefinition {
  key?: string;
  expression: string;
  triggerFields: string[];
  matchType?: FormulaMatchType;
}

export interface CalcRule {
  field: string;
  expression: string;
  triggerFields: string[];
  condition?: string;
  order?: number;
  formulaField?: string;
  formulas?: Record<string, FormulaDefinition>;
}

export interface AggRule {
  sourceField?: string;
  targetField: string;
  algorithm?: 'SUM' | 'AVG' | 'COUNT' | 'MAX' | 'MIN';
  filter?: string;
  expression?: string;
}

export interface AggConfig {
  rules: AggRule[];
  postProcess?: string;
}

interface CompiledFormulaBranch {
  key: string;
  matchType: FormulaMatchType;
  compiled: EvalFunction;
  matcher?: RegExp;
}

interface CompiledCalcRule extends CalcRule {
  compiled?: EvalFunction;
  compiledFormulaBranches?: CompiledFormulaBranch[];
  dependencyFields?: string[];
}

interface CompiledAggRule extends AggRule {
  compiledExpr?: EvalFunction;
}

const calcRuleCache = new Map<string, CompiledCalcRule[]>();
const aggRuleCache = new Map<string, CompiledAggRule[]>();

const IDENTIFIER_REGEX = /\b([A-Za-z_]\w*)\b/g;
const QUALIFIED_IDENTIFIER_REGEX = /\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b/g;
const BUILTIN_TOKENS = new Set([
  'abs',
  'ceil',
  'floor',
  'round',
  'sqrt',
  'pow',
  'log',
  'exp',
  'min',
  'max',
  'sum',
  'mean',
  'mod',
  'sign',
  'pi',
  'e',
  'true',
  'false',
  'null',
  'undefined',
  'if',
  'else',
  'return',
  'NaN',
  'Infinity',
  'SUM_IF',
  'AVG_IF',
  'COUNT_IF',
  'MAX_IF',
  'MIN_IF',
  'sum_if',
  'avg_if',
  'count_if',
  'max_if',
  'min_if',
  'IN',
  'in',
  'NVL',
  'nvl'
]);

export interface CalcRuleDependency {
  targetField: string;
  writeFieldRef: string;
  readFieldRefs: string[];
}

export interface CalcRuntimeScope {
  detailRowsByTableCode?: Record<string, Array<Record<string, any>>>;
}

type ParsedFieldRef = { tableCode?: string; field: string };

function parseFieldRef(fieldRef: string | undefined | null): ParsedFieldRef | null {
  if (!fieldRef || typeof fieldRef !== 'string') return null;
  const raw = fieldRef.trim();
  if (!raw) return null;
  const dotIndex = raw.indexOf('.');
  if (dotIndex > 0) {
    const tableCode = raw.slice(0, dotIndex).trim();
    const field = raw.slice(dotIndex + 1).trim();
    if (!isValidIdentifier(tableCode) || !isValidIdentifier(field)) return null;
    return { tableCode, field };
  }
  if (!isValidIdentifier(raw)) return null;
  return { field: raw };
}

function ensureFieldRefInScope(scope: Record<string, any>, fieldRef: string) {
  const parsed = parseFieldRef(fieldRef);
  if (!parsed) return;
  if (!parsed.tableCode) {
    if (!(parsed.field in scope)) scope[parsed.field] = 0;
    return;
  }
  const tableScope = scope[parsed.tableCode];
  if (!tableScope || typeof tableScope !== 'object' || Array.isArray(tableScope)) {
    scope[parsed.tableCode] = { [parsed.field]: 0 };
    return;
  }
  if (!(parsed.field in tableScope)) {
    tableScope[parsed.field] = 0;
  }
}

function readScopeField(scope: Record<string, any>, fieldRef: string | undefined): any {
  if (!fieldRef) return undefined;
  const parsed = parseFieldRef(fieldRef);
  if (!parsed) return undefined;
  if (!parsed.tableCode) {
    return scope[parsed.field];
  }
  const tableScope = scope[parsed.tableCode];
  if (!tableScope || typeof tableScope !== 'object') return undefined;
  return tableScope[parsed.field];
}

function normalizeScopeValue(value: unknown) {
  return value ?? 0;
}

function cloneScopeRecord(record: Record<string, any>) {
  const cloned: Record<string, any> = {};
  for (const [key, value] of Object.entries(record)) {
    cloned[key] = normalizeScopeValue(value);
  }
  return cloned;
}

function withDefaultTable(dep: string, defaultTableCode: string): string {
  const parsed = parseFieldRef(dep);
  if (!parsed) return dep;
  if (parsed.tableCode) return dep;
  return `${defaultTableCode}.${parsed.field}`;
}

export function isValidIdentifier(value: string | undefined | null): boolean {
  if (!value) return false;
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(value);
}

export function normalizeFieldRef(fieldRef: string, defaultTableCode?: string): string | null {
  const parsed = parseFieldRef(fieldRef);
  if (!parsed) return null;
  if (parsed.tableCode) return `${parsed.tableCode}.${parsed.field}`;
  if (!defaultTableCode || !isValidIdentifier(defaultTableCode)) return null;
  return `${defaultTableCode}.${parsed.field}`;
}

export function extractFieldRefsFromExpression(expression: string | undefined, defaultTableCode?: string): Set<string> {
  const deps = new Set<string>();
  if (!expression || typeof expression !== 'string') return deps;

  const qualifiedRanges: Array<{ start: number; end: number }> = [];
  let qualifiedMatch: RegExpExecArray | null;

  QUALIFIED_IDENTIFIER_REGEX.lastIndex = 0;
  while ((qualifiedMatch = QUALIFIED_IDENTIFIER_REGEX.exec(expression)) !== null) {
    const tableCode = qualifiedMatch[1];
    const field = qualifiedMatch[2];
    if (isValidIdentifier(tableCode) && isValidIdentifier(field)) {
      deps.add(`${tableCode}.${field}`);
      qualifiedRanges.push({
        start: qualifiedMatch.index,
        end: qualifiedMatch.index + qualifiedMatch[0].length
      });
    }
  }

  const isInsideQualified = (index: number) => qualifiedRanges.some(range => index >= range.start && index < range.end);

  IDENTIFIER_REGEX.lastIndex = 0;
  let bareMatch: RegExpExecArray | null;
  while ((bareMatch = IDENTIFIER_REGEX.exec(expression)) !== null) {
    const token = bareMatch[1];
    if (isInsideQualified(bareMatch.index)) continue;
    if (BUILTIN_TOKENS.has(token)) continue;
    const normalized = normalizeFieldRef(token, defaultTableCode);
    if (normalized) {
      deps.add(normalized);
    } else if (!defaultTableCode && isValidIdentifier(token)) {
      deps.add(token);
    }
  }

  return deps;
}

export function extractFieldRefsFromRule(rule: CalcRule, defaultTableCode?: string): Set<string> {
  const deps = new Set<string>();

  for (const trigger of rule.triggerFields || []) {
    const normalized = normalizeFieldRef(trigger, defaultTableCode);
    if (normalized) {
      deps.add(normalized);
    } else if (!defaultTableCode && isValidIdentifier(trigger)) {
      deps.add(trigger);
    }
  }

  const formulaFieldRef = normalizeFieldRef(rule.formulaField || '', defaultTableCode);
  if (formulaFieldRef) {
    deps.add(formulaFieldRef);
  } else if (!defaultTableCode && rule.formulaField && isValidIdentifier(rule.formulaField)) {
    deps.add(rule.formulaField);
  }

  for (const dep of extractFieldRefsFromExpression(rule.expression, defaultTableCode)) {
    deps.add(dep);
  }
  for (const dep of extractFieldRefsFromExpression(rule.condition, defaultTableCode)) {
    deps.add(dep);
  }

  if (rule.formulas) {
    for (const formula of Object.values(rule.formulas)) {
      for (const trigger of formula.triggerFields || []) {
        const normalized = normalizeFieldRef(trigger, defaultTableCode);
        if (normalized) {
          deps.add(normalized);
        } else if (!defaultTableCode && isValidIdentifier(trigger)) {
          deps.add(trigger);
        }
      }
      for (const dep of extractFieldRefsFromExpression(formula.expression, defaultTableCode)) {
        deps.add(dep);
      }
    }
  }

  return deps;
}

export function buildCalcRuleDependencies(rules: CalcRule[], tableCode: string): CalcRuleDependency[] {
  if (!isValidIdentifier(tableCode)) return [];
  return rules.map(rule => {
    const readFieldRefs = Array.from(extractFieldRefsFromRule(rule, tableCode)).filter(
      dep => dep !== `${tableCode}.${rule.field}`
    );
    return {
      targetField: rule.field,
      writeFieldRef: `${tableCode}.${rule.field}`,
      readFieldRefs
    };
  });
}

export function resolveAffectedRuleFieldsByDependencies(
  changedFieldRefs: string[],
  dependencies: CalcRuleDependency[]
): Set<string> {
  const changed = new Set(changedFieldRefs.filter(Boolean));
  const affectedTargets = new Set<string>();
  let advanced = true;

  while (advanced) {
    advanced = false;
    for (const dep of dependencies) {
      if (affectedTargets.has(dep.targetField)) continue;
      const hit = dep.readFieldRefs.some(ref => changed.has(ref));
      if (!hit) continue;
      affectedTargets.add(dep.targetField);
      if (!changed.has(dep.writeFieldRef)) {
        changed.add(dep.writeFieldRef);
        advanced = true;
      }
    }
  }

  return affectedTargets;
}

export function compileCalcRules(rules: CalcRule[], cacheKey?: string): CompiledCalcRule[] {
  if (cacheKey && calcRuleCache.has(cacheKey)) {
    return calcRuleCache.get(cacheKey)!;
  }

  const compiled = rules.map((rule, idx) => {
    const result: CompiledCalcRule = {
      ...rule,
      order: rule.order ?? idx,
      dependencyFields: Array.from(extractFieldRefsFromRule(rule))
    };

    if (rule.formulaField && rule.formulas) {
      result.compiledFormulaBranches = [];
      for (const [key, formula] of Object.entries(rule.formulas)) {
        const branchKey = formula.key ?? key;
        try {
          const compiledExpression = compile(formula.expression);
          const matchType: FormulaMatchType =
            formula.matchType === 'regex'
              ? 'regex'
              : formula.matchType === 'contains'
                ? 'contains'
                : formula.matchType === 'notContains'
                  ? 'notContains'
                  : 'equals';
          if (matchType === 'regex') {
            try {
              result.compiledFormulaBranches.push({
                key: branchKey,
                matchType,
                compiled: compiledExpression,
                matcher: new RegExp(branchKey)
              });
            } catch (regexError) {
              console.warn(`[Calculator] compile regex branch failed: ${rule.field}.${branchKey}`, regexError);
            }
          } else {
            result.compiledFormulaBranches.push({
              key: branchKey,
              matchType,
              compiled: compiledExpression
            });
          }
        } catch (e) {
          console.warn(`[Calculator] compile expression failed: ${rule.field}.${branchKey}`, e);
        }
      }
    } else if (rule.expression) {
      try {
        result.compiled = compile(rule.expression);
      } catch (e) {
        console.warn(`[Calculator] compile expression failed: ${rule.field}`, e);
      }
    }

    return result;
  });

  compiled.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

  if (cacheKey) {
    calcRuleCache.set(cacheKey, compiled);
  }

  return compiled;
}

export function compileAggRules(rules: AggRule[], cacheKey?: string): CompiledAggRule[] {
  if (cacheKey && aggRuleCache.has(cacheKey)) {
    return aggRuleCache.get(cacheKey)!;
  }

  const compiled = rules.map(rule => ({
    ...rule,
    compiledExpr: rule.expression ? compile(rule.expression) : undefined
  }));

  if (cacheKey) {
    aggRuleCache.set(cacheKey, compiled);
  }

  return compiled;
}

export function evalCondition(condition: string | undefined, row: Record<string, any>): boolean {
  if (!condition) return true;

  try {
    const fn = new Function(...Object.keys(row), `return ${condition}`);
    return fn(...Object.values(row));
  } catch (e) {
    console.warn('[Calculator] condition evaluate failed:', condition, e);
    return true;
  }
}

type AggregateAlgorithm = 'SUM' | 'AVG' | 'COUNT' | 'MAX' | 'MIN';

type AggregateSource = {
  tableCode: string;
  field: string;
  filterExpr?: string;
};

function resolveAggregateSource(args: unknown[]): AggregateSource | null {
  if (args.length === 0) return null;
  const first = args[0];

  if (typeof first === 'string') {
    const firstRaw = first.trim();
    const parsed = parseFieldRef(firstRaw);
    if (parsed?.tableCode) {
      const filterExpr = typeof args[1] === 'string' ? args[1] : undefined;
      return {
        tableCode: parsed.tableCode,
        field: parsed.field,
        filterExpr
      };
    }

    if (isValidIdentifier(firstRaw) && typeof args[1] === 'string' && isValidIdentifier(args[1].trim())) {
      const filterExpr = typeof args[2] === 'string' ? args[2] : undefined;
      return {
        tableCode: firstRaw,
        field: args[1].trim(),
        filterExpr
      };
    }
  }

  return null;
}

function buildFilterMatcher(
  tableCode: string,
  filterExpr: string,
  cache: Map<string, (row: Record<string, any>) => boolean>
) {
  const cacheKey = `${tableCode}::${filterExpr}`;
  const cached = cache.get(cacheKey);
  if (cached) return cached;

  const evaluator = new Function('scope', `with(scope){ return (${filterExpr}); }`) as (
    scope: Record<string, any>
  ) => unknown;
  const matcher = (row: Record<string, any>) => {
    try {
      const scope = { ...row, row, [tableCode]: row };
      return Boolean(evaluator(scope));
    } catch {
      return false;
    }
  };
  cache.set(cacheKey, matcher);
  return matcher;
}

function aggregateDetailRows(
  rowsByTableCode: Record<string, Array<Record<string, any>>> | undefined,
  algorithm: AggregateAlgorithm,
  args: unknown[],
  filterCache: Map<string, (row: Record<string, any>) => boolean>
): number {
  const source = resolveAggregateSource(args);
  if (!source) return 0;

  const sourceRows = rowsByTableCode?.[source.tableCode] || [];
  const rows = source.filterExpr
    ? sourceRows.filter(buildFilterMatcher(source.tableCode, source.filterExpr, filterCache))
    : sourceRows;

  if (rows.length === 0) return 0;
  if (algorithm === 'COUNT') return rows.length;

  const values = rows.map(row => Number(row[source.field]) || 0);
  switch (algorithm) {
    case 'SUM':
      return values.reduce((acc, cur) => acc + cur, 0);
    case 'AVG':
      return values.reduce((acc, cur) => acc + cur, 0) / values.length;
    case 'MAX':
      return Math.max(...values);
    case 'MIN':
      return Math.min(...values);
    default:
      return 0;
  }
}

function createCalcFunctionScope(runtime?: CalcRuntimeScope): Record<string, any> {
  const rowsByTableCode = runtime?.detailRowsByTableCode;
  const filterCache = new Map<string, (row: Record<string, any>) => boolean>();

  const aggregate = (algorithm: AggregateAlgorithm, args: unknown[]) =>
    aggregateDetailRows(rowsByTableCode, algorithm, args, filterCache);

  const SUM_IF = (...args: unknown[]) => aggregate('SUM', args);
  const AVG_IF = (...args: unknown[]) => aggregate('AVG', args);
  const COUNT_IF = (...args: unknown[]) => aggregate('COUNT', args);
  const MAX_IF = (...args: unknown[]) => aggregate('MAX', args);
  const MIN_IF = (...args: unknown[]) => aggregate('MIN', args);
  const IN = (value: unknown, ...candidates: unknown[]) => candidates.some(item => Object.is(item, value));
  const NVL = (value: unknown, defaultValue: unknown) =>
    value == null || (typeof value === 'number' && Number.isNaN(value)) ? defaultValue : value;

  return {
    SUM_IF,
    AVG_IF,
    COUNT_IF,
    MAX_IF,
    MIN_IF,
    sum_if: SUM_IF,
    avg_if: AVG_IF,
    count_if: COUNT_IF,
    max_if: MAX_IF,
    min_if: MIN_IF,
    IN,
    in: IN,
    NVL,
    nvl: NVL
  };
}

export function calcRowFields(
  row: Record<string, any>,
  context: Record<string, any>,
  rules: CompiledCalcRule[],
  precision: number | null = null,
  runtime?: CalcRuntimeScope
): Record<string, number> {
  const results: Record<string, number> = {};
  const scope: Record<string, any> = {};

  for (const [key, value] of Object.entries(context || {})) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      // Keep qualified refs and bare refs on the same null-handling semantics.
      scope[key] = cloneScopeRecord(value as Record<string, any>);
    } else {
      scope[key] = normalizeScopeValue(value);
    }
  }

  for (const [key, value] of Object.entries(row || {})) {
    scope[key] = normalizeScopeValue(value);
  }

  const functionScope = createCalcFunctionScope(runtime);
  for (const [key, value] of Object.entries(functionScope)) {
    scope[key] = value;
  }

  const rowScopeKeys: string[] = [];
  for (const [key, value] of Object.entries(context || {})) {
    if (value === row) {
      rowScopeKeys.push(key);
    }
  }

  for (const rule of rules) {
    for (const field of rule.triggerFields || []) {
      ensureFieldRefInScope(scope, field);
    }
    if (rule.formulas) {
      for (const formula of Object.values(rule.formulas)) {
        for (const field of formula.triggerFields || []) {
          ensureFieldRefInScope(scope, field);
        }
      }
    }
    for (const fieldRef of rule.dependencyFields || []) {
      ensureFieldRefInScope(scope, fieldRef);
    }
  }

  const maxPasses = Math.max(1, rules.length * 2);
  for (let pass = 0; pass < maxPasses; pass++) {
    let changed = false;

    for (const rule of rules) {
      if (!evalCondition(rule.condition, scope)) {
        continue;
      }

      try {
        let value: number;

        if (rule.formulaField && rule.compiledFormulaBranches?.length) {
          const formulaValue = String(readScopeField(scope, rule.formulaField) ?? '');
          const matchedBranch = rule.compiledFormulaBranches.find(branch => {
            switch (branch.matchType) {
              case 'regex':
                return branch.matcher?.test(formulaValue) ?? false;
              case 'contains':
                return formulaValue.includes(branch.key);
              case 'notContains':
                return !formulaValue.includes(branch.key);
              default:
                return branch.key === formulaValue;
            }
          });

          if (matchedBranch) {
            value = matchedBranch.compiled.evaluate(scope);
          } else {
            if (row[rule.field] != null) {
              scope[rule.field] = row[rule.field];
            }
            continue;
          }
        } else if (rule.compiled) {
          value = rule.compiled.evaluate(scope);
        } else {
          continue;
        }

        const raw = normalizeNumber(Number(value));
        const output = applyPrecision(raw, precision);
        const prev = scope[rule.field];
        if (!Object.is(prev, raw)) {
          changed = true;
        }
        results[rule.field] = output;
        scope[rule.field] = raw;
        for (const key of rowScopeKeys) {
          const tableScope = scope[key];
          if (tableScope && typeof tableScope === 'object' && !Array.isArray(tableScope)) {
            tableScope[rule.field] = raw;
          }
        }
      } catch (e) {
        console.warn('[Calculator] evaluate failed:', rule.field, e);
        results[rule.field] = 0;
      }
    }

    if (!changed) {
      break;
    }
  }

  return results;
}

export function getAffectedRules(field: string, rules: CompiledCalcRule[], isBroadcast = false): CompiledCalcRule[] {
  const affected = new Set<string>();
  const queue = [field];

  while (queue.length > 0) {
    const current = queue.shift()!;

    for (const rule of rules) {
      let isDep = false;

      if (isBroadcast) {
        if (rule.dependencyFields?.includes(current)) {
          isDep = true;
        }
        if (!isDep && rule.expression && rule.expression.includes(current)) {
          isDep = true;
        }
        if (!isDep && rule.formulas) {
          for (const formula of Object.values(rule.formulas)) {
            if (formula.expression.includes(current)) {
              isDep = true;
              break;
            }
          }
        }
      } else {
        if (rule.triggerFields.includes(current)) {
          isDep = true;
        }
        if (!isDep && rule.dependencyFields?.includes(current)) {
          isDep = true;
        }
        if (!isDep && rule.formulas) {
          for (const formula of Object.values(rule.formulas)) {
            if (formula.triggerFields.includes(current)) {
              isDep = true;
              break;
            }
          }
        }
        if (!isDep && rule.formulaField === current) {
          isDep = true;
        }
      }

      if (isDep && !affected.has(rule.field)) {
        affected.add(rule.field);
        queue.push(rule.field);
      }
    }
  }

  return rules.filter(r => affected.has(r.field));
}

export function calcAggregates(
  rows: Record<string, any>[],
  rules: CompiledAggRule[],
  currentMaster: Record<string, any> = {},
  precision: number | null = null,
  postProcess?: string
): Record<string, number> {
  const results: Record<string, number> = {};

  for (const rule of rules) {
    if (rule.algorithm && rule.sourceField) {
      const filteredRows = rule.filter ? filterRows(rows, rule.filter) : rows;
      const value = aggregate(filteredRows, rule.sourceField, rule.algorithm);
      results[rule.targetField] = normalizeNumber(value);
    }
  }

  for (const rule of rules) {
    if (rule.compiledExpr && !rule.algorithm) {
      const context = { ...currentMaster, ...results };
      try {
        const value = rule.compiledExpr.evaluate(context);
        results[rule.targetField] = normalizeNumber(Number(value) || 0);
      } catch (e) {
        console.warn('[Calculator] aggregate expression evaluate failed:', rule.expression, e);
        results[rule.targetField] = 0;
      }
    }
  }

  if (postProcess) {
    try {
      const fields = Object.keys(results);
      const fn = new Function(
        ...fields,
        `
        ${postProcess}
        return { ${fields.join(', ')} };
      `
      );
      const processed = fn(...Object.values(results));
      for (const field of fields) {
        if (typeof processed[field] === 'number') {
          results[field] = normalizeNumber(processed[field]);
        }
      }
    } catch (e) {
      console.warn('[Calculator] aggregate postProcess failed:', postProcess, e);
    }
  }

  return applyPrecisionMap(results, precision);
}

function filterRows(rows: Record<string, any>[], filterExpr: string): Record<string, any>[] {
  return rows.filter(row => {
    try {
      const fn = new Function(...Object.keys(row), `return ${filterExpr}`);
      return fn(...Object.values(row));
    } catch {
      return true;
    }
  });
}

function aggregate(rows: Record<string, any>[], field: string, algorithm: string): number {
  if (rows.length === 0) return 0;

  const values = rows.map(r => Number(r[field]) || 0);

  switch (algorithm) {
    case 'SUM':
      return values.reduce((a, b) => a + b, 0);
    case 'AVG':
      return values.reduce((a, b) => a + b, 0) / values.length;
    case 'COUNT':
      return rows.length;
    case 'MAX':
      return Math.max(...values);
    case 'MIN':
      return Math.min(...values);
    default:
      return 0;
  }
}

function round(value: number, precision: number): number {
  if (Number.isNaN(value) || !Number.isFinite(value)) return 0;
  const factor = 10 ** precision;
  return Math.round(value * factor) / factor;
}

function normalizeNumber(value: number): number {
  if (Number.isNaN(value) || !Number.isFinite(value)) return 0;
  return value;
}

function applyPrecision(value: number, precision: number | null): number {
  if (precision == null) return value;
  return round(value, precision);
}

function applyPrecisionMap(results: Record<string, number>, precision: number | null): Record<string, number> {
  if (precision == null) return results;
  const output: Record<string, number> = {};
  for (const [field, value] of Object.entries(results)) {
    output[field] = applyPrecision(value, precision);
  }
  return output;
}

export function clearCalcCache(cacheKey?: string) {
  if (cacheKey) {
    calcRuleCache.delete(cacheKey);
    aggRuleCache.delete(cacheKey);
  } else {
    calcRuleCache.clear();
    aggRuleCache.clear();
  }
}

export function extractFieldsFromRules(rules: CalcRule[]): Set<string> {
  const fields = new Set<string>();
  for (const rule of rules) {
    const refs = extractFieldRefsFromRule(rule);
    for (const ref of refs) {
      const parsed = parseFieldRef(ref);
      if (!parsed) continue;
      fields.add(parsed.field);
    }
    for (const trigger of rule.triggerFields || []) {
      const parsed = parseFieldRef(trigger);
      if (parsed) fields.add(parsed.field);
    }
    if (rule.formulaField) {
      const parsed = parseFieldRef(rule.formulaField);
      if (parsed) fields.add(parsed.field);
    }
  }
  return fields;
}
