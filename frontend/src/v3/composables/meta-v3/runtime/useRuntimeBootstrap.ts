import type { Ref } from 'vue';
import { findFirstGridKey } from './helpers';
import type { MetaError, RuntimeLogger, RuntimeStage } from './types';

type RuntimeBootstrapMeta = {
  pageComponents: Ref<any[]>;
  masterGridKey: Ref<string | null>;
};

type RuntimeBootstrapOptions = {
  pageCode: string;
  logger: RuntimeLogger;
  meta: RuntimeBootstrapMeta;
  runtimeStatus: Ref<'loading' | 'ready' | 'error'>;
  runtimeError: Ref<MetaError | null>;
  isReady: Ref<boolean>;
  reportComponentError: (componentKey: string, stage: RuntimeStage, message: string, raw?: unknown) => void;
  refreshAutoFeatures: () => void;
  makeError: (params: {
    pageCode: string;
    stage: RuntimeStage;
    message: string;
    componentKey?: string;
    code?: string;
    raw?: unknown;
  }) => MetaError;
  loadComponentsRaw: () => Promise<boolean>;
  parseConfigRaw: () => boolean;
  loadMetaRaw: () => Promise<boolean>;
  compileRulesRaw: () => boolean;
  buildStates: () => void;
  applyExtensions: () => void;
};

function resolveMasterComponentKey(meta: RuntimeBootstrapMeta) {
  return meta.masterGridKey.value || findFirstGridKey(meta.pageComponents.value) || 'masterGrid';
}

export function useRuntimeBootstrap(options: RuntimeBootstrapOptions) {
  const {
    pageCode,
    logger,
    meta,
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
  } = options;

  async function loadComponents() {
    logger.log('loadComponents', 'start');
    const ok = await loadComponentsRaw();
    if (!ok) {
      const error = makeError({ pageCode, stage: 'loadComponents', message: 'Failed to load components' });
      runtimeError.value = error;
      runtimeStatus.value = 'error';
      logger.error(error);
      return false;
    }
    return true;
  }

  function parseConfig() {
    logger.log('parseConfig', 'start');
    const ok = parseConfigRaw();
    if (!ok) {
      const error = makeError({ pageCode, stage: 'parseConfig', message: 'Failed to parse page config' });
      runtimeError.value = error;
      runtimeStatus.value = 'error';
      logger.error(error);
      return false;
    }
    return true;
  }

  async function loadMeta() {
    logger.log('loadMeta', 'start');
    const ok = await loadMetaRaw();
    if (!ok) {
      reportComponentError(resolveMasterComponentKey(meta), 'loadMeta', 'Failed to load table metadata');
    }
    return ok;
  }

  function compileRules() {
    logger.log('compileRules', 'start');
    const ok = compileRulesRaw();
    refreshAutoFeatures();
    if (!ok) {
      reportComponentError(resolveMasterComponentKey(meta), 'compileRules', 'Failed to compile rules');
    }
    return ok;
  }

  async function init() {
    const componentsOk = await loadComponents();
    if (!componentsOk) {
      isReady.value = true;
      return;
    }

    const configOk = parseConfig();
    if (!configOk) {
      isReady.value = true;
      return;
    }

    await loadMeta();
    compileRules();
    buildStates();
    applyExtensions();
    runtimeStatus.value = runtimeError.value ? 'error' : 'ready';
    isReady.value = true;
  }

  return {
    init,
    loadComponents,
    parseConfig,
    loadMeta,
    compileRules
  };
}
