import type { Ref, ShallowRef } from 'vue';
import type { GridApi } from 'ag-grid-community';
import { forEachNestedDetailGridApi } from '@/v3/composables/meta-v3/detail-grid-apis';
import type { CalcRuleDependency, CalcRuntimeScope, ParsedPageConfig, RowData } from '@/v3/logic/calc-engine';
import {
  buildCalcRuleDependencies,
  calcAggregates,
  calcRowFields,
  compileAggRules,
  compileCalcRules,
  ensureRowKey,
  isValidIdentifier,
  normalizeFieldRef,
  resolveAffectedRuleFieldsByDependencies
} from '@/v3/logic/calc-engine';
import {
  applySummaryRowValues,
  buildSummaryRows,
  getSummaryRowId,
  resolveSummaryConfig
} from '@/v3/composables/meta-v3/summary-config';
import type { RowStateApi } from '@/v3/composables/meta-v3/useWorkingSetStore';

type CompiledCalcRules = ReturnType<typeof compileCalcRules>;

type CompiledAggRules = ReturnType<typeof compileAggRules>;

type CalcChange = {
  rowId?: string | number;
  field: string;
  oldValue: any;
  newValue: any;
  reason?: string;
};

type DetailLogGroup = {
  tabKey: string;
  rules: any[];
  ruleIndexMap: Map<string, { index: number; type: string }>;
  changes: CalcChange[];
};

type AggregateLog = {
  masterId: number;
  rowCount: number;
  aggregateRules: any[];
  masterCalcRules: any[];
  changes: CalcChange[];
};

const CALC_LOG_FLAG = '__META_V3_CALC_LOG__';

export function useCalcBroadcast(params: {
  masterGridApi: ShallowRef<GridApi | null>;
  getMasterRowById: (masterId: number) => RowData | null;
  getMasterRowByRowKey: (rowKey: string) => RowData | null;
  resolveMasterRowKey: (masterId: number) => string | null;
  detailCache: Map<string, Record<string, RowData[]>>;
  detailCalcRulesByTab: Ref<Record<string, CompiledCalcRules>>;
  compiledAggRules: Ref<CompiledAggRules>;
  compiledMasterCalcRules: Ref<CompiledCalcRules>;
  pageConfig: Ref<ParsedPageConfig | null>;
  loadDetailData?: (masterId: number, masterRowKey?: string) => Promise<void>;
  detailGridApisByTab?: Ref<Record<string, any>>;
  rowStateApi: RowStateApi;
}) {
  const {
    masterGridApi,
    getMasterRowById,
    getMasterRowByRowKey,
    resolveMasterRowKey,
    detailCache,
    detailCalcRulesByTab,
    compiledAggRules,
    compiledMasterCalcRules,
    pageConfig,
    loadDetailData,
    detailGridApisByTab,
    rowStateApi
  } = params;

  const detailDependencyCache = new Map<
    string,
    { rulesRef: CompiledCalcRules; deps: CalcRuleDependency[]; tableCode: string }
  >();

  function resolveMasterTableCode(): string | null {
    const tableCode = pageConfig.value?.masterTableCode;
    if (!isValidIdentifier(tableCode)) return null;
    return tableCode || null;
  }

  function resolveDetailTableCode(tabKey: string): string | null {
    const tab = pageConfig.value?.tabs?.find(item => item.key === tabKey);
    const tableCode = tab?.tableCode;
    if (!isValidIdentifier(tableCode)) return null;
    return tableCode || null;
  }

  function toQualifiedFieldRefs(fields: string[], defaultTableCode?: string | null): string[] {
    const refs: string[] = [];
    const seen = new Set<string>();
    for (const field of fields) {
      const raw = typeof field === 'string' ? field.trim() : '';
      if (!raw) continue;
      const normalized = normalizeFieldRef(raw, defaultTableCode || undefined);
      const ref = normalized || raw;
      if (seen.has(ref)) continue;
      seen.add(ref);
      refs.push(ref);
    }
    return refs;
  }

  function getDetailDependencies(tabKey: string, calcRules: CompiledCalcRules): CalcRuleDependency[] {
    const tableCode = resolveDetailTableCode(tabKey);
    if (!tableCode) return [];
    const cacheKey = `${tabKey}:${tableCode}`;
    const cached = detailDependencyCache.get(cacheKey);
    if (cached && cached.rulesRef === calcRules) {
      return cached.deps;
    }
    const deps = buildCalcRuleDependencies(calcRules, tableCode);
    detailDependencyCache.set(cacheKey, { rulesRef: calcRules, deps, tableCode });
    return deps;
  }

  function buildMasterCalcContext(masterRow: RowData): Record<string, any> {
    const context: Record<string, any> = {};
    const masterTableCode = resolveMasterTableCode();
    if (masterTableCode) {
      context[masterTableCode] = masterRow;
    }
    return context;
  }

  function buildDetailCalcContext(masterRow: RowData, detailRow: RowData, tabKey: string): Record<string, any> {
    const context: Record<string, any> = {};
    const masterTableCode = resolveMasterTableCode();
    if (masterTableCode) {
      context[masterTableCode] = masterRow;
    }
    const detailTableCode = resolveDetailTableCode(tabKey);
    if (detailTableCode) {
      context[detailTableCode] = detailRow;
    }
    return context;
  }

  function resolveMasterRowKeyFromRow(row: RowData, preferredRowKey?: string): string | null {
    if (preferredRowKey) return preferredRowKey;
    if (row?._rowKey) return String(row._rowKey);
    const masterIdRaw = row?.id;
    if (masterIdRaw == null) return null;
    const masterId = Number(masterIdRaw);
    if (Number.isNaN(masterId)) return null;
    return resolveMasterRowKey(masterId);
  }

  function buildDetailRowsByTableCode(cached: Record<string, RowData[]> | undefined) {
    const rowsByTableCode: Record<string, RowData[]> = {};
    if (!cached) return rowsByTableCode;

    const seenByTable = new Map<string, Set<string>>();
    const getRowIdentity = (row: RowData, fallbackIndex: number) => {
      if (row?.id != null) return `id:${row.id}`;
      if (row?._rowKey) return `rk:${String(row._rowKey)}`;
      return `idx:${fallbackIndex}`;
    };

    for (const [tabKey, rows] of Object.entries(cached)) {
      const tableCode = resolveDetailTableCode(tabKey);
      if (!tableCode) continue;

      if (!rowsByTableCode[tableCode]) rowsByTableCode[tableCode] = [];
      if (!seenByTable.has(tableCode)) seenByTable.set(tableCode, new Set<string>());
      const seen = seenByTable.get(tableCode)!;

      rows.forEach((row, idx) => {
        if (rowStateApi.isRowDeleted(row)) return;
        const identity = getRowIdentity(row, idx);
        if (seen.has(identity)) return;
        seen.add(identity);
        rowsByTableCode[tableCode].push(row);
      });
    }

    return rowsByTableCode;
  }

  function buildMasterCalcRuntime(
    masterRow: RowData,
    masterRowKey?: string,
    cachedOverride?: Record<string, RowData[]>
  ): CalcRuntimeScope {
    const resolvedRowKey = resolveMasterRowKeyFromRow(masterRow, masterRowKey);
    const cached = cachedOverride ?? (resolvedRowKey ? detailCache.get(resolvedRowKey) : undefined);
    return {
      detailRowsByTableCode: buildDetailRowsByTableCode(cached)
    };
  }

  function markFieldChange(row: RowData, field: string, oldValue: any, newValue: any, type: 'user' | 'calc') {
    rowStateApi.markFieldChange(row, field, oldValue, newValue, type);
  }

  function formatValue(value: any) {
    if (typeof value === 'string') return `"${value}"`;
    if (value == null) return String(value);
    return String(value);
  }

  function formatCalcRule(rule: any) {
    const base = rule.expression
      ? `${rule.field} = ${rule.expression}`
      : rule.formulaField
        ? `${rule.field} = [formula by ${rule.formulaField}]`
        : `${rule.field} = [rule]`;
    return rule.condition ? `${base} | condition: ${rule.condition}` : base;
  }

  function formatAggRule(rule: any) {
    if (rule.algorithm && rule.sourceField) {
      const base = `${rule.targetField} = ${rule.algorithm}(${rule.sourceField})`;
      return rule.filter ? `${base} | filter: ${rule.filter}` : base;
    }
    if (rule.expression) return `${rule.targetField} = ${rule.expression}`;
    return `${rule.targetField} = [rule]`;
  }

  function buildRuleIndexMap(rules: any[]) {
    const map = new Map<string, { index: number; type: string }>();
    rules.forEach((rule, idx) => {
      const reasonType = rule.expression ? 'expression' : rule.formulaField ? 'formula' : 'rule';
      if (rule.field) {
        map.set(rule.field, { index: idx + 1, type: reasonType });
      } else if (rule.targetField) {
        map.set(rule.targetField, { index: idx + 1, type: rule.expression ? 'expression' : 'aggregate' });
      }
    });
    return map;
  }

  function isCalcLogEnabled(): boolean {
    try {
      const g = globalThis as any;
      if (g && Object.hasOwn(g, CALC_LOG_FLAG)) {
        return Boolean(g[CALC_LOG_FLAG]);
      }
    } catch {
      // ignore
    }
    return true;
  }

  function logCalcBroadcast(params: {
    masterId: number;
    triggerFieldRefs: string[];
    detailLogs: DetailLogGroup[];
    aggregateLog?: AggregateLog | null;
  }) {
    if (!isCalcLogEnabled()) return;
    const { masterId, triggerFieldRefs, detailLogs, aggregateLog } = params;
    const hasDetail = detailLogs.some(group => group.changes.length > 0);
    const hasMaster = aggregateLog?.changes?.length;
    if (!hasDetail && !hasMaster) return;

    const header = `[MetaV3][CALC] masterId=${masterId}`;
    console.groupCollapsed(header);
    console.info('trigger:');
    console.info(`  - changed: [${triggerFieldRefs.map(f => `"${f}"`).join(', ')}]`);

    for (const group of detailLogs) {
      if (group.changes.length === 0) continue;
      console.info(`detail rules (${group.tabKey}):`);
      for (const rule of group.rules) {
        const ruleMeta = group.ruleIndexMap.get(rule.field);
        const prefix = ruleMeta ? `(#${ruleMeta.index}) ` : '';
        console.info(`  - ${prefix}${formatCalcRule(rule)}`);
      }
      console.info('detail changes:');
      console.table(
        group.changes.map(change => ({
          rowId: change.rowId ?? '-',
          field: change.field,
          from: formatValue(change.oldValue),
          to: formatValue(change.newValue),
          reason: change.reason ?? ''
        }))
      );
    }

    if (aggregateLog && aggregateLog.changes.length > 0) {
      const aggIndexMap = buildRuleIndexMap(aggregateLog.aggregateRules);
      const calcIndexMap = buildRuleIndexMap(aggregateLog.masterCalcRules);

      console.info('master rules (aggregate):');
      for (const rule of aggregateLog.aggregateRules) {
        const ruleMeta = aggIndexMap.get(rule.targetField);
        const prefix = ruleMeta ? `(#${ruleMeta.index}) ` : '';
        console.info(`  - ${prefix}${formatAggRule(rule)}`);
      }
      if (aggregateLog.masterCalcRules.length > 0) {
        console.info('master rules (calc):');
        for (const rule of aggregateLog.masterCalcRules) {
          const ruleMeta = calcIndexMap.get(rule.field);
          const prefix = ruleMeta ? `(#${ruleMeta.index}) ` : '';
          console.info(`  - ${prefix}${formatCalcRule(rule)}`);
        }
      }

      console.info('master changes:');
      console.table(
        aggregateLog.changes.map(change => ({
          field: change.field,
          from: formatValue(change.oldValue),
          to: formatValue(change.newValue),
          reason: change.reason ?? ''
        }))
      );
    }

    console.groupEnd();
  }

  function resolveDetailAffectedRules(
    tabKey: string,
    calcRules: CompiledCalcRules,
    changedFieldRefs: string[]
  ): CompiledCalcRules {
    if (changedFieldRefs.length === 0) return calcRules;
    const dependencies = getDetailDependencies(tabKey, calcRules);
    if (dependencies.length === 0) return calcRules;
    const affectedFields = resolveAffectedRuleFieldsByDependencies(changedFieldRefs, dependencies);
    if (affectedFields.size === 0) return [];
    return calcRules.filter(rule => affectedFields.has(rule.field));
  }

  function runDetailCalc(
    node: any,
    api: any,
    row: RowData,
    masterId: number,
    tabKey: string,
    masterRowKey?: string,
    changedFields?: string | string[],
    valueOverrides?: Record<string, any>
  ) {
    const masterRow = getMasterRowById(masterId) || (masterRowKey ? getMasterRowByRowKey(masterRowKey) : null);
    if (!masterRow) return [] as string[];
    const calcRules = detailCalcRulesByTab.value[tabKey] || [];
    if (calcRules.length === 0) return [] as string[];

    const detailTableCode = resolveDetailTableCode(tabKey);
    const changedList = Array.isArray(changedFields)
      ? changedFields.filter(Boolean)
      : changedFields
        ? [changedFields]
        : [];
    const changedFieldRefs = toQualifiedFieldRefs(changedList, detailTableCode);
    const effectiveRules = resolveDetailAffectedRules(tabKey, calcRules, changedFieldRefs);
    if (effectiveRules.length === 0) return [] as string[];

    const hasOverrides = Boolean(valueOverrides && Object.keys(valueOverrides).length > 0);
    const evalRow = hasOverrides ? { ...row, ...valueOverrides } : row;
    const context = buildDetailCalcContext(masterRow, evalRow, tabKey);
    const results = calcRowFields(evalRow, context, effectiveRules);

    if (hasOverrides && valueOverrides) {
      for (const [field, value] of Object.entries(valueOverrides)) {
        if (!Object.is(row[field], value)) {
          row[field] = value;
        }
      }
    }

    const changedRuleFields: string[] = [];
    for (const [field, value] of Object.entries(results)) {
      if (row[field] !== value) {
        const oldValue = row[field];
        row[field] = value;
        markFieldChange(row, field, oldValue, value, 'calc');
        changedRuleFields.push(field);
      }
    }
    if (changedRuleFields.length > 0) {
      if (node) {
        api?.refreshCells({ rowNodes: [node], columns: changedRuleFields, force: true });
      } else {
        api?.refreshCells({ force: true });
      }
    }
    return changedRuleFields;
  }

  function runMasterCalc(node: any, row: RowData, valueOverrides?: Record<string, any>) {
    if (compiledMasterCalcRules.value.length === 0) return [] as string[];
    const hasOverrides = Boolean(valueOverrides && Object.keys(valueOverrides).length > 0);
    const evalRow = hasOverrides ? { ...row, ...valueOverrides } : row;
    const masterRowKey = resolveMasterRowKeyFromRow(row);
    const runtimeScope = buildMasterCalcRuntime(evalRow, masterRowKey || undefined);
    const context = buildMasterCalcContext(evalRow);
    const results = calcRowFields(evalRow, context, compiledMasterCalcRules.value, null, runtimeScope);

    if (hasOverrides && valueOverrides) {
      for (const [field, value] of Object.entries(valueOverrides)) {
        if (!Object.is(row[field], value)) {
          row[field] = value;
        }
      }
    }

    const changedFields: string[] = [];
    for (const [field, value] of Object.entries(results)) {
      if (row[field] !== value) {
        const oldValue = row[field];
        row[field] = value;
        markFieldChange(row, field, oldValue, value, 'calc');
        changedFields.push(field);
      }
    }
    if (changedFields.length > 0) {
      if (node) {
        masterGridApi.value?.refreshCells({ rowNodes: [node], columns: changedFields, force: true });
      } else {
        masterGridApi.value?.refreshCells({ force: true });
      }
    }
    return changedFields;
  }

  async function broadcastToDetail(masterId: number, masterRow: RowData, changedFields?: string | string[]) {
    const masterRowKey = ensureRowKey(masterRow);
    let cached = detailCache.get(masterRowKey);
    if (!cached && loadDetailData) {
      await loadDetailData(masterId, masterRowKey);
      cached = detailCache.get(masterRowKey);
    }
    if (!cached) return;

    const changedList = Array.isArray(changedFields)
      ? changedFields.filter(Boolean)
      : changedFields
        ? [changedFields]
        : [];
    const masterTableCode = resolveMasterTableCode();
    const changedFieldRefs = toQualifiedFieldRefs(changedList, masterTableCode);

    const detailLogs: DetailLogGroup[] = [];
    for (const [tabKey, rows] of Object.entries(cached)) {
      const calcRules = detailCalcRulesByTab.value[tabKey] || [];
      if (calcRules.length === 0) continue;
      const effectiveRules = resolveDetailAffectedRules(tabKey, calcRules, changedFieldRefs);
      if (effectiveRules.length === 0) continue;
      const ruleIndexMap = buildRuleIndexMap(calcRules);
      const changes: CalcChange[] = [];

      for (const row of rows) {
        if (rowStateApi.isRowDeleted(row)) continue;
        const context = buildDetailCalcContext(masterRow, row, tabKey);
        const results = calcRowFields(row, context, effectiveRules);
        for (const [field, value] of Object.entries(results)) {
          if (row[field] !== value) {
            const oldValue = row[field];
            row[field] = value;
            markFieldChange(row, field, oldValue, value, 'calc');
            const reasonMeta = ruleIndexMap.get(field);
            const reason = reasonMeta ? `rule#${reasonMeta.index} / ${reasonMeta.type}` : undefined;
            changes.push({ rowId: row?.id ?? row?._rowKey, field, oldValue, newValue: value, reason });
          }
        }
      }
      if (changes.length > 0) {
        detailLogs.push({
          tabKey,
          rules: effectiveRules,
          ruleIndexMap,
          changes
        });
      }
    }

    refreshAllDetailGrids(masterRowKey);
    const aggregateLog = recalcAggregates(masterId, masterRowKey);
    logCalcBroadcast({
      masterId,
      triggerFieldRefs: changedFieldRefs.length > 0 ? changedFieldRefs : changedList,
      detailLogs,
      aggregateLog
    });
  }

  function refreshAllDetailGrids(masterRowKey: string) {
    const detailApis = detailGridApisByTab?.value;
    if (detailApis && Object.keys(detailApis).length > 0) {
      Object.values(detailApis).forEach(api => {
        api?.refreshCells?.({ force: true });
        api?.refreshClientSideRowModel?.('aggregate');
      });
      return;
    }
    const cached = detailCache.get(masterRowKey);
    if (!cached) return;
    const tabs = pageConfig.value?.tabs || [];

    forEachNestedDetailGridApi({
      masterGridApi,
      masterRowKey,
      tabKeys: tabs.map(tab => tab.key),
      callback: (detailApi, tabKey) => {
        if (!cached[tabKey]) return;
        detailApi.refreshCells({ force: true });
        detailApi.refreshClientSideRowModel?.('aggregate');
      }
    });
  }

  function recalcAggregates(masterId: number, masterRowKey?: string): AggregateLog | null {
    const resolvedRowKey = masterRowKey ?? resolveMasterRowKey(masterId);
    if (!resolvedRowKey) return null;
    const cached = detailCache.get(resolvedRowKey);
    if (!cached) return null;
    const masterNode = masterGridApi.value?.getRowNode(String(resolvedRowKey));
    if (!masterNode) return null;
    const masterRow = masterNode.data;
    const effectiveMasterId = masterRow?.id ?? masterId;

    const allRows: RowData[] = [];
    for (const rows of Object.values(cached)) {
      allRows.push(...rows.filter(row => !rowStateApi.isRowDeleted(row)));
    }

    const results = calcAggregates(
      allRows,
      compiledAggRules.value,
      masterRow as Record<string, any>,
      2,
      pageConfig.value?.postProcess
    );

    const changedFields: string[] = [];
    const changes: CalcChange[] = [];
    const aggReasonMap = buildRuleIndexMap(compiledAggRules.value);
    for (const [field, value] of Object.entries(results)) {
      if (masterRow[field] !== value) {
        const oldValue = masterRow[field];
        masterRow[field] = value;
        markFieldChange(masterRow, field, oldValue, value, 'calc');
        changedFields.push(field);
        const reasonMeta = aggReasonMap.get(field);
        const reason = reasonMeta ? `rule#${reasonMeta.index} / aggregate` : undefined;
        changes.push({ field, oldValue, newValue: value, reason });
      }
    }

    if (compiledMasterCalcRules.value.length > 0) {
      const calcReasonMap = buildRuleIndexMap(compiledMasterCalcRules.value);
      const masterContext = buildMasterCalcContext(masterRow);
      const runtimeScope = buildMasterCalcRuntime(masterRow, resolvedRowKey, cached);
      const calcResults = calcRowFields(masterRow, masterContext, compiledMasterCalcRules.value, null, runtimeScope);
      for (const [field, value] of Object.entries(calcResults)) {
        if (masterRow[field] !== value) {
          const oldValue = masterRow[field];
          masterRow[field] = value;
          markFieldChange(masterRow, field, oldValue, value, 'calc');
          changedFields.push(field);
          const reasonMeta = calcReasonMap.get(field);
          const reason = reasonMeta ? `rule#${reasonMeta.index} / calc` : undefined;
          changes.push({ field, oldValue, newValue: value, reason });
        }
      }
    }

    if (changedFields.length > 0) {
      masterGridApi.value?.refreshCells({ rowNodes: [masterNode], columns: changedFields, force: true });
    }

    refreshSummaryRow(effectiveMasterId, resolvedRowKey);
    return {
      masterId: effectiveMasterId,
      rowCount: allRows.length,
      aggregateRules: compiledAggRules.value,
      masterCalcRules: compiledMasterCalcRules.value,
      changes
    };
  }

  function refreshSummaryRow(masterId: number, masterRowKey?: string) {
    const api = masterGridApi.value;
    if (!api) return;
    const resolvedRowKey = masterRowKey ?? resolveMasterRowKey(masterId);
    if (!resolvedRowKey) return;
    const secondLevelInfo = api.getDetailGridInfo(`detail_${resolvedRowKey}`);
    if (!secondLevelInfo?.api) return;
    const cached = detailCache.get(resolvedRowKey);
    if (!cached || !pageConfig.value) return;

    const summaryConfig = resolveSummaryConfig(pageConfig.value);
    const summaryRows = buildSummaryRows({
      masterId,
      masterRowKey: resolvedRowKey,
      pageConfig: pageConfig.value,
      detailCache,
      summaryConfig,
      isRowDeleted: rowStateApi.isRowDeleted
    });

    for (const summaryRow of summaryRows) {
      const tabKey = summaryRow._tabKey;
      if (!tabKey) continue;
      const summaryNode = secondLevelInfo.api.getRowNode(getSummaryRowId(resolvedRowKey, String(tabKey)));
      if (summaryNode) {
        applySummaryRowValues(summaryNode, summaryRow, summaryConfig);
      }
    }
  }

  return {
    markFieldChange,
    runDetailCalc,
    runMasterCalc,
    broadcastToDetail,
    refreshAllDetailGrids,
    recalcAggregates,
    refreshSummaryRow
  };
}
