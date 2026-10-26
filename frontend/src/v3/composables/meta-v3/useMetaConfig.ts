import { parseMetaConfig } from '@/v3/composables/meta-v3/useConfigParser';
import { loadPageMeta } from '@/v3/composables/meta-v3/useMetaLoader';
import { createMetaConfigState } from '@/v3/composables/meta-v3/createMetaConfigState';
import { loadPageComponents } from '@/v3/composables/meta-v3/useComponentLoader';
import { compileMetaRules } from '@/v3/composables/meta-v3/useRuleCompiler';

export function useMetaConfig(pageCode: string, notifyError: (message: string) => void) {
  const state = createMetaConfigState();
  const {
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
  } = state;

  async function loadComponents() {
    const componentBundle = await loadPageComponents(pageCode);
    if (!componentBundle) {
      notifyError('加载页面组件失败');
      return false;
    }

    pageComponents.value = componentBundle.components;
    rulesByComponent.value = componentBundle.rulesByComponent;
    masterGridKey.value = componentBundle.masterGridKey ?? null;
    detailTabsKey.value = componentBundle.detailTabsKey ?? null;
    layoutDetailTypeRef.value = componentBundle.detailType ?? null;
    layoutSplitConfigRef.value = componentBundle.splitConfig || null;
    return true;
  }

  function parseConfig() {
    const components = pageComponents.value || [];
    if (components.length === 0) {
      notifyError('页面组件为空');
      return false;
    }

    const parsedConfig = parseMetaConfig({
      components,
      rulesByComponent: rulesByComponent.value,
      masterGridKey: masterGridKey.value ?? undefined,
      detailTabsKey: detailTabsKey.value ?? undefined,
      layoutDetailType: layoutDetailTypeRef.value,
      layoutSplitConfig: layoutSplitConfigRef.value
    });

    if (!parsedConfig) {
      notifyError('页面配置解析失败');
      return false;
    }

    pageConfig.value = parsedConfig.pageConfig;
    broadcastFields.value = parsedConfig.broadcastFields;
    masterGridOptions.value = parsedConfig.masterGridOptions;
    detailGridOptionsByTab.value = parsedConfig.detailGridOptionsByTab;
    detailLayoutMode.value = parsedConfig.detailLayoutMode;
    detailSplitConfig.value = parsedConfig.detailSplitConfig;
    return true;
  }

  async function loadMeta() {
    if (!pageConfig.value) return false;

    const pageMeta = await loadPageMeta({
      pageCode,
      pageConfig: pageConfig.value,
      masterGridKey: masterGridKey.value ?? undefined,
      masterGridOptions: masterGridOptions.value,
      detailGridOptionsByTab: detailGridOptionsByTab.value
    });

    if (!pageMeta) {
      notifyError('加载主表元数据失败');
      return false;
    }

    masterColumnDefs.value = pageMeta.masterColumnDefs;
    masterRowClassGetter.value = pageMeta.masterRowClassGetter;
    masterColumnMeta.value = pageMeta.masterColumnMeta;
    masterPkColumn.value = pageMeta.masterPkColumn;
    masterSumFields.value = pageMeta.masterSumFields;
    detailColumnsByTab.value = pageMeta.detailColumnsByTab;
    detailRowClassGetterByTab.value = pageMeta.detailRowClassGetterByTab;
    detailColumnMetaByTab.value = pageMeta.detailColumnMetaByTab;
    detailFkColumnByTab.value = pageMeta.detailFkColumnByTab;
    detailPkColumnByTab.value = pageMeta.detailPkColumnByTab;
    detailSumFieldsByTab.value = pageMeta.detailSumFieldsByTab;
    return true;
  }

  function compileRules() {
    return compileMetaRules({
      pageCode,
      pageConfig: pageConfig.value,
      pageComponents: pageComponents.value || [],
      rulesByComponent: rulesByComponent.value,
      masterGridKey: masterGridKey.value ?? undefined,
      detailTabsKey: detailTabsKey.value ?? undefined,
      masterColumnDefs,
      detailColumnsByTab,
      masterColumnMeta,
      detailColumnMetaByTab,
      masterValidationRules,
      detailValidationRulesByTab,
      masterLookupRules,
      detailLookupRulesByTab,
      compiledMasterCalcRules,
      compiledAggRules,
      detailCalcRulesByTab,
      masterContextMenu,
      detailContextMenuDefault,
      detailContextMenuByTab,
      masterRowEditableRules,
      masterCellEditableRules,
      masterRowClassRules,
      detailRowClassRulesByTab,
      detailRowEditableRulesByTab,
      detailCellEditableRulesByTab,
      masterToolbar,
      detailToolbarByTab
    });
  }

  async function loadMetadata() {
    const ok = await loadComponents();
    if (!ok) return false;
    if (!parseConfig()) return false;
    if (!(await loadMeta())) return false;
    return compileRules();
  }

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
    masterLookupRules,
    detailLookupRulesByTab,
    masterRowEditableRules,
    masterCellEditableRules,
    masterRowClassRules,
    detailRowClassRulesByTab,
    detailRowEditableRulesByTab,
    detailCellEditableRulesByTab,
    masterToolbar,
    detailToolbarByTab,
    masterSumFields,
    detailSumFieldsByTab,
    loadComponents,
    parseConfig,
    loadMeta,
    compileRules,
    loadMetadata
  };
}
