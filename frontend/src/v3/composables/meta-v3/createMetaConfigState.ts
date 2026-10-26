import { shallowRef } from 'vue';
import type { ColDef } from 'ag-grid-community';
import type { LookupRule } from '@/v3/composables/meta-v3/useMetaColumns';
import type {
  CellEditableRule,
  ContextMenuRule,
  GridStyleRule,
  PageComponentWithRules,
  PageRule,
  RowEditableRule,
  SplitLayoutConfig,
  ToolbarRule
} from '@/v3/composables/meta-v3/types';
import type { ParsedPageConfig, ValidationRule } from '@/v3/logic/calc-engine';
import { compileAggRules, compileCalcRules } from '@/v3/logic/calc-engine';
import type { ResolvedGridOptions } from '@/v3/composables/meta-v3/grid-options';

export function createMetaConfigState() {
  const pageConfig = shallowRef<ParsedPageConfig | null>(null);
  const pageComponents = shallowRef<PageComponentWithRules[]>([]);
  const rulesByComponent = shallowRef<Map<string, PageRule[]>>(new Map());
  const broadcastFields = shallowRef<string[]>([]);
  const masterColumnDefs = shallowRef<ColDef[]>([]);
  const detailColumnsByTab = shallowRef<Record<string, ColDef[]>>({});
  const detailCalcRulesByTab = shallowRef<Record<string, ReturnType<typeof compileCalcRules>>>({});
  const detailFkColumnByTab = shallowRef<Record<string, string>>({});
  const masterPkColumn = shallowRef<string>('ID');
  const detailPkColumnByTab = shallowRef<Record<string, string>>({});
  const compiledAggRules = shallowRef<ReturnType<typeof compileAggRules>>([]);
  const compiledMasterCalcRules = shallowRef<ReturnType<typeof compileCalcRules>>([]);
  const masterRowClassGetter = shallowRef<((params: any) => string | undefined) | undefined>(undefined);
  const detailRowClassGetterByTab = shallowRef<Record<string, ((params: any) => string | undefined) | undefined>>({});
  const masterGridOptions = shallowRef<ResolvedGridOptions | null>(null);
  const detailGridOptionsByTab = shallowRef<Record<string, ResolvedGridOptions>>({});
  const detailLayoutMode = shallowRef<'nested' | 'split'>('nested');
  const detailSplitConfig = shallowRef<SplitLayoutConfig | null>(null);
  const masterGridKey = shallowRef<string | null>(null);
  const detailTabsKey = shallowRef<string | null>(null);
  const masterValidationRules = shallowRef<ValidationRule[]>([]);
  const detailValidationRulesByTab = shallowRef<Record<string, ValidationRule[]>>({});
  const masterColumnMeta = shallowRef<any[]>([]);
  const detailColumnMetaByTab = shallowRef<Record<string, any[]>>({});
  const masterContextMenu = shallowRef<ContextMenuRule | null>(null);
  const detailContextMenuByTab = shallowRef<Record<string, ContextMenuRule | null>>({});
  const detailContextMenuDefault = shallowRef<ContextMenuRule | null>(null);
  const masterLookupRules = shallowRef<LookupRule[]>([]);
  const detailLookupRulesByTab = shallowRef<Record<string, LookupRule[]>>({});
  const layoutDetailTypeRef = shallowRef<string | null>(null);
  const layoutSplitConfigRef = shallowRef<SplitLayoutConfig | null>(null);
  const masterRowEditableRules = shallowRef<RowEditableRule[]>([]);
  const masterCellEditableRules = shallowRef<CellEditableRule[]>([]);
  const masterRowClassRules = shallowRef<GridStyleRule[]>([]);
  const detailRowClassRulesByTab = shallowRef<Record<string, GridStyleRule[]>>({});
  const detailRowEditableRulesByTab = shallowRef<Record<string, RowEditableRule[]>>({});
  const detailCellEditableRulesByTab = shallowRef<Record<string, CellEditableRule[]>>({});
  const masterToolbar = shallowRef<ToolbarRule | null>(null);
  const detailToolbarByTab = shallowRef<Record<string, ToolbarRule | null>>({});
  const masterSumFields = shallowRef<string[]>([]);
  const detailSumFieldsByTab = shallowRef<Record<string, string[]>>({});

  return {
    pageConfig,
    pageComponents,
    rulesByComponent,
    broadcastFields,
    masterColumnDefs,
    detailColumnsByTab,
    detailCalcRulesByTab,
    detailFkColumnByTab,
    masterPkColumn,
    detailPkColumnByTab,
    compiledAggRules,
    compiledMasterCalcRules,
    masterRowClassGetter,
    detailRowClassGetterByTab,
    masterGridOptions,
    detailGridOptionsByTab,
    detailLayoutMode,
    detailSplitConfig,
    masterGridKey,
    detailTabsKey,
    masterValidationRules,
    detailValidationRulesByTab,
    masterColumnMeta,
    detailColumnMetaByTab,
    masterContextMenu,
    detailContextMenuByTab,
    detailContextMenuDefault,
    masterLookupRules,
    detailLookupRulesByTab,
    layoutDetailTypeRef,
    layoutSplitConfigRef,
    masterRowEditableRules,
    masterCellEditableRules,
    masterRowClassRules,
    detailRowClassRulesByTab,
    detailRowEditableRulesByTab,
    detailCellEditableRulesByTab,
    masterToolbar,
    detailToolbarByTab,
    masterSumFields,
    detailSumFieldsByTab
  };
}
