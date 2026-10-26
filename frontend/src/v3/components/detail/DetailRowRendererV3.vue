<script setup lang="ts">
import { computed, unref } from 'vue';
import DetailPanelV3 from '@/v3/components/detail/DetailPanelV3.vue';

const props = defineProps<{ params: any }>();

const panelContext = computed(() => props.params?.context?.detailPanelContext || {});

const masterId = computed<number | null>(() => {
  const raw = props.params?.data?.id;
  if (raw == null) return null;
  const value = Number(raw);
  return Number.isNaN(value) ? null : value;
});
const masterRowKey = computed<string | null>(() => {
  const raw = props.params?.data?._rowKey;
  return raw ? String(raw) : null;
});

const tabs = computed(() => unref(panelContext.value.tabs) || []);
const detailCache = computed(() => panelContext.value.detailCache || new Map());
const detailColumnsByTab = computed(() => unref(panelContext.value.detailColumnsByTab) || {});
const detailRowEditableRulesByTab = computed(() => unref(panelContext.value.detailRowEditableRulesByTab) || {});
const detailCellEditableRulesByTab = computed(() => unref(panelContext.value.detailCellEditableRulesByTab) || {});
const detailRowClassByTab = computed(() => unref(panelContext.value.detailRowClassByTab) || {});
const detailGridOptionsByTab = computed(() => unref(panelContext.value.detailGridOptionsByTab) || {});
const detailSumFieldsByTab = computed(() => unref(panelContext.value.detailSumFieldsByTab) || {});
const rowStateApi = computed(() => panelContext.value.rowStateApi);
const cellClassRules = computed(() => panelContext.value.cellClassRules);
const noop = () => {};
const noopLoad = async () => {};
const noopMenu = () => () => [];

const applyGridConfig = computed(() => panelContext.value.applyGridConfig);
const onDetailCellValueChanged = computed(() => panelContext.value.onDetailCellValueChanged || noop);
const onDetailCellClicked = computed(() => panelContext.value.onDetailCellClicked || noop);
const onCellEditingStarted = computed(() => panelContext.value.onCellEditingStarted || noop);
const onCellEditingStopped = computed(() => panelContext.value.onCellEditingStopped || noop);
const loadDetailData = computed(() => panelContext.value.loadDetailData || noopLoad);
const registerDetailGridApi = computed(() => panelContext.value.registerDetailGridApi || noop);
const unregisterDetailGridApi = computed(() => panelContext.value.unregisterDetailGridApi || noop);
const getDetailContextMenuItems = computed(() => panelContext.value.getDetailContextMenuItems || noopMenu);
const refreshDetailRowHeight = computed(() => panelContext.value.refreshDetailRowHeight || noop);
const defaultViewMode = computed(() => panelContext.value.defaultViewMode || 'stack');
const detailViewMode = computed(() => unref(panelContext.value.detailViewMode));
const onActiveTabChange = computed(() => panelContext.value.onActiveTabChange || noop);

// 鼠标进入子表区域时，禁用主表滚动
function onMouseEnter() {
  const masterGrid = document.querySelector('.master-grid');
  if (masterGrid) {
    const viewport = masterGrid.querySelector('.ag-body-viewport') as HTMLElement;
    if (viewport) {
      viewport.style.overflowY = 'hidden';
    }
  }
}

// 鼠标离开子表区域时，恢复主表滚动
function onMouseLeave() {
  const masterGrid = document.querySelector('.master-grid');
  if (masterGrid) {
    const viewport = masterGrid.querySelector('.ag-body-viewport') as HTMLElement;
    if (viewport) {
      viewport.style.overflowY = '';
    }
  }
}

function handleActiveTabChange(tabKey: string) {
  onActiveTabChange.value?.(tabKey, masterId.value, masterRowKey.value);
}
</script>

<template>
  <div class="detail-row-renderer" @mouseenter="onMouseEnter" @mouseleave="onMouseLeave">
    <DetailPanelV3
      :tabs="tabs"
      :active-master-id="masterId"
      :active-master-row-key="masterRowKey"
      :detail-cache="detailCache"
      :detail-columns-by-tab="detailColumnsByTab"
      :detail-row-editable-rules-by-tab="detailRowEditableRulesByTab"
      :detail-cell-editable-rules-by-tab="detailCellEditableRulesByTab"
      :detail-row-class-by-tab="detailRowClassByTab"
      :detail-grid-options-by-tab="detailGridOptionsByTab"
      :detail-sum-fields-by-tab="detailSumFieldsByTab"
      :row-state-api="rowStateApi"
      :cell-class-rules="cellClassRules"
      :apply-grid-config="applyGridConfig"
      :on-detail-cell-value-changed="onDetailCellValueChanged"
      :on-detail-cell-clicked="onDetailCellClicked"
      :on-cell-editing-started="onCellEditingStarted"
      :on-cell-editing-stopped="onCellEditingStopped"
      :load-detail-data="loadDetailData"
      :register-detail-grid-api="registerDetailGridApi"
      :unregister-detail-grid-api="unregisterDetailGridApi"
      :get-detail-context-menu-items="getDetailContextMenuItems"
      :refresh-detail-row-height="refreshDetailRowHeight"
      :default-view-mode="defaultViewMode"
      :view-mode="detailViewMode"
      @update:active-tab="handleActiveTabChange"
    />
  </div>
</template>

<style scoped>
.detail-row-renderer {
  height: 100%;
  overflow: auto;
  padding: 8px 12px 12px 12px;
  background: #f8fafc;
  box-sizing: border-box;
}
</style>
