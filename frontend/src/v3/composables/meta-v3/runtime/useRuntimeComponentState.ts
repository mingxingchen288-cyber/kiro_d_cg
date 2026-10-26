import { watch, type Ref } from 'vue';
import { resolveFormRenderer } from '@/v3/composables/meta-v3/form-renderer-registry';
import { findFirstGridKey, flattenComponents } from './helpers';
import type { ComponentState, FormState, GridState, RuntimeLogger } from './types';

type RuntimeComponentMeta = {
  pageComponents: Ref<any[]>;
  masterGridKey: Ref<string | null>;
  masterColumnDefs: Ref<any[]>;
};

type RuntimeComponentStateOptions = {
  logger: RuntimeLogger;
  meta: RuntimeComponentMeta;
  componentStateByKey: Ref<Record<string, ComponentState>>;
  componentErrors: Ref<Record<string, any>>;
};

export function useRuntimeComponentState(options: RuntimeComponentStateOptions) {
  const { logger, meta, componentStateByKey, componentErrors } = options;

  let watchersAttached = false;

  function parseFormComponentConfig(component: any) {
    try {
      return component.componentConfig ? JSON.parse(component.componentConfig) : {};
    } catch (error) {
      console.warn('[MetaV3] form config parse failed', error);
      return {};
    }
  }

  function buildStates() {
    logger.log('buildStates', 'start');
    const components = meta.pageComponents.value || [];
    const flatComponents = flattenComponents(components);
    const hasMasterDetail = flatComponents.some(component => component.componentType === 'MASTER_DETAIL');
    const nextStates: Record<string, ComponentState> = {};

    for (const component of flatComponents) {
      nextStates[component.componentKey] = {
        componentKey: component.componentKey,
        componentType: component.componentType,
        status: 'ready',
        error: componentErrors.value[component.componentKey]
      };
      if (componentErrors.value[component.componentKey]) {
        nextStates[component.componentKey].status = 'error';
      }
    }

    const masterKey = hasMasterDetail ? null : meta.masterGridKey.value || findFirstGridKey(components);
    if (masterKey) {
      const gridError = componentErrors.value[masterKey];
      const gridState: GridState = {
        componentKey: masterKey,
        componentType: 'GRID',
        status: gridError ? 'error' : 'ready',
        error: gridError,
        rowData: [],
        columnDefs: meta.masterColumnDefs.value || []
      };
      nextStates[masterKey] = gridState;
    }

    componentStateByKey.value = nextStates;

    if (!watchersAttached && masterKey) {
      watchersAttached = true;
      watch(
        meta.masterColumnDefs,
        defs => {
          const state = componentStateByKey.value[masterKey] as GridState | undefined;
          if (state) state.columnDefs = defs || [];
        },
        { deep: false }
      );
    }
  }

  function applyExtensions() {
    logger.log('applyExtensions', 'start');
    const components = meta.pageComponents.value || [];
    const flatComponents = flattenComponents(components);

    for (const component of flatComponents) {
      if (component.componentType !== 'FORM') continue;
      const state = componentStateByKey.value[component.componentKey] as FormState | undefined;
      if (!state) continue;
      const config = parseFormComponentConfig(component) as {
        rendererKey?: string;
        variantKey?: string;
        placeholder?: string;
      };
      const rendererKey = config.rendererKey || config.variantKey;
      if (rendererKey) {
        state.renderer = resolveFormRenderer(rendererKey) || state.renderer;
      }
      if (config.placeholder) state.placeholder = config.placeholder;
    }
  }

  return {
    buildStates,
    applyExtensions
  };
}
