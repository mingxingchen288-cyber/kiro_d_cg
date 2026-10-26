import { ref, shallowRef } from 'vue';
import type { GridApi } from 'ag-grid-community';
import { useMetaConfig } from '@/v3/composables/meta-v3/useMetaConfig';
import { useCalcBroadcast } from '@/v3/composables/meta-v3/useCalcBroadcast';
import { useAdvancedSearch } from '@/v3/composables/meta-v3/useAdvancedSearch';
import { useUserGridConfig } from '@/v3/composables/meta-v3/useUserGridConfig';
import { useCustomExport } from '@/v3/composables/meta-v3/useCustomExport';
import { useWorkingSetStore } from '@/v3/composables/meta-v3/useWorkingSetStore';
import { fetchMyPageButtons } from '@/service/api/role-manage';
import { createRuntimeLogger } from './logger';
import { useRuntimeLookup } from './useRuntimeLookup';
import { useRuntimeMetadataReload } from './useRuntimeMetadataReload';
import { useRuntimeActions } from './useRuntimeActions';
import { useRuntimeState } from './useRuntimeState';
import { useRuntimeMutations } from './useRuntimeMutations';
import { useRuntimeBootstrap } from './useRuntimeBootstrap';
import { useRuntimeComponentState } from './useRuntimeComponentState';
import type { MetaError, RuntimeFeatures, RuntimeStage } from './types';

type NotifyFn = (message: string) => void;

export type BaseRuntimeOptions = {
  pageCode: string;
  initialMasterId?: number | null;
  notifyInfo: NotifyFn;
  notifyError: NotifyFn;
  notifySuccess: NotifyFn;
};

const DEFAULT_FEATURES: Required<RuntimeFeatures> = {
  detailTabs: true,
  broadcast: true,
  aggregates: true,
  lookup: true,
  export: true,
  contextMenu: true
};

function resolveFeatures(features?: RuntimeFeatures): Required<RuntimeFeatures> {
  return { ...DEFAULT_FEATURES, ...(features || {}) };
}

function makeError(params: {
  pageCode: string;
  stage: RuntimeStage;
  message: string;
  componentKey?: string;
  code?: string;
  raw?: unknown;
}): MetaError {
  return {
    code: params.code || 'META_RUNTIME_ERROR',
    message: params.message,
    stage: params.stage,
    pageCode: params.pageCode,
    componentKey: params.componentKey,
    raw: params.raw
  };
}

export function useBaseRuntime(options: BaseRuntimeOptions, features?: RuntimeFeatures) {
  const { pageCode, initialMasterId, notifyInfo, notifyError, notifySuccess } = options;
  const autoFeatureEnabled = !features;
  const resolvedFeatures = ref<Required<RuntimeFeatures>>(resolveFeatures(features));
  const logger = createRuntimeLogger(pageCode, notifyError);

  const masterGridApi = shallowRef<GridApi | null>(null);
  const detailGridApisByTab = ref<Record<string, any>>({});
  const activeMasterRowKey = ref<string | null>(null);

  const meta = useMetaConfig(pageCode, notifyError);
  const {
    loadComponents: loadComponentsRaw,
    parseConfig: parseConfigRaw,
    loadMeta: loadMetaRaw,
    compileRules: compileRulesRaw,
    ...metaApi
  } = meta;
  const gridConfig = useUserGridConfig({ pageCode, notifyError, notifySuccess });
  const isReady = ref(false);
  const buttonPermissions = ref<Set<string>>(new Set());
  const {
    runtimeStatus,
    runtimeError,
    componentStateByKey,
    componentErrors,
    reportComponentError,
    refreshAutoFeatures
  } = useRuntimeState({
    pageCode,
    logger,
    autoFeatureEnabled,
    resolvedFeatures,
    meta: {
      pageConfig: meta.pageConfig,
      detailCalcRulesByTab: meta.detailCalcRulesByTab,
      compiledAggRules: meta.compiledAggRules,
      compiledMasterCalcRules: meta.compiledMasterCalcRules,
      masterLookupRules: meta.masterLookupRules,
      detailLookupRulesByTab: meta.detailLookupRulesByTab,
      masterGridKey: meta.masterGridKey,
      pageComponents: meta.pageComponents
    },
    makeError
  });

  const workingSet = useWorkingSetStore({
    pageCode,
    pageConfig: meta.pageConfig,
    detailFkColumnByTab: meta.detailFkColumnByTab,
    masterPkColumn: meta.masterPkColumn,
    detailPkColumnByTab: meta.detailPkColumnByTab,
    masterValidationRules: meta.masterValidationRules,
    detailValidationRulesByTab: meta.detailValidationRulesByTab,
    masterColumnMeta: meta.masterColumnMeta,
    detailColumnMetaByTab: meta.detailColumnMetaByTab,
    masterGridApi,
    detailGridApisByTab,
    activeMasterRowKey,
    initialMasterId,
    notifyInfo,
    notifyError,
    notifySuccess
  });

  const calc = useCalcBroadcast({
    masterGridApi,
    getMasterRowById: workingSet.getMasterRowById,
    getMasterRowByRowKey: workingSet.getMasterRowByRowKey,
    resolveMasterRowKey: workingSet.resolveMasterRowKey,
    detailCache: workingSet.detailCache,
    detailCalcRulesByTab: meta.detailCalcRulesByTab,
    compiledAggRules: meta.compiledAggRules,
    compiledMasterCalcRules: meta.compiledMasterCalcRules,
    pageConfig: meta.pageConfig,
    loadDetailData: workingSet.loadDetailData,
    detailGridApisByTab,
    rowStateApi: workingSet.rowStateApi
  });

  const calcApi = {
    markFieldChange: calc.markFieldChange,
    runMasterCalc: calc.runMasterCalc,
    runDetailCalc: (
      node: any,
      api: any,
      row: any,
      masterId: number,
      tabKey: string,
      masterRowKey?: string,
      changedFields?: string | string[],
      valueOverrides?: Record<string, any>
    ) => {
      if (!resolvedFeatures.value.detailTabs) return;
      return calc.runDetailCalc(node, api, row, masterId, tabKey, masterRowKey, changedFields, valueOverrides);
    },
    recalcAggregates: (masterId: number, masterRowKey?: string) => {
      if (!resolvedFeatures.value.aggregates) return;
      return calc.recalcAggregates(masterId, masterRowKey);
    },
    broadcastToDetail: async (masterId: number, row: any, changedFields?: string | string[]) => {
      if (!resolvedFeatures.value.broadcast) return;
      return calc.broadcastToDetail(masterId, row, changedFields);
    }
  };

  const {
    addMasterRow,
    deleteMasterRow,
    copyMasterRow,
    addDetailRow,
    deleteDetailRow,
    copyDetailRow,
    commitMasterPatch,
    commitDetailPatch,
    onMasterCellValueChanged,
    onDetailCellValueChanged
  } = useRuntimeMutations({
    resolvedFeatures,
    masterGridApi,
    detailGridApisByTab,
    activeMasterRowKey,
    addMasterRowRaw: workingSet.addMasterRow,
    deleteMasterRowRaw: workingSet.deleteMasterRow,
    copyMasterRowRaw: workingSet.copyMasterRow,
    addDetailRowRaw: workingSet.addDetailRow,
    deleteDetailRowRaw: workingSet.deleteDetailRow,
    copyDetailRowRaw: workingSet.copyDetailRow,
    applyMasterPatchRaw: workingSet.applyMasterPatch,
    applyDetailPatchRaw: workingSet.applyDetailPatch,
    markFieldChange: calcApi.markFieldChange,
    runMasterCalc: calcApi.runMasterCalc,
    runDetailCalc: calcApi.runDetailCalc,
    recalcAggregates: calcApi.recalcAggregates,
    broadcastToDetail: calcApi.broadcastToDetail,
    isLoadingMasterRows: workingSet.isLoadingMasterRows,
    isLoadingDetailRows: workingSet.isLoadingDetailRows
  });

  const runtimeLookup = useRuntimeLookup({
    resolvedFeatures,
    meta: {
      masterCellEditableRules: meta.masterCellEditableRules,
      masterRowEditableRules: meta.masterRowEditableRules,
      masterLookupRules: meta.masterLookupRules,
      detailLookupRulesByTab: meta.detailLookupRulesByTab
    },
    rowStateApi: workingSet.rowStateApi,
    commitMasterPatch,
    commitDetailPatch
  });

  const advancedSearch = useAdvancedSearch({
    pageCode,
    pageConfig: meta.pageConfig,
    masterGridKey: meta.masterGridKey,
    masterColumnMeta: meta.masterColumnMeta,
    detailColumnMetaByTab: meta.detailColumnMetaByTab,
    masterColumnDefs: meta.masterColumnDefs,
    detailColumnDefsByTab: meta.detailColumnsByTab,
    masterLookupRules: meta.masterLookupRules,
    detailLookupRulesByTab: meta.detailLookupRulesByTab,
    masterGridApi,
    setAdvancedConditions: workingSet.setAdvancedConditions,
    clearAdvancedConditions: workingSet.clearAdvancedConditions,
    clearAllCache: workingSet.clearAllCache,
    notifyInfo
  });

  const { save } = workingSet;

  const customExport = useCustomExport({
    pageCode,
    masterGridApi,
    notifyInfo,
    notifyError,
    notifySuccess
  });

  let runtimeApi: any;
  const { executeAction, registerActionHandler } = useRuntimeActions({
    pageCode,
    notifyError,
    notifySuccess,
    getRuntime: () => runtimeApi,
    masterGridApi,
    activeMasterRowKey,
    pageConfig: meta.pageConfig,
    data: {
      detailCache: workingSet.detailCache,
      getMasterRowByRowKey: workingSet.getMasterRowByRowKey,
      reloadMasterRow: workingSet.reloadMasterRow,
      loadDetailData: workingSet.loadDetailData,
      clearAllCache: workingSet.clearAllCache
    }
  });

  const actions = {
    advancedSearch,
    executeAction,
    save,
    customExportConfigs: customExport.customExportConfigs,
    executeCustomExport: customExport.executeCustomExport
  };

  const mutations = {
    addMasterRow,
    deleteMasterRow,
    copyMasterRow,
    addDetailRow,
    deleteDetailRow,
    copyDetailRow,
    onMasterCellValueChanged,
    onDetailCellValueChanged
  };

  const gridConfigApi = {
    applyGridConfig: gridConfig.applyGridConfig,
    saveGridConfig: gridConfig.saveGridConfig
  };

  const stateApi = {
    componentStateByKey,
    pageError: runtimeError,
    reportComponentError
  };

  function hasButtonPermission(buttonKey: string) {
    const permissions = buttonPermissions.value;
    return permissions.has('*') || permissions.has(buttonKey);
  }

  fetchMyPageButtons(pageCode)
    .then(buttons => {
      buttonPermissions.value = new Set(buttons || []);
    })
    .catch(() => {
      buttonPermissions.value = new Set();
    });

  runtimeApi = {
    pageCode,
    permissions: {
      buttonPermissions,
      hasButton: hasButtonPermission
    },
    masterGridApi,
    detailGridApisByTab,
    activeMasterRowKey,
    rowStateApi: workingSet.rowStateApi,
    workingSet,
    meta: metaApi,
    state: stateApi,
    calc: calcApi,
    lookup: runtimeLookup,
    mutations,
    actions,
    gridConfig: gridConfigApi
  };

  registerActionHandler('advancedSearch', () => advancedSearch.open());

  const { buildStates, applyExtensions } = useRuntimeComponentState({
    logger,
    meta: {
      pageComponents: meta.pageComponents,
      masterGridKey: meta.masterGridKey,
      masterColumnDefs: meta.masterColumnDefs
    },
    componentStateByKey,
    componentErrors
  });

  const { init, loadComponents, parseConfig, loadMeta, compileRules } = useRuntimeBootstrap({
    pageCode,
    logger,
    meta: {
      pageComponents: meta.pageComponents,
      masterGridKey: meta.masterGridKey
    },
    runtimeStatus,
    runtimeError,
    isReady,
    reportComponentError,
    refreshAutoFeatures,
    makeError,
    loadComponentsRaw,
    parseConfigRaw,
    loadMetaRaw,
    compileRulesRaw,
    buildStates,
    applyExtensions
  });

  const { reloadMetadata } = useRuntimeMetadataReload({
    pageCode,
    resolvedFeatures,
    meta: {
      pageComponents: meta.pageComponents,
      masterGridKey: meta.masterGridKey,
      masterColumnDefs: meta.masterColumnDefs,
      detailColumnsByTab: meta.detailColumnsByTab
    },
    componentStateByKey,
    masterGridApi,
    detailGridApisByTab,
    detailCache: workingSet.detailCache,
    resolveMasterRowKey: workingSet.resolveMasterRowKey,
    rowStateApi: workingSet.rowStateApi,
    applyGridConfig: gridConfig.applyGridConfig,
    loadComponents: loadComponentsRaw,
    parseConfig: parseConfigRaw,
    loadMeta: loadMetaRaw,
    compileRules: compileRulesRaw,
    refreshAutoFeatures,
    runMasterCalc: calcApi.runMasterCalc,
    broadcastToDetail: calcApi.broadcastToDetail
  });

  return {
    isReady,
    features: resolvedFeatures,
    init,
    reloadMetadata,
    ...runtimeApi
  };
}
