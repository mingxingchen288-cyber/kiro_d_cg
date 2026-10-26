import type { ShallowRef } from 'vue';
import type { ColDef } from 'ag-grid-community';
import { type LookupRule, extractLookupRules } from '@/v3/composables/meta-v3/useMetaColumns';
import type {
  CellEditableRule,
  ContextMenuRule,
  GridStyleRule,
  PageComponentWithRules,
  PageRule,
  RowEditableRule,
  ToolbarRule
} from '@/v3/composables/meta-v3/types';
import {
  type ParsedPageConfig,
  type ValidationRule,
  compileAggRules,
  compileCalcRules,
  parseValidationRules
} from '@/v3/logic/calc-engine';
import {
  applyCellStyleRules,
  getComponentRules,
  parseAggregateRuleConfig,
  parseCalcRuleConfig,
  parseCellEditableRule,
  parseContextMenuRule,
  parseGridStyleRule,
  parseLookupRuleConfig,
  parseRowEditableRule,
  parseToolbarRule,
  parseValidationRuleConfig
} from '@/v3/composables/meta-v3/usePageRules';
import { getComponentConfig, getDetailGridComponentConfig } from '@/v3/composables/meta-v3/useComponentLoader';
import { collectRulesByKeys, mergeLookupRules, uniqueKeys } from '@/v3/composables/meta-v3/meta-config-shared';

type ColumnMetadata = Api.Metadata.ColumnMetadata;
type CompiledCalcRules = ReturnType<typeof compileCalcRules>;
type CompiledAggRules = ReturnType<typeof compileAggRules>;

type RuleCompilerParams = {
  pageCode: string;
  pageConfig: ParsedPageConfig | null;
  pageComponents: PageComponentWithRules[];
  rulesByComponent: Map<string, PageRule[]>;
  masterGridKey?: string;
  detailTabsKey?: string;
  masterColumnDefs: ShallowRef<ColDef[]>;
  detailColumnsByTab: ShallowRef<Record<string, ColDef[]>>;
  masterColumnMeta: ShallowRef<ColumnMetadata[]>;
  detailColumnMetaByTab: ShallowRef<Record<string, ColumnMetadata[]>>;
  masterValidationRules: ShallowRef<ValidationRule[]>;
  detailValidationRulesByTab: ShallowRef<Record<string, ValidationRule[]>>;
  masterLookupRules: ShallowRef<LookupRule[]>;
  detailLookupRulesByTab: ShallowRef<Record<string, LookupRule[]>>;
  compiledMasterCalcRules: ShallowRef<CompiledCalcRules>;
  compiledAggRules: ShallowRef<CompiledAggRules>;
  detailCalcRulesByTab: ShallowRef<Record<string, CompiledCalcRules>>;
  masterContextMenu: ShallowRef<ContextMenuRule | null>;
  detailContextMenuDefault: ShallowRef<ContextMenuRule | null>;
  detailContextMenuByTab: ShallowRef<Record<string, ContextMenuRule | null>>;
  masterRowEditableRules: ShallowRef<RowEditableRule[]>;
  masterCellEditableRules: ShallowRef<CellEditableRule[]>;
  masterRowClassRules: ShallowRef<GridStyleRule[]>;
  detailRowClassRulesByTab: ShallowRef<Record<string, GridStyleRule[]>>;
  detailRowEditableRulesByTab: ShallowRef<Record<string, RowEditableRule[]>>;
  detailCellEditableRulesByTab: ShallowRef<Record<string, CellEditableRule[]>>;
  masterToolbar: ShallowRef<ToolbarRule | null>;
  detailToolbarByTab: ShallowRef<Record<string, ToolbarRule | null>>;
};

function applyLookupFieldClass(columns: ColDef[], lookupRules: LookupRule[]): ColDef[] {
  const lookupFields = new Set(lookupRules.map(rule => rule.columnName).filter(Boolean));
  if (lookupFields.size === 0) return columns;

  return columns.map(column => {
    if (column.field && lookupFields.has(column.field)) {
      return { ...column, cellClass: 'lookup-field' };
    }
    return column;
  });
}

export function compileMetaRules(params: RuleCompilerParams): boolean {
  const config = params.pageConfig;
  if (!config) return false;

  const resolvedMasterGridKey = params.masterGridKey ?? undefined;
  const resolvedDetailTabsKey = params.detailTabsKey ?? undefined;
  const masterRuleKeys = uniqueKeys([resolvedMasterGridKey, 'master', 'masterGrid']);
  const masterRules = collectRulesByKeys(params.rulesByComponent, masterRuleKeys);
  const masterRuleLabel = resolvedMasterGridKey || 'master';

  const masterValidation = parseValidationRuleConfig(masterRuleLabel, masterRules);
  params.masterValidationRules.value =
    masterValidation.length > 0 ? masterValidation : parseValidationRules(params.masterColumnMeta.value);

  const masterLookup = parseLookupRuleConfig(masterRuleLabel, masterRules);
  params.masterLookupRules.value = mergeLookupRules(extractLookupRules(params.masterColumnMeta.value), masterLookup);
  params.masterColumnDefs.value = applyLookupFieldClass(params.masterColumnDefs.value, params.masterLookupRules.value);

  const masterCalcRules = parseCalcRuleConfig(masterRuleLabel, masterRules);
  if (masterCalcRules.length > 0) {
    params.compiledMasterCalcRules.value = compileCalcRules(masterCalcRules, `${params.pageCode}_master`);
  } else {
    params.compiledMasterCalcRules.value = [];
  }

  const masterAggRules = parseAggregateRuleConfig(masterRuleLabel, masterRules);
  if (masterAggRules.length > 0) {
    params.compiledAggRules.value = compileAggRules(masterAggRules, `${params.pageCode}_agg`);
  } else if (config.aggregates?.length) {
    params.compiledAggRules.value = compileAggRules(config.aggregates, `${params.pageCode}_agg`);
  } else {
    params.compiledAggRules.value = [];
  }

  params.detailValidationRulesByTab.value = {};
  params.detailLookupRulesByTab.value = {};
  params.detailCalcRulesByTab.value = {};
  params.detailContextMenuByTab.value = {};

  const masterComponentConfig = getComponentConfig(params.pageComponents || [], resolvedMasterGridKey || 'masterGrid');
  params.masterContextMenu.value = parseContextMenuRule(masterRuleLabel, masterRules, masterComponentConfig);
  params.masterRowEditableRules.value = parseRowEditableRule(masterRuleLabel, masterRules);
  params.masterCellEditableRules.value = parseCellEditableRule(masterRuleLabel, masterRules);
  params.masterRowClassRules.value = parseGridStyleRule(masterRuleLabel, masterRules);
  params.masterColumnDefs.value = applyCellStyleRules(params.masterColumnDefs.value, params.masterRowClassRules.value);
  params.masterToolbar.value = parseToolbarRule(masterRuleLabel, masterRules, masterComponentConfig);

  params.detailContextMenuDefault.value = null;
  const detailGlobalRules = getComponentRules(params.rulesByComponent, [resolvedDetailTabsKey || 'detailTabs']);
  params.detailContextMenuDefault.value = parseContextMenuRule(
    resolvedDetailTabsKey || 'detailTabs',
    detailGlobalRules
  );

  for (const tab of config.tabs || []) {
    const tabRules = getComponentRules(params.rulesByComponent, [tab.key]);
    const rawColumns = params.detailColumnMetaByTab.value[tab.key] || [];

    const detailValidation = parseValidationRuleConfig(tab.key, tabRules);
    params.detailValidationRulesByTab.value[tab.key] =
      detailValidation.length > 0 ? detailValidation : parseValidationRules(rawColumns);

    const detailLookup = parseLookupRuleConfig(tab.key, tabRules);
    params.detailLookupRulesByTab.value[tab.key] = mergeLookupRules(extractLookupRules(rawColumns), detailLookup);

    if (params.detailColumnsByTab.value[tab.key]) {
      params.detailColumnsByTab.value[tab.key] = applyLookupFieldClass(
        params.detailColumnsByTab.value[tab.key],
        params.detailLookupRulesByTab.value[tab.key]
      );
    }

    const detailCalcRules = parseCalcRuleConfig(tab.key, tabRules);
    if (detailCalcRules.length > 0) {
      params.detailCalcRulesByTab.value[tab.key] = compileCalcRules(detailCalcRules, `${params.pageCode}_${tab.key}`);
    } else {
      params.detailCalcRulesByTab.value[tab.key] = [];
    }

    const detailGridConfig = getDetailGridComponentConfig(params.pageComponents || [], tab.key);
    params.detailContextMenuByTab.value[tab.key] =
      parseContextMenuRule(tab.key, tabRules, detailGridConfig) || params.detailContextMenuDefault.value;
    params.detailToolbarByTab.value[tab.key] = parseToolbarRule(tab.key, tabRules, detailGridConfig);
    params.detailRowClassRulesByTab.value[tab.key] = parseGridStyleRule(tab.key, tabRules);

    if (params.detailColumnsByTab.value[tab.key]) {
      params.detailColumnsByTab.value[tab.key] = applyCellStyleRules(
        params.detailColumnsByTab.value[tab.key],
        params.detailRowClassRulesByTab.value[tab.key] || []
      );
    }

    params.detailRowEditableRulesByTab.value[tab.key] = parseRowEditableRule(tab.key, tabRules);
    params.detailCellEditableRulesByTab.value[tab.key] = parseCellEditableRule(tab.key, tabRules);
  }

  return true;
}
