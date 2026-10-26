<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { NEmpty, NSpin, useMessage } from 'naive-ui';
import { useWebSocket } from '@/v3/composables/meta-v3/useWebSocket';
import MetaPageRendererV3 from '@/v3/components/meta-v3/renderers/MetaPageRendererV3.vue';
import LookupDialog from '@/v3/components/LookupDialog.vue';
import AdvancedSearchDialog from '@/v3/components/AdvancedSearchDialog.vue';
import { useBaseRuntime } from '@/v3/composables/meta-v3/runtime';
import { getToken, isAuthShuttingDown } from '@/store/modules/auth/shared';
import { showErrorDialog } from '@/v3/utils/errorDialog';

const props = defineProps<{ pageCode: string }>();
const message = useMessage();
const route = useRoute();
const disposed = ref(false);

const routeMasterId = computed(() => {
  const raw = Array.isArray(route.query.focusId) ? route.query.focusId[0] : route.query.focusId;
  if (raw == null || raw === '') return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
});

function notifyRuntimeError(msg: string) {
  if (disposed.value || isAuthShuttingDown() || !getToken()) return;
  showErrorDialog(msg);
}

const runtime = useBaseRuntime({
  pageCode: props.pageCode,
  initialMasterId: routeMasterId.value,
  notifyInfo: msg => message.info(msg),
  notifyError: notifyRuntimeError,
  notifySuccess: msg => message.success(msg)
});

const { isReady, init } = runtime;
const pageComponents = runtime.meta?.pageComponents;
const {
  lookupDialogRef,
  currentLookupRule,
  currentLookupRowData,
  currentLookupCellValue,
  onLookupSelect,
  onLookupCancel
} = runtime.lookup;
const pageError = runtime.state.pageError;

// WebSocket 订阅：元数据配置变更时热重载
const { subscribe } = useWebSocket();
subscribe('META_CONFIG_CHANGED', payload => {
  const changedPageCode = payload.pageCode;
  if (!changedPageCode || changedPageCode === props.pageCode) {
    runtime.reloadMetadata?.(payload);
  }
});

onMounted(async () => {
  await init();
});

watch(routeMasterId, async masterId => {
  runtime.workingSet?.setRouteMasterId?.(masterId);
  runtime.workingSet?.clearAllCache?.();
  await nextTick();
  const api = runtime.masterGridApi?.value as any;
  api?.deselectAll?.();
  api?.refreshServerSide?.({ purge: true });
});

onBeforeUnmount(() => {
  disposed.value = true;
});
</script>

<template>
  <div class="master-detail-page-v3">
    <div v-if="pageError" class="state">
      <NEmpty :description="pageError.message || 'Page config error'" />
    </div>
    <MetaPageRendererV3 v-else-if="isReady" :components="pageComponents" :runtime="runtime" />
    <div v-else class="state">
      <NSpin size="large" />
    </div>
    <LookupDialog
      v-if="currentLookupRule"
      ref="lookupDialogRef"
      :lookup-code="currentLookupRule.lookupCode"
      :mapping="currentLookupRule.mapping"
      :multiple="currentLookupRule.multiple === true"
      :row-data="currentLookupRowData"
      :filter-field="currentLookupRule.filterField"
      :filter-column="currentLookupRule.filterColumn"
      :filter-value-from="currentLookupRule.filterValueFrom"
      :filter-value="currentLookupCellValue"
      @select="onLookupSelect"
      @cancel="onLookupCancel"
    />
    <AdvancedSearchDialog v-if="isReady" :runtime="runtime" />
  </div>
</template>

<style scoped>
.master-detail-page-v3 {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f5f7fb;
}

.state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

:deep(.cell-new) {
  background-color: #0b3d91 !important;
  color: #ffffff;
}
:deep(.cell-user-changed) {
  background-color: #b7f4b3 !important;
  color: #1a1a1a !important;
}
:deep(.cell-calc-changed) {
  background-color: #fff2a8 !important;
  color: #1a1a1a !important;
}
:deep(.cell-deleted) {
  background-color: #f8d7da !important;
  text-decoration: line-through;
}
:deep(.row-deleted) {
  opacity: 0.5;
}
:deep(.row-new) {
  background-color: #0b3d91;
  color: #ffffff;
  font-style: italic;
}
:deep(.row-confirmed) {
  background-color: #e6ffed !important;
}
:deep(.row-iserp) {
  background-color: #e6ffed !important;
}
:deep(.row-iserp-updated) {
  background-color: #fff2a8 !important;
}
:deep(.row-iserp-price-null) {
  background-color: #f8d7da !important;
}
:deep(.ag-header-cell-label) {
  white-space: normal !important;
  line-height: 1.2;
}
:deep(.ag-header-cell) {
  height: auto !important;
}
</style>
