import { ref, type Ref } from 'vue';
import { findComponentByKey, findFirstGridKey } from './helpers';
import type {
  ComponentStateByKey,
  MetaError,
  RuntimeFeatures,
  RuntimeLogger,
  RuntimeStage
} from './types';

type RuntimeMetaBindings = {
  pageConfig: Ref<{ tabs?: any[] } | null | undefined>;
  detailCalcRulesByTab: Ref<Record<string, any[]>>;
  compiledAggRules: Ref<any[]>;
  compiledMasterCalcRules: Ref<any[]>;
  masterLookupRules: Ref<any[]>;
  detailLookupRulesByTab: Ref<Record<string, any[]>>;
  masterGridKey: Ref<string | null>;
  pageComponents: Ref<any[]>;
};

type MakeErrorParams = {
  pageCode: string;
  stage: RuntimeStage;
  message: string;
  componentKey?: string;
  code?: string;
  raw?: unknown;
};

type RuntimeStateOptions = {
  pageCode: string;
  logger: RuntimeLogger;
  autoFeatureEnabled: boolean;
  resolvedFeatures: Ref<Required<RuntimeFeatures>>;
  meta: RuntimeMetaBindings;
  makeError: (params: MakeErrorParams) => MetaError;
};

export function useRuntimeState(options: RuntimeStateOptions) {
  const { pageCode, logger, autoFeatureEnabled, resolvedFeatures, meta, makeError } = options;

  const runtimeStatus = ref<'loading' | 'ready' | 'error'>('loading');
  const runtimeError = ref<MetaError | null>(null);
  const componentStateByKey = ref<ComponentStateByKey>({});
  const componentErrors = ref<Record<string, MetaError>>({});

  function resolveComponentType(componentKey: string) {
    const components = meta.pageComponents.value || [];
    const match = findComponentByKey(components, componentKey);
    return match?.componentType || 'UNKNOWN';
  }

  function applyErrorToState(componentKey: string, error: MetaError) {
    const state = componentStateByKey.value[componentKey];
    if (state) {
      state.status = 'error';
      state.error = error;
      return;
    }
    componentStateByKey.value[componentKey] = {
      componentKey,
      componentType: resolveComponentType(componentKey),
      status: 'error',
      error
    };
  }

  function reportComponentError(componentKey: string, stage: RuntimeStage, message: string, raw?: unknown) {
    const error = makeError({ pageCode, stage, message, componentKey, raw });
    componentErrors.value[componentKey] = error;
    applyErrorToState(componentKey, error);
    logger.error(error);
  }

  function deriveFeaturesFromMeta(): Required<RuntimeFeatures> {
    const hasTabs = (meta.pageConfig.value?.tabs?.length ?? 0) > 0;
    const hasDetailCalc = Object.values(meta.detailCalcRulesByTab.value || {}).some(list => (list?.length ?? 0) > 0);
    const hasBroadcast = hasTabs && hasDetailCalc;
    const hasMasterCalc = (meta.compiledMasterCalcRules.value?.length ?? 0) > 0;
    const hasAgg = (meta.compiledAggRules.value?.length ?? 0) > 0 || hasMasterCalc;
    const masterLookup = (meta.masterLookupRules.value?.length ?? 0) > 0;
    const detailLookup = Object.values(meta.detailLookupRulesByTab.value || {}).some(list => (list?.length ?? 0) > 0);
    const hasLookup = masterLookup || detailLookup;
    const hasGrid = Boolean(meta.masterGridKey.value || findFirstGridKey(meta.pageComponents.value || []));

    return {
      detailTabs: hasTabs,
      broadcast: hasBroadcast,
      aggregates: hasAgg,
      lookup: hasLookup,
      export: hasGrid,
      contextMenu: hasGrid
    };
  }

  function refreshAutoFeatures() {
    if (!autoFeatureEnabled) return;
    resolvedFeatures.value = deriveFeaturesFromMeta();
  }

  return {
    runtimeStatus,
    runtimeError,
    componentStateByKey,
    componentErrors,
    reportComponentError,
    refreshAutoFeatures
  };
}
