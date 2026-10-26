<script setup lang="ts">
import { defineComponent, h, onErrorCaptured, ref } from 'vue';
import type { PageComponentWithRules } from '@/v3/composables/meta-v3/types';
import type { MetaRuntime } from '@/v3/composables/meta-v3/runtime/types';
import { resolveComponentRenderer } from '@/v3/composables/meta-v3/component-renderer-registry';
import { initComponentRenderers } from '@/v3/components/meta-v3/renderers/renderers';

initComponentRenderers();

const props = defineProps<{
  components: PageComponentWithRules[];
  runtime: MetaRuntime;
}>();

const MissingRenderer = defineComponent({
  name: 'MissingRendererV3',
  props: {
    component: { type: Object, required: true },
    runtime: { type: Object, required: false }
  },
  setup(missingProps) {
    console.warn('[MetaV3] missing renderer for component', missingProps.component);
    return () => h('div', { class: 'meta-missing-renderer' }, 'Unsupported component');
  }
});

const RendererBoundary = defineComponent({
  name: 'MetaRendererBoundaryV3',
  props: {
    component: { type: Object, required: true },
    runtime: { type: Object, required: true },
    renderer: { type: Object, required: true }
  },
  setup(boundaryProps) {
    const hasError = ref(false);
    const errorMessage = ref('');

    onErrorCaptured(err => {
      hasError.value = true;
      const message = err instanceof Error ? err.message : String(err);
      errorMessage.value = message || 'Renderer failed';

      const runtime = boundaryProps.runtime as MetaRuntime;
      runtime.state.reportComponentError(boundaryProps.component.componentKey, 'render', message, err);
      return false;
    });

    return () => {
      if (hasError.value) {
        return h('div', { class: 'meta-renderer-error' }, errorMessage.value || 'Render error');
      }
      return h(boundaryProps.renderer as any, {
        component: boundaryProps.component,
        runtime: boundaryProps.runtime
      });
    };
  }
});

function resolveRenderer(component: PageComponentWithRules) {
  return resolveComponentRenderer({ component, runtime: props.runtime }) || MissingRenderer;
}
</script>

<template>
  <RendererBoundary
    v-for="component in components"
    :key="component.componentKey"
    :component="component"
    :runtime="runtime"
    :renderer="resolveRenderer(component)"
  />
</template>

<style scoped>
.meta-renderer-error {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60px;
  padding: 12px;
  color: #d03050;
  background: #fff2f0;
  border: 1px dashed #ffccc7;
  border-radius: 4px;
  font-size: 12px;
}
</style>
