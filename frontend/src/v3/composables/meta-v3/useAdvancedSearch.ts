import { computed, ref, watch } from 'vue';
import type { Ref, ShallowRef } from 'vue';
import type { ColDef, GridApi } from 'ag-grid-community';
import type { DynamicQueryCondition } from '@/service/api';
import { fetchDictItems } from '@/service/api';
import type { ParsedPageConfig } from '@/v3/logic/calc-engine';
import type { LookupRuleConfig } from '@/v3/composables/meta-v3/types';
import {
  getEmptyAdvancedSearchSecondaryValue,
  getEmptyAdvancedSearchValue,
  isAdvancedSearchMultiValueOperator,
  isAdvancedSearchNullaryOperator,
  isAdvancedSearchRangeOperator,
  normalizeAdvancedSearchSecondaryValue,
  normalizeAdvancedSearchValue
} from '@/v3/composables/meta-v3/advanced-search-values';

type SearchDataType = 'string' | 'number' | 'date' | 'datetime';
type SearchInputMode = 'text' | 'number' | 'date' | 'datetime' | 'select' | 'lookup';

type RawColumnMeta = {
  columnName?: string;
  headerText?: string;
  dataType?: string;
  visible?: boolean;
  searchable?: boolean;
  dictType?: string;
  lookupCode?: string;
  rulesConfig?: string;
};

type SearchOption = {
  label: string;
  value: string | number;
};

export type AdvancedSearchField = {
  key: string;
  tableKey: string;
  tableLabel: string;
  field: string;
  fieldLabel: string;
  dataType: SearchDataType;
  inputMode: SearchInputMode;
  dictType?: string;
  lookupCode?: string;
  options: SearchOption[];
};

export type AdvancedSearchCondition = AdvancedSearchField & {
  operator: string;
  value: any;
  value2?: any;
  enabled: boolean;
  visible: boolean;
  loadingOptions?: boolean;
};

function normalizeDataType(dataType?: string): SearchDataType {
  const normalized = String(dataType || '')
    .trim()
    .toLowerCase();
  if (['number', 'integer', 'decimal', 'float', 'double'].includes(normalized)) {
    return 'number';
  }
  if (['datetime', 'timestamp'].includes(normalized)) {
    return 'datetime';
  }
  if (['date'].includes(normalized)) {
    return 'date';
  }
  return 'string';
}

function normalizeFieldKey(tableKey: string, field: string) {
  return `${String(tableKey || '')
    .trim()
    .toUpperCase()}::${String(field || '')
    .trim()
    .toUpperCase()}`;
}

function normalizeFieldName(field?: unknown) {
  return String(field || '')
    .trim()
    .toUpperCase();
}

function normalizeSelectOptions(values: unknown[]): SearchOption[] {
  return values.reduce<SearchOption[]>((result, item) => {
    const text = String(item ?? '').trim();
    if (text) {
      result.push({ label: text, value: text });
    }
    return result;
  }, []);
}

function resolveLookupCode(rawColumn: RawColumnMeta, colDef?: ColDef, lookupRule?: LookupRuleConfig) {
  if (lookupRule?.lookupCode) {
    return lookupRule.lookupCode;
  }
  if (rawColumn?.lookupCode) {
    return rawColumn.lookupCode;
  }
  const lookupCodeFromRules = parseLookupCodeFromRulesConfig(rawColumn?.rulesConfig);
  if (lookupCodeFromRules) {
    return lookupCodeFromRules;
  }
  if (
    typeof colDef?.cellEditorParams === 'object' &&
    typeof (colDef.cellEditorParams as any)?.lookupCode === 'string'
  ) {
    return String((colDef.cellEditorParams as any).lookupCode).trim();
  }
  return undefined;
}

function resolveSelectMeta(rawColumn: RawColumnMeta, colDef?: ColDef) {
  if (rawColumn?.dictType) {
    return {
      inputMode: 'select' as const,
      dictType: rawColumn.dictType,
      options: [] as SearchOption[]
    };
  }

  const rawValues = typeof colDef?.cellEditorParams === 'object' ? (colDef.cellEditorParams as any)?.values : undefined;
  if (Array.isArray(rawValues) && rawValues.length > 0) {
    return {
      inputMode: 'select' as const,
      options: normalizeSelectOptions(rawValues)
    };
  }

  return null;
}

function resolvePrimitiveInputMode(dataType: SearchDataType): SearchInputMode {
  if (dataType === 'number') {
    return 'number';
  }
  if (dataType === 'datetime') {
    return 'datetime';
  }
  if (dataType === 'date') {
    return 'date';
  }
  return 'text';
}

function parseLookupCodeFromRulesConfig(rulesConfig?: string): string | undefined {
  if (!rulesConfig) return undefined;
  try {
    const parsed = JSON.parse(rulesConfig);
    const lookupCode = parsed?.lookup?.code;
    return typeof lookupCode === 'string' && lookupCode.trim() ? lookupCode.trim() : undefined;
  } catch {
    return undefined;
  }
}

function buildLookupRuleMap(rules: LookupRuleConfig[] | undefined) {
  const result = new Map<string, LookupRuleConfig>();
  for (const rule of rules || []) {
    const key = normalizeFieldName(rule?.columnName);
    if (key) {
      result.set(key, rule);
    }
  }
  return result;
}

function buildColDefMap(columnDefs: ColDef[] | undefined) {
  const result = new Map<string, ColDef>();
  for (const colDef of columnDefs || []) {
    const key = normalizeFieldName(colDef?.field);
    if (key) {
      result.set(key, colDef);
    }
  }
  return result;
}

function resolveInputMeta(params: {
  rawColumn: RawColumnMeta;
  colDef?: ColDef;
  lookupRule?: LookupRuleConfig;
}): Pick<AdvancedSearchField, 'dataType' | 'inputMode' | 'dictType' | 'lookupCode' | 'options'> {
  const { rawColumn, colDef, lookupRule } = params;
  const dataType = normalizeDataType(rawColumn?.dataType);
  const lookupCode = resolveLookupCode(rawColumn, colDef, lookupRule);
  if (lookupCode) {
    return {
      dataType,
      inputMode: 'lookup',
      lookupCode,
      options: []
    };
  }

  const selectMeta = resolveSelectMeta(rawColumn, colDef);
  if (selectMeta) {
    return {
      dataType,
      ...selectMeta
    };
  }

  return { dataType, inputMode: resolvePrimitiveInputMode(dataType), options: [] };
}

function buildFieldDefinitions(params: {
  pageConfig: ParsedPageConfig | null;
  masterGridKey: string | null;
  masterColumnMeta: RawColumnMeta[];
  detailColumnMetaByTab: Record<string, RawColumnMeta[]>;
  masterColumnDefs: ColDef[];
  detailColumnDefsByTab: Record<string, ColDef[]>;
  masterLookupRules: LookupRuleConfig[];
  detailLookupRulesByTab: Record<string, LookupRuleConfig[]>;
}): AdvancedSearchField[] {
  const {
    pageConfig,
    masterGridKey,
    masterColumnMeta,
    detailColumnMetaByTab,
    masterColumnDefs,
    detailColumnDefsByTab,
    masterLookupRules,
    detailLookupRulesByTab
  } = params;
  const definitions: AdvancedSearchField[] = [];
  const seen = new Set<string>();

  const appendFields = (config: {
    tableKey: string;
    tableLabel: string;
    columns: RawColumnMeta[];
    columnDefs: ColDef[];
    lookupRules: LookupRuleConfig[];
  }) => {
    const { tableKey, tableLabel, columns, columnDefs, lookupRules } = config;
    const colDefMap = buildColDefMap(columnDefs);
    const lookupRuleMap = buildLookupRuleMap(lookupRules);
    for (const column of columns || []) {
      const field = String(column?.columnName || '').trim();
      if (field && column?.visible !== false && column?.searchable !== false) {
        const key = normalizeFieldKey(tableKey, field);
        if (!seen.has(key)) {
          seen.add(key);

          const fieldToken = normalizeFieldName(field);
          const inputMeta = resolveInputMeta({
            rawColumn: column,
            colDef: colDefMap.get(fieldToken),
            lookupRule: lookupRuleMap.get(fieldToken)
          });

          definitions.push({
            key,
            tableKey,
            tableLabel,
            field,
            fieldLabel: String(column?.headerText || field),
            ...inputMeta
          });
        }
      }
    }
  };

  appendFields({
    tableKey: masterGridKey || 'masterGrid',
    tableLabel: '主表',
    columns: masterColumnMeta || [],
    columnDefs: masterColumnDefs || [],
    lookupRules: masterLookupRules || []
  });

  for (const tab of pageConfig?.tabs || []) {
    appendFields({
      tableKey: tab.key,
      tableLabel: tab.title || tab.key,
      columns: detailColumnMetaByTab?.[tab.key] || [],
      columnDefs: detailColumnDefsByTab?.[tab.key] || [],
      lookupRules: detailLookupRulesByTab?.[tab.key] || []
    });
  }

  return definitions;
}

function splitInValue(value: string) {
  return value
    .split(/[,，]/)
    .map(item => item.trim())
    .filter(Boolean);
}

function getDefaultOperator(field: AdvancedSearchField) {
  if (field.inputMode === 'select' || field.inputMode === 'lookup') {
    return 'eq';
  }
  if (field.dataType === 'string') {
    return 'like';
  }
  return 'eq';
}

function hasConditionValue(condition: AdvancedSearchCondition) {
  if (isAdvancedSearchNullaryOperator(condition.operator)) {
    return true;
  }
  if (isAdvancedSearchRangeOperator(condition.operator)) {
    return condition.value !== null && condition.value !== '' && condition.value2 !== null && condition.value2 !== '';
  }
  if (isAdvancedSearchMultiValueOperator(condition.operator)) {
    if (Array.isArray(condition.value)) {
      return condition.value.length > 0;
    }
    return String(condition.value ?? '').trim().length > 0;
  }
  return condition.value !== null && String(condition.value ?? '').trim().length > 0;
}

export function useAdvancedSearch(params: {
  pageCode: string;
  pageConfig: Ref<ParsedPageConfig | null>;
  masterGridKey: Ref<string | null>;
  masterColumnMeta: Ref<RawColumnMeta[]>;
  detailColumnMetaByTab: Ref<Record<string, RawColumnMeta[]>>;
  masterColumnDefs: Ref<ColDef[]>;
  detailColumnDefsByTab: Ref<Record<string, ColDef[]>>;
  masterLookupRules: Ref<LookupRuleConfig[]>;
  detailLookupRulesByTab: Ref<Record<string, LookupRuleConfig[]>>;
  masterGridApi: ShallowRef<GridApi | null>;
  setAdvancedConditions: (conditions: DynamicQueryCondition[]) => void;
  clearAdvancedConditions: () => void;
  clearAllCache: () => void;
  notifyInfo: (message: string) => void;
}) {
  const {
    pageConfig,
    masterGridKey,
    masterColumnMeta,
    detailColumnMetaByTab,
    masterColumnDefs,
    detailColumnDefsByTab,
    masterLookupRules,
    detailLookupRulesByTab,
    masterGridApi,
    setAdvancedConditions,
    clearAdvancedConditions,
    clearAllCache,
    notifyInfo
  } = params;

  const showDialog = ref(false);
  const searchConditions = ref<AdvancedSearchCondition[]>([]);
  const dictOptionsCache = new Map<string, SearchOption[]>();

  function getFieldDefinitions() {
    return buildFieldDefinitions({
      pageConfig: pageConfig.value,
      masterGridKey: masterGridKey.value,
      masterColumnMeta: masterColumnMeta.value || [],
      detailColumnMetaByTab: detailColumnMetaByTab.value || {},
      masterColumnDefs: masterColumnDefs.value || [],
      detailColumnDefsByTab: detailColumnDefsByTab.value || {},
      masterLookupRules: masterLookupRules.value || [],
      detailLookupRulesByTab: detailLookupRulesByTab.value || {}
    });
  }

  async function ensureSelectOptions(condition: AdvancedSearchCondition) {
    if (condition.inputMode !== 'select' || condition.options.length > 0 || !condition.dictType) {
      return;
    }
    const cached = dictOptionsCache.get(condition.dictType);
    if (cached) {
      condition.options = cached;
      return;
    }

    condition.loadingOptions = true;
    try {
      const { data } = await fetchDictItems(condition.dictType);
      const options = (data || []).map(item => ({
        label: String(item.label ?? item.value ?? ''),
        value: String(item.value ?? '')
      }));
      dictOptionsCache.set(condition.dictType, options);
      condition.options = options;
    } finally {
      condition.loadingOptions = false;
    }
  }

  async function ensureLookupConditionReady(_condition: AdvancedSearchCondition) {}

  async function hydrateVisibleConditions() {
    await Promise.all(
      searchConditions.value.filter(condition => condition.visible).map(condition => ensureSelectOptions(condition))
    );
  }

  function refreshMasterGrid() {
    clearAllCache();
    masterGridApi.value?.deselectAll?.();
    masterGridApi.value?.refreshServerSide?.({ purge: true });
  }

  function syncSearchConditions(definitions: AdvancedSearchField[]) {
    const previous = new Map(searchConditions.value.map(condition => [condition.key, condition]));

    searchConditions.value = definitions.map(definition => {
      const existing = previous.get(definition.key);
      const operator = existing?.operator || getDefaultOperator(definition);
      return {
        ...definition,
        options: definition.options.length > 0 ? definition.options : existing?.options || [],
        operator,
        value: normalizeAdvancedSearchValue({
          inputMode: definition.inputMode,
          dataType: definition.dataType,
          operator,
          value: existing?.value
        }),
        value2: normalizeAdvancedSearchSecondaryValue({
          inputMode: definition.inputMode,
          dataType: definition.dataType,
          value: existing?.value2
        }),
        enabled: existing?.enabled || false,
        visible: existing?.visible ?? true,
        loadingOptions: existing?.loadingOptions || false
      };
    });

    hydrateVisibleConditions().catch(() => undefined);
  }

  function toQueryConditions(): DynamicQueryCondition[] {
    return searchConditions.value
      .filter(condition => condition.enabled && hasConditionValue(condition))
      .map(condition => {
        const value = condition.value;
        if (isAdvancedSearchRangeOperator(condition.operator)) {
          return {
            tableKey: condition.tableKey,
            field: condition.field,
            operator: condition.operator,
            value,
            value2: condition.value2
          };
        }
        if (isAdvancedSearchMultiValueOperator(condition.operator)) {
          return {
            tableKey: condition.tableKey,
            field: condition.field,
            operator: condition.operator,
            value: Array.isArray(value) ? value : splitInValue(String(value ?? ''))
          };
        }
        if (isAdvancedSearchNullaryOperator(condition.operator)) {
          return {
            tableKey: condition.tableKey,
            field: condition.field,
            operator: condition.operator,
            value: null
          };
        }
        return {
          tableKey: condition.tableKey,
          field: condition.field,
          operator: condition.operator,
          value
        };
      });
  }

  function open() {
    syncSearchConditions(getFieldDefinitions());
    showDialog.value = true;
  }

  function close() {
    showDialog.value = false;
  }

  function executeSearch() {
    const conditions = toQueryConditions();
    setAdvancedConditions(conditions);
    refreshMasterGrid();
    showDialog.value = false;
    notifyInfo(conditions.length > 0 ? `已应用 ${conditions.length} 个高级查询条件` : '已清空高级查询条件');
  }

  function clearSearch() {
    searchConditions.value = searchConditions.value.map(condition => ({
      ...condition,
      value: getEmptyAdvancedSearchValue({
        inputMode: condition.inputMode,
        dataType: condition.dataType,
        operator: condition.operator
      }),
      value2: getEmptyAdvancedSearchSecondaryValue({
        inputMode: condition.inputMode,
        dataType: condition.dataType
      }),
      enabled: false
    }));
    clearAdvancedConditions();
    refreshMasterGrid();
  }

  const visibleConditions = computed(() => searchConditions.value.filter(condition => condition.visible));

  const activeFilterSummaries = computed(() =>
    searchConditions.value
      .filter(condition => condition.enabled && hasConditionValue(condition))
      .map(condition => `${condition.tableLabel}·${condition.fieldLabel}`)
  );

  watch(
    [pageConfig, masterGridKey, masterColumnMeta],
    () => {
      syncSearchConditions(getFieldDefinitions());
    },
    { immediate: true }
  );

  watch(
    () => searchConditions.value.map(condition => `${condition.key}:${condition.visible ? '1' : '0'}`).join('|'),
    () => {
      hydrateVisibleConditions().catch(() => undefined);
    }
  );

  return {
    showDialog,
    searchConditions,
    visibleConditions,
    activeFilterSummaries,
    open,
    close,
    executeSearch,
    clearSearch,
    ensureLookupConditionReady
  };
}
