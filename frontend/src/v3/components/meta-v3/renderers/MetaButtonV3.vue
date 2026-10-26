<script setup lang="ts">
import { computed, unref } from 'vue';
import { NButton } from 'naive-ui';
import type { ButtonProps } from 'naive-ui';
import type { PageComponentWithRules } from '@/v3/composables/meta-v3/types';
import type { ComponentStateByKey, MetaRuntime } from '@/v3/composables/meta-v3/runtime/types';

type ButtonConfig = {
  text?: string;
  label?: string;
  type?: string;
  size?: string;
  disabled?: boolean;
  action?: string;
  tableCode?: string;
  actionData?: Record<string, any>;
  /** 是否需要选中行才能执行 */
  requiresRow?: boolean;
  /** 执行后刷新模式: 'all' 刷新全部, 'row' 刷新选中行, 'none' 不刷新 */
  refreshMode?: 'all' | 'row' | 'none';
};

const props = defineProps<{
  component: PageComponentWithRules;
  runtime: MetaRuntime;
}>();

function parseButtonConfig(config?: string): ButtonConfig {
  if (!config) return {};
  try {
    return JSON.parse(config) as ButtonConfig;
  } catch (error) {
    console.warn('[MetaV3] button config parse failed', error);
    return {};
  }
}

function resolveComponentState(): Record<string, any> {
  const source = props.runtime?.state?.componentStateByKey;
  const stateByKey = (source && 'value' in source ? source.value : source) as ComponentStateByKey | undefined;
  if (!stateByKey) return {};
  return stateByKey[props.component.componentKey] || {};
}

const config = computed(() => parseButtonConfig(props.component.componentConfig));
const state = computed(() => resolveComponentState());

const label = computed(() => config.value.label || config.value.text || props.component.componentKey);
const buttonType = computed<ButtonProps['type']>(() => (config.value.type as ButtonProps['type']) || 'default');
const buttonSize = computed<ButtonProps['size']>(() => (config.value.size as ButtonProps['size']) || 'medium');
const status = computed(() => state.value.status || 'ready');

// 获取选中行
function getSelectedRow(): Record<string, any> | null {
  const runtime = props.runtime as Record<string, any>;
  const gridApi = runtime.masterGridApi?.value;
  if (!gridApi) return null;
  const selectedNodes = gridApi.getSelectedNodes();
  return selectedNodes?.[0]?.data || null;
}

// 需要选中行但没有选中时禁用按钮
const requiresRow = computed(() => config.value.requiresRow === true);
const hasSelectedRow = computed(() => getSelectedRow() !== null);
const isDisabled = computed(() => {
  if (config.value.disabled || unref(state.value.disabled) || status.value === 'error') return true;
  if (requiresRow.value && !hasSelectedRow.value) return true;
  return false;
});
const errorMessage = computed(() => state.value.error?.message || 'Button render failed');

function handleClick() {
  if (typeof state.value.onClick === 'function') {
    state.value.onClick({ component: props.component, runtime: props.runtime });
    return;
  }
  const action = config.value.action;
  if (!action) return;

  const runtime = props.runtime as Record<string, any>;
  const actions = runtime.actions;
  if (typeof actions?.[action] === 'function') {
    actions[action](props.component);
    return;
  }
  if (typeof actions?.executeAction === 'function') {
    const selectedRow = getSelectedRow();
    // 默认刷新模式：需要选中行时刷新行，否则刷新全部
    const defaultRefreshMode = requiresRow.value ? 'row' : 'all';
    const refreshMode = config.value.refreshMode ?? defaultRefreshMode;

    actions.executeAction(action, {
      tableCode: config.value.tableCode,
      data: config.value.actionData,
      selectedRow,
      refreshMode
    });
  }
}
</script>

<template>
  <div class="meta-button">
    <div v-if="status === 'error'" class="meta-button-error">
      {{ errorMessage }}
    </div>
    <NButton v-else :type="buttonType" :size="buttonSize" :disabled="isDisabled" @click="handleClick">
      {{ label }}
    </NButton>
  </div>
</template>

<style scoped>
.meta-button {
  display: inline-flex;
}

.meta-button-error {
  padding: 6px 10px;
  border: 1px dashed #ffccc7;
  border-radius: 4px;
  color: #d03050;
  background: #fff2f0;
  font-size: 12px;
}
</style>
