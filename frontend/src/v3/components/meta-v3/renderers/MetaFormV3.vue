<script setup lang="ts">
import { computed, unref } from 'vue';
import type { PageComponentWithRules } from '@/v3/composables/meta-v3/types';
import type { ComponentStateByKey, MetaRuntime } from '@/v3/composables/meta-v3/runtime/types';

const props = defineProps<{
  component: PageComponentWithRules;
  runtime: MetaRuntime;
}>();

function resolveComponentState(): Record<string, any> {
  const source = props.runtime?.state?.componentStateByKey;
  const stateByKey = (source && 'value' in source ? source.value : source) as ComponentStateByKey | undefined;
  if (!stateByKey) return {};
  return stateByKey[props.component.componentKey] || {};
}

const state = computed(() => resolveComponentState());
const customRenderer = computed(() => unref(state.value.renderer));
const placeholder = computed(
  () => unref(state.value.placeholder) || `Form \"${props.component.componentKey}\" not configured`
);
const status = computed(() => state.value.status || 'ready');
const errorMessage = computed(() => state.value.error?.message || 'Form render failed');
</script>

<template>
  <div class="meta-form">
    <div v-if="status === 'error'" class="meta-form-error">
      {{ errorMessage }}
    </div>
    <component :is="customRenderer" v-else-if="customRenderer" :component="component" :runtime="runtime" />
    <div v-else class="meta-form-placeholder">
      {{ placeholder }}
    </div>
  </div>
</template>

<style scoped>
.meta-form {
  width: 100%;
}

.meta-form-error {
  padding: 12px;
  border: 1px dashed #ffccc7;
  border-radius: 4px;
  color: #d03050;
  background: #fff2f0;
  font-size: 12px;
}

.meta-form-placeholder {
  padding: 12px;
  border: 1px dashed #d9d9d9;
  border-radius: 4px;
  color: #666;
  font-size: 12px;
}
</style>
