<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import type { ColDef } from 'ag-grid-community';
import type { RowData, TabConfig } from '@/v3/logic/calc-engine';
import DetailGridV3 from '@/v3/components/detail/DetailGridV3.vue';
import type { ResolvedGridOptions } from '@/v3/composables/meta-v3/grid-options';
import type { CellEditableRule, RowEditableRule } from '@/v3/composables/meta-v3/types';
import type { RowStateApi } from '@/v3/composables/meta-v3/useWorkingSetStore';

const props = defineProps<{
  tabs: TabConfig[];
  activeMasterId: number | null;
  activeMasterRowKey: string | null;
  detailCache: Map<string, Record<string, RowData[]>>;
  detailColumnsByTab: Record<string, ColDef[]>;
  detailRowEditableRulesByTab?: Record<string, RowEditableRule[]>;
  detailCellEditableRulesByTab?: Record<string, CellEditableRule[]>;
  detailRowClassByTab?: Record<string, ((params: any) => string | undefined) | undefined>;
  detailGridOptionsByTab?: Record<string, ResolvedGridOptions>;
  detailSumFieldsByTab?: Record<string, string[]>;
  cellClassRules: ColDef['cellClassRules'];
  rowStateApi: RowStateApi;
  defaultViewMode?: 'tab' | 'stack';
  viewMode?: 'tab' | 'stack';
  applyGridConfig?: (gridKey: string, api: any, columnApi: any, sourceColumnDefs?: ColDef[]) => void;
  onDetailCellValueChanged: (event: any, masterId: number, tabKey: string, masterRowKey?: string) => void;
  onDetailCellClicked: (event: any, masterId: number, tabKey: string) => void;
  onCellEditingStarted: () => void;
  onCellEditingStopped: () => void;
  loadDetailData: (masterId: number, masterRowKey?: string) => Promise<void>;
  registerDetailGridApi: (tabKey: string, api: any) => void;
  unregisterDetailGridApi?: (tabKey: string, api: any) => void;
  getDetailContextMenuItems: (masterId: number, masterRowKey: string, tabKey: string) => (params: any) => any[];
  refreshDetailRowHeight?: () => void;
}>();

const emit = defineEmits<{
  (e: 'update:activeTab', value: string): void;
}>();

const localViewMode = ref<'tab' | 'stack'>(props.defaultViewMode ?? 'tab');
const activeTab = ref<string>('');
const gridApis = ref<Record<string, any>>({});

const hasTabs = computed(() => Array.isArray(props.tabs) && props.tabs.length > 0);

const currentViewMode = computed<'tab' | 'stack'>(() => props.viewMode ?? localViewMode.value);

const activeTabConfig = computed(() => {
  if (!hasTabs.value) return null;
  return props.tabs.find(tab => tab.key === activeTab.value) || props.tabs[0];
});

watch(
  () => props.tabs,
  tabs => {
    if (!tabs || tabs.length === 0) {
      activeTab.value = '';
      return;
    }
    if (!activeTab.value || !tabs.some(tab => tab.key === activeTab.value)) {
      activeTab.value = tabs[0].key;
      emit('update:activeTab', activeTab.value);
    }
  },
  { immediate: true }
);

watch(
  () => props.activeMasterId,
  async masterId => {
    const masterRowKey = props.activeMasterRowKey;
    if (masterId == null || !masterRowKey) return;
    if (!props.detailCache.get(masterRowKey)) {
      await props.loadDetailData(masterId, masterRowKey);
    }
    updateGridRows(masterRowKey);
  },
  { immediate: true }
);

watch(activeTab, () => {
  emit('update:activeTab', activeTab.value);
  if (props.activeMasterRowKey == null) return;
  updateGridRows(props.activeMasterRowKey, activeTab.value);
  nextTick(() => refreshLayout());
});

watch(currentViewMode, async () => {
  await nextTick();
  refreshLayout();
});

function handleRegister(tabKey: string, api: any) {
  gridApis.value[tabKey] = api;
  props.registerDetailGridApi(tabKey, api);
  if (props.activeMasterRowKey != null) {
    const rows = props.detailCache.get(props.activeMasterRowKey)?.[tabKey] || [];
    api?.setGridOption?.('rowData', rows);
  }
}

function handleUnregister(tabKey: string, api: any) {
  if (gridApis.value[tabKey] === api) {
    delete gridApis.value[tabKey];
  }
  props.unregisterDetailGridApi?.(tabKey, api);
}

function resolveRows(tabKey: string): RowData[] {
  if (props.activeMasterRowKey == null) return [];
  return props.detailCache.get(props.activeMasterRowKey)?.[tabKey] || [];
}

function updateGridRows(masterRowKey: string, tabKey?: string) {
  const cached = props.detailCache.get(masterRowKey);
  if (!cached) return;
  if (tabKey) {
    gridApis.value[tabKey]?.setGridOption('rowData', cached[tabKey] || []);
    return;
  }
  Object.entries(cached).forEach(([key, rows]) => {
    gridApis.value[key]?.setGridOption('rowData', rows || []);
  });
}

function getDetailContextMenuItemsFor(tabKey: string) {
  if (props.activeMasterId == null || props.activeMasterRowKey == null) return () => [];
  return props.getDetailContextMenuItems(props.activeMasterId, props.activeMasterRowKey, tabKey);
}

function refreshLayout() {
  const apis = Object.values(gridApis.value);
  if (apis.length === 0) return;
  apis.forEach(api => {
    api?.doLayout?.();
    api?.sizeColumnsToFit?.();
  });
}
</script>

<template>
  <div class="detail-panel-inner" :class="{ 'tab-mode': currentViewMode === 'tab' }">
    <div v-if="hasTabs && currentViewMode === 'tab'" class="detail-toolbar">
      <div class="detail-tabs">
        <template v-if="currentViewMode === 'tab'">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: tab.key === activeTab }"
            @click="activeTab = tab.key"
          >
            {{ tab.title }}
          </button>
        </template>
      </div>
    </div>

    <div class="detail-body">
      <div v-if="!activeMasterId" class="detail-empty">请选择主表记录</div>
      <div v-else-if="!hasTabs" class="detail-empty">暂无明细配置</div>
      <div v-else class="detail-content">
        <DetailGridV3
          v-if="currentViewMode === 'tab' && activeTabConfig"
          :key="activeTabConfig.key"
          :tab="activeTabConfig"
          :rows="resolveRows(activeTabConfig.key)"
          :columns="detailColumnsByTab[activeTabConfig.key] || []"
          :row-editable-rules="detailRowEditableRulesByTab?.[activeTabConfig.key] || []"
          :cell-editable-rules="detailCellEditableRulesByTab?.[activeTabConfig.key] || []"
          :row-class-getter="detailRowClassByTab?.[activeTabConfig.key]"
          :grid-options="detailGridOptionsByTab?.[activeTabConfig.key]"
          :cell-class-rules="cellClassRules"
          :row-state-api="rowStateApi"
          :context-menu-items="getDetailContextMenuItemsFor(activeTabConfig.key)"
          :register-detail-grid-api="handleRegister"
          :unregister-detail-grid-api="handleUnregister"
          :apply-grid-config="applyGridConfig"
          :on-cell-value-changed="
            event =>
              onDetailCellValueChanged(event, activeMasterId!, activeTabConfig!.key, activeMasterRowKey || undefined)
          "
          :on-cell-clicked="event => onDetailCellClicked(event, activeMasterId!, activeTabConfig!.key)"
          :on-cell-editing-started="onCellEditingStarted"
          :on-cell-editing-stopped="onCellEditingStopped"
          :sum-fields="detailSumFieldsByTab?.[activeTabConfig.key]"
        />

        <div v-else class="detail-stack">
          <DetailGridV3
            v-for="tab in tabs"
            :key="tab.key"
            :tab="tab"
            :rows="resolveRows(tab.key)"
            :columns="detailColumnsByTab[tab.key] || []"
            :row-editable-rules="detailRowEditableRulesByTab?.[tab.key] || []"
            :cell-editable-rules="detailCellEditableRulesByTab?.[tab.key] || []"
            :row-class-getter="detailRowClassByTab?.[tab.key]"
            :grid-options="detailGridOptionsByTab?.[tab.key]"
            :cell-class-rules="cellClassRules"
            :row-state-api="rowStateApi"
            :context-menu-items="getDetailContextMenuItemsFor(tab.key)"
            :show-title="true"
            :tab-count="tabs.length"
            :refresh-detail-row-height="refreshDetailRowHeight"
            :register-detail-grid-api="handleRegister"
            :unregister-detail-grid-api="handleUnregister"
            :apply-grid-config="applyGridConfig"
            :on-cell-value-changed="
              event => onDetailCellValueChanged(event, activeMasterId!, tab.key, activeMasterRowKey || undefined)
            "
            :on-cell-clicked="event => onDetailCellClicked(event, activeMasterId!, tab.key)"
            :on-cell-editing-started="onCellEditingStarted"
            :on-cell-editing-stopped="onCellEditingStopped"
            :sum-fields="detailSumFieldsByTab?.[tab.key]"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.detail-panel-inner {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  height: 100%;
  --detail-title-height: 24px;
}

.detail-panel-inner.tab-mode {
  gap: 4px;
}

.detail-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: var(--detail-title-height);
  padding: 0 12px;
  border-bottom: 1px solid #eef2f7;
}

.detail-tabs {
  display: flex;
  gap: 12px;
  flex: 1;
  align-items: center;
  height: 100%;
}

.tab-btn {
  border: none;
  background: transparent;
  height: 100%;
  padding: 0 2px;
  line-height: var(--detail-title-height);
  font-size: 13px;
  color: #64748b;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn.active {
  color: #2563eb;
  border-bottom-color: #2563eb;
  font-weight: 600;
}

.detail-body {
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 0;
}

.detail-content {
  width: 100%;
  height: 100%;
}

/* Tab 模式下单个 grid */
.detail-panel-inner.tab-mode :deep(.detail-grid-wrap) {
  height: 300px;
}

/* 堆叠模式：多个子表垂直排列 */
.detail-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 100%;
  height: 100%;
}

.detail-empty {
  height: 100px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 13px;
}
</style>
