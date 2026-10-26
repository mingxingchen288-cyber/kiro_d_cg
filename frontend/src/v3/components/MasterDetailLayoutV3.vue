<script setup lang="ts">
import { computed, nextTick, ref, unref, watch } from 'vue';
import { NButton, NDropdown, NSpace, NSplit, useDialog } from 'naive-ui';
import { AgGridVue } from 'ag-grid-vue3';
import { useThemeStore } from '@/store/modules/theme';
import DetailRowRendererV3 from '@/v3/components/detail/DetailRowRendererV3.vue';
import DetailPanelV3 from '@/v3/components/detail/DetailPanelV3.vue';
import ApprovalActionGroup from '@/v3/components/approval/ApprovalActionGroup.vue';
import { useMasterGridBindings } from '@/v3/composables/meta-v3/useMasterGridBindings';
import { useGridContextMenu } from '@/v3/composables/meta-v3/useGridContextMenu';
import { showErrorDialog } from '@/v3/utils/errorDialog';
import { handleToolbarAction } from '@/v3/composables/meta-v3/useToolbarAction';
import { ensureRowKey } from '@/v3/logic/calc-engine';
import { buildRowClassCallback, buildRowEditableCallback } from '@/v3/composables/meta-v3/usePageRules';

const props = defineProps<{ runtime: any }>();

const dialog = useDialog();

const themeStore = useThemeStore();
const runtime = props.runtime;
const meta = runtime.meta;
const workingSet = runtime.workingSet;
const masterGridApi = runtime.masterGridApi;
const rowStateApi = runtime.rowStateApi;
const lookup = runtime.lookup;
const actions = runtime.actions;
const mutations = runtime.mutations;
const gridConfigApi = runtime.gridConfig;

const {
  masterColumnDefs,
  detailColumnsByTab,
  pageConfig,
  masterRowClassGetter,
  detailRowClassGetterByTab,
  detailRowClassRulesByTab,
  detailRowEditableRulesByTab,
  detailCellEditableRulesByTab,
  masterGridOptions,
  detailGridOptionsByTab,
  detailSumFieldsByTab,
  masterContextMenu,
  detailContextMenuByTab,
  masterRowEditableRules,
  masterRowClassRules,
  masterToolbar,
  detailToolbarByTab
} = meta;
const detailGridApisByTab = runtime.detailGridApisByTab;
const activeMasterRowKey = runtime.activeMasterRowKey;

const { save, executeAction, customExportConfigs, executeCustomExport } = actions;
const { applyGridConfig, saveGridConfig } = gridConfigApi;
const { onDetailCellClicked, onMasterCellClicked: handleLookupMasterCellClick } = lookup;

const { detailCache, loadDetailData, createServerSideDataSource, getMasterRowById } = workingSet;
const routeMasterId = workingSet.routeMasterId;
const {
  addMasterRow,
  deleteMasterRow,
  copyMasterRow,
  addDetailRow,
  deleteDetailRow,
  copyDetailRow,
  onMasterCellValueChanged: applyMasterCellValueChanged,
  onDetailCellValueChanged: applyDetailCellValueChanged
} = mutations;

const editingState = ref(false);

const canAddRow = computed(() => runtime.permissions?.hasButton?.('addRow') === true);
const canDeleteRow = computed(() => runtime.permissions?.hasButton?.('deleteRow') === true);
const canSave = computed(() => runtime.permissions?.hasButton?.('save') === true);

// 从表内置按钮下拉选项
const detailAddOptions = computed(() =>
  detailTabs.value.map((tab: { title?: string; key: string }) => ({ label: `新增${tab.title || tab.key}`, key: tab.key }))
);
const detailDeleteOptions = computed(() =>
  detailTabs.value.map((tab: { title?: string; key: string }) => ({ label: `删除${tab.title || tab.key}`, key: tab.key }))
);

function handleDetailAdd(tabKey: string) {
  const { masterId, masterRowKey } = resolveActiveMasterContext();
  if (masterId == null) {
    window.$message?.warning('请先选择主表记录');
    return;
  }
  addDetailRow(masterId, tabKey, masterRowKey || undefined);
}

function handleDetailDelete(tabKey: string) {
  const { masterId, masterRowKey } = resolveActiveMasterContext();
  if (masterId == null) {
    window.$message?.warning('请先选择主表记录');
    return;
  }
  const api = detailGridApisByTab.value[tabKey];
  const selectedRows = api?.getSelectedRows?.() || [];
  if (selectedRows.length === 0) {
    window.$message?.warning('请先选择要删除的明细行');
    return;
  }
  selectedRows.forEach((row: any) => deleteDetailRow(masterId, tabKey, row, masterRowKey || undefined));
}

// 工具栏：合并主表 + 从表 toolbar 按钮
// 多个 tab 同名 action 合并为下拉按钮
type MergedToolbarItem = {
  key: string;
  action?: string;
  label?: string;
  type?: 'default' | 'primary' | 'info' | 'success' | 'warning' | 'error' | 'tertiary';
  disabled?: boolean;
  confirm?: string;
  requiresRow?: boolean;
  tabKey?: string;
  children?: { label: string; key: string }[];
};

const mergedToolbarItems = computed<MergedToolbarItem[]>(() => {
  const items: MergedToolbarItem[] = [];

  // 1. 主表 toolbar 按钮
  const masterItems = masterToolbar?.value?.items || [];
  for (const item of masterItems) {
    if (item.visible === false) continue;
    items.push({ ...item, key: `master_${item.action}` });
  }

  // 2. 从表 toolbar 按钮
  const tabs = pageConfig.value?.tabs || [];
  const detailToolbars = detailToolbarByTab?.value || {};
  const isTabMode = detailViewMode.value === 'tab';

  if (isTabMode) {
    // Tab 模式：直接显示当前激活 tab 的按钮，不需要下拉
    const currentTab = activeDetailTab.value || tabs[0]?.key;
    const toolbar = currentTab ? detailToolbars[currentTab] : null;
    if (toolbar?.items) {
      for (const btn of toolbar.items) {
        if (btn.visible === false || !btn.action) continue;
        items.push({ ...btn, key: `detail_${currentTab}_${btn.action}`, tabKey: currentTab });
      }
    }
  } else {
    // 堆叠模式：按 action 分组合并为下拉按钮
    const actionGroup = new Map<
      string,
      { label: string; tabKey: string; tabTitle: string; alias?: string; item: any }[]
    >();

    for (const tab of tabs) {
      const toolbar = detailToolbars[tab.key];
      if (!toolbar?.items) continue;
      for (const btn of toolbar.items) {
        if (btn.visible === false || !btn.action) continue;
        const group = actionGroup.get(btn.action) || [];
        group.push({
          label: btn.toolbarAlias || `${btn.label}(${tab.title})`,
          tabKey: tab.key,
          tabTitle: tab.title,
          alias: btn.toolbarAlias,
          item: btn
        });
        actionGroup.set(btn.action, group);
      }
    }

    for (const [action, group] of actionGroup) {
      if (group.length === 1) {
        const { item, tabKey, label } = group[0];
        items.push({ ...item, key: `detail_${tabKey}_${action}`, label, tabKey });
      } else {
        const baseLabel = group[0].item.label || action;
        items.push({
          key: `detail_merged_${action}`,
          action,
          label: baseLabel,
          type: group[0].item.type,
          children: group.map(g => ({
            label: g.label,
            key: `detail_${g.tabKey}_${action}`
          }))
        });
      }
    }
  }

  return items;
});

function handleDropdownSelect(key: string, parentItem: MergedToolbarItem) {
  // key 格式: detail_{tabKey}_{action}
  const match = key.match(/^detail_(.+?)_(.+)$/);
  if (!match) return;
  const [, tabKey, action] = match;
  // 找到对应的 tab 和 action，执行操作
  const { masterId, masterRowKey } = resolveActiveMasterContext();
  if (masterId == null) {
    window.$message?.warning('请先选择主表记录');
    return;
  }
  switch (action) {
    case 'addRow':
      addDetailRow(masterId, tabKey, masterRowKey || undefined);
      break;
    case 'copyRow': {
      const api = detailGridApisByTab.value[tabKey];
      const selectedRows = api?.getSelectedRows?.() || [];
      if (selectedRows.length === 0) {
        window.$message?.warning('请先选择要复制的行');
        return;
      }
      copyDetailRow(masterId, tabKey, selectedRows[0], masterRowKey || undefined);
      break;
    }
    case 'deleteRow': {
      const api = detailGridApisByTab.value[tabKey];
      const selectedRows = api?.getSelectedRows?.() || [];
      if (selectedRows.length === 0) {
        window.$message?.warning('请先选择要删除的行');
        return;
      }
      selectedRows.forEach((row: any) => deleteDetailRow(masterId, tabKey, row, masterRowKey || undefined));
      break;
    }
    default:
      // 自定义 action，走 executeAction
      executeAction(action, { data: {}, selectedRow: null });
      break;
  }
}

async function handleToolbarClick(item: any) {
  if (item.tabKey) {
    // 从表按钮，直接执行对应 tab 的操作
    handleDropdownSelect(`detail_${item.tabKey}_${item.action}`, item);
    return;
  }

  // 主表内置 action 处理
  const action = item.action;
  const getSelectedRow = () => {
    const api = masterGridApi?.value;
    const selectedRows = api?.getSelectedRows?.() || [];
    return selectedRows[0] || null;
  };

  switch (action) {
    case 'addRow':
      addMasterRow();
      return;
    case 'copyRow': {
      const row = getSelectedRow();
      if (!row) {
        window.$message?.warning('请先选择一行');
        return;
      }
      copyMasterRow(row);
      return;
    }
    case 'deleteRow': {
      const api = masterGridApi?.value;
      const selectedRows = api?.getSelectedRows?.() || [];
      if (selectedRows.length === 0) {
        window.$message?.warning('请先选择要删除的行');
        return;
      }
      selectedRows.forEach((row: any) => deleteMasterRow(row));
      return;
    }
    case 'save':
      save();
      return;
    case 'saveGridConfig': {
      const api = masterGridApi?.value;
      if (api) saveGridConfig(masterGridKey.value, api, null);
      return;
    }
    default:
      // 自定义后端 action
      await handleToolbarAction(item, {
        getSelectedRow,
        executeAction,
        dialog
      });
  }
}

function getSelectedMasterRow() {
  const api = masterGridApi?.value;
  const selectedRows = api?.getSelectedRows?.() || [];
  return selectedRows[0] || null;
}

function deleteSelectedMasterRows() {
  const api = masterGridApi?.value;
  const selectedRows = api?.getSelectedRows?.() || [];
  if (selectedRows.length === 0) {
    window.$message?.warning('请先选择要删除的行');
    return;
  }
  selectedRows.forEach((row: any) => deleteMasterRow(row));
}

// 使用全局主题设置的detailViewMode
const detailViewMode = computed(() => themeStore.detailViewMode);

// 使用全局主题设置的masterDetailMode
const masterDetailMode = computed(() => themeStore.masterDetailMode);

const detailFeatureEnabled = computed(() => runtime.features?.detailTabs !== false);
const hasDetailTabs = computed(() => detailFeatureEnabled.value && (pageConfig.value?.tabs?.length || 0) > 0);
const detailTabs = computed(() => pageConfig.value?.tabs || []);
const detailLayoutMode = computed(() => meta.detailLayoutMode?.value ?? meta.detailLayoutMode ?? 'nested');
const splitConfig = computed(() => {
  const config = meta.detailSplitConfig?.value ?? meta.detailSplitConfig ?? {};
  return {
    defaultSize: config?.defaultSize ?? 0.5,
    min: config?.min ?? 0.2,
    max: config?.max ?? 0.8
  };
});
// 使用全局主题设置判断是否为分屏模式
const isSplitMode = computed(() => masterDetailMode.value === 'split');

// 合并明细表行样式：列元数据 rulesConfig + T_COST_PAGE_RULE ROW_CLASS
const mergedDetailRowClassByTab = computed(() => {
  const result: Record<string, ((params: any) => string | undefined) | undefined> = {};
  const tabs = pageConfig.value?.tabs || [];
  for (const tab of tabs) {
    const metaGetter = detailRowClassGetterByTab?.value?.[tab.key];
    const rules = detailRowClassRulesByTab?.value?.[tab.key] || [];
    const ruleGetter = buildRowClassCallback(rules);

    if (!metaGetter && !ruleGetter) {
      result[tab.key] = undefined;
    } else {
      result[tab.key] = (params: any) => {
        const classes: string[] = [];
        const metaClass = metaGetter?.(params);
        if (metaClass) classes.push(metaClass);
        const ruleClass = ruleGetter?.(params);
        if (ruleClass) classes.push(ruleClass);
        return classes.length > 0 ? classes.join(' ') : undefined;
      };
    }
  }
  return result;
});

// 从表行编辑权限检查（用于控制删除）
const detailRowEditableByTab = computed(() => {
  const result: Record<string, ((row: any) => boolean) | undefined> = {};
  const tabs = pageConfig.value?.tabs || [];
  for (const tab of tabs) {
    const rules = detailRowEditableRulesByTab?.value?.[tab.key] || [];
    const callback = buildRowEditableCallback(rules);
    result[tab.key] = callback ? (row: any) => callback({ data: row, context: { rowStateApi } }) : undefined;
  }
  return result;
});
const activeMasterId = ref<number | null>(null);
const activeDetailTab = ref<string>('');
let lastFocusedRouteMasterId: number | null = null;

const masterGridOptionsValue = computed(() => masterGridOptions?.value || null);

function normalizeMasterId(value: unknown): number | null {
  if (value == null || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function setActiveMasterContext(row: any | null) {
  const nextId = normalizeMasterId(row?.id);
  const nextRowKey = row ? ensureRowKey(row) : null;
  activeMasterId.value = nextId;
  activeMasterRowKey.value = nextRowKey ? String(nextRowKey) : null;
}

function getExpandedMasterNode(api: any): any | null {
  let expandedNode: any = null;
  api?.forEachNode?.((node: any) => {
    if (node?.master && node.expanded) {
      expandedNode = node;
    }
  });
  return expandedNode;
}

function resolveActiveMasterContext() {
  if (activeMasterId.value != null) {
    return {
      masterId: activeMasterId.value,
      masterRowKey: activeMasterRowKey.value
    };
  }

  if (!isSplitMode.value) {
    const expandedNode = getExpandedMasterNode(masterGridApi.value);
    if (expandedNode?.data) {
      setActiveMasterContext(expandedNode.data);
      return {
        masterId: activeMasterId.value,
        masterRowKey: activeMasterRowKey.value
      };
    }
  }

  return {
    masterId: null,
    masterRowKey: null
  };
}

function findMasterNodeById(api: any, targetId: number) {
  let matchedNode: any = null;
  api?.forEachNode?.((node: any) => {
    if (!matchedNode && normalizeMasterId(node?.data?.id) === targetId) {
      matchedNode = node;
    }
  });
  return matchedNode;
}

async function focusRouteMasterRow(api: any = masterGridApi.value) {
  const targetId = normalizeMasterId(routeMasterId?.value);
  if (targetId == null || !api || lastFocusedRouteMasterId === targetId) return;

  const node = findMasterNodeById(api, targetId);
  if (!node?.data) return;

  lastFocusedRouteMasterId = targetId;
  node.setSelected?.(true, true);
  setActiveMasterContext(node.data);
  if (node.rowIndex != null) {
    api.ensureIndexVisible?.(node.rowIndex, 'middle');
  }

  if (!hasDetailTabs.value) {
    workingSet.setRouteMasterId?.(null);
    return;
  }
  const masterRowKey = String(ensureRowKey(node.data));
  if (isSplitMode.value) {
    await loadDetailData(targetId, masterRowKey);
  } else if (!node.expanded) {
    node.setExpanded?.(true);
  } else if (!detailCache.get(masterRowKey)) {
    await loadDetailData(targetId, masterRowKey);
    api.resetRowHeights?.();
  }

  // focusId 只用于通知跳转后的首次定位。定位完成后立即清掉隐藏条件，
  // 保持当前显示不刷新，后续用户查询/清空查询时不再被原单据锁住。
  workingSet.setRouteMasterId?.(null);
}

// 确保 dataSource 只创建一次，避免因响应式重新计算导致 AG Grid 重置
let cachedDataSource: any = null;
function getDataSource() {
  if (!cachedDataSource) {
    cachedDataSource = createServerSideDataSource({
      pageSize: masterGridOptionsValue.value?.cacheBlockSize
    });
  }
  return cachedDataSource;
}

const {
  cellClassRules,
  defaultColDef,
  gridOptions: masterGridRuntimeOptions,
  autoSizeStrategy,
  rowSelection,
  rowHeight,
  headerHeight,
  getRowId: getMasterRowId,
  getRowClass,
  getRowStyle,
  getContextMenuItems: getMasterContextMenuItems,
  onGridReady: onMasterGridReady,
  onCellEditingStarted,
  onCellEditingStopped,
  onCellValueChanged: onMasterCellValueChanged,
  onCellClicked: onMasterCellClicked,
  onFilterChanged,
  onSelectionChanged
} = useMasterGridBindings({
  deps: {
    masterGridApi: runtime.masterGridApi,
    masterGridKey: meta.masterGridKey,
    masterCellEditableRules: meta.masterCellEditableRules,
    masterRowEditableRules,
    masterRowClassRules,
    masterSumFields: meta.masterSumFields,
    addMasterRow,
    deleteMasterRow,
    copyMasterRow,
    addDetailRow,
    deleteDetailRow,
    copyDetailRow,
    rowStateApi,
    save,
    saveGridConfig,
    customExportConfigs,
    executeCustomExport,
    executeAction,
    onMasterCellValueChanged: applyMasterCellValueChanged,
    onMasterCellClicked: handleLookupMasterCellClick
  },
  isUserEditing: editingState,
  metaRowClassGetter: masterRowClassGetter?.value,
  gridOptions: masterGridOptionsValue.value,
  columnDefs: masterColumnDefs,
  contextMenuConfig: masterContextMenu,
  dataSource: getDataSource(),
  onSelectionChanged: async rows => {
    const selected = rows?.[0];
    if (selected) {
      setActiveMasterContext(selected);
      return;
    }
    if (isSplitMode.value) {
      setActiveMasterContext(null);
    }
    // loadDetailData 由 DetailPanelV3 的 watch(activeMasterId) 统一触发，此处不再重复调用
  }
});

const masterGridKey = computed(() => {
  const key = meta.masterGridKey?.value ?? meta.masterGridKey;
  return key && String(key).trim().length > 0 ? key : 'masterGrid';
});

const { getDetailContextMenuItems } = useGridContextMenu({
  addMasterRow,
  deleteMasterRow,
  copyMasterRow,
  addDetailRow,
  deleteDetailRow,
  copyDetailRow,
  save,
  saveGridConfig,
  detailMenuByTab: detailContextMenuByTab,
  isDetailRowEditableByTab: detailRowEditableByTab,
  getActiveMaster: () => ({
    id: activeMasterId.value,
    rowKey: activeMasterRowKey.value
  }),
  notifyError: (msg: string) => showErrorDialog(msg)
});

function handleMasterGridReady(event: any) {
  onMasterGridReady(event);
  event.api?.addEventListener?.('modelUpdated', () => {
    focusRouteMasterRow(event.api);
  });
  applyGridConfig(masterGridKey.value, event.api, event.columnApi, unref(masterColumnDefs) || []);
  nextTick(() => focusRouteMasterRow(event.api));
}

// 刷新detail行高度
function refreshDetailRowHeight() {
  masterGridApi.value?.resetRowHeights();
}

// 切换 tab/堆叠 模式时重算展开行高度
watch(detailViewMode, () => {
  nextTick(() => masterGridApi.value?.resetRowHeights());
});

watch(
  () => routeMasterId?.value ?? null,
  () => {
    lastFocusedRouteMasterId = null;
    nextTick(() => focusRouteMasterRow(masterGridApi.value));
  }
);

function registerDetailGridApi(tabKey: string, api: any) {
  detailGridApisByTab.value[tabKey] = api;
}

function unregisterDetailGridApi(tabKey: string, api: any) {
  if (detailGridApisByTab.value[tabKey] === api) {
    delete detailGridApisByTab.value[tabKey];
  }
}

const gridContext = {
  rowStateApi,
  detailPanelContext: {
    tabs: detailTabs,
    detailCache,
    detailColumnsByTab,
    detailRowEditableRulesByTab,
    detailCellEditableRulesByTab,
    detailRowClassByTab: mergedDetailRowClassByTab,
    detailGridOptionsByTab,
    detailSumFieldsByTab,
    rowStateApi,
    cellClassRules,
    applyGridConfig,
    onDetailCellValueChanged: applyDetailCellValueChanged,
    onDetailCellClicked,
    onCellEditingStarted,
    onCellEditingStopped,
    loadDetailData,
    registerDetailGridApi,
    unregisterDetailGridApi,
    getDetailContextMenuItems,
    refreshDetailRowHeight,
    defaultViewMode: 'stack',
    detailViewMode,
    onActiveTabChange: (tabKey: string, masterId?: number | null, masterRowKey?: string | null) => {
      activeDetailTab.value = tabKey;
      if (masterId != null) {
        activeMasterId.value = masterId;
        activeMasterRowKey.value = masterRowKey ?? null;
      }
    }
  }
};

function getRowHeight(params: any): number | undefined {
  if (!params.node?.detail) return undefined;

  const masterRowKey = params.node?.data?._rowKey ? String(params.node?.data?._rowKey) : null;
  const tabs = detailTabs.value || [];
  const tabCount = tabs.length || 1;
  const rowHeight = 28;
  const headerHeight = 28;
  const gap = 16;
  const padding = 80;
  const minRows = 2;
  const isTabMode = detailViewMode.value === 'tab';

  const cached = masterRowKey ? detailCache.get(masterRowKey) : undefined;

  if (isTabMode) {
    // tab 模式：只显示一个从表，高度按最大的 tab 算
    const tabBarHeight = 32;
    let maxTabHeight = 0;
    for (const tab of tabs) {
      const rows = cached?.[tab.key] || [];
      const contentHeight = headerHeight + Math.max(rows.length, minRows) * rowHeight + 20;
      if (contentHeight > maxTabHeight) maxTabHeight = contentHeight;
    }
    // 限制最大高度
    const maxContainerHeight = window.innerHeight - 100;
    const totalHeight = tabBarHeight + maxTabHeight + 40;
    return Math.min(totalHeight, maxContainerHeight);
  }

  // 堆叠模式：所有子表累加
  const availableHeight = window.innerHeight - 100 - padding - gap * (tabCount - 1);
  const maxGridHeight = Math.floor(availableHeight / tabCount);
  const minGridHeight = headerHeight + rowHeight * minRows;

  let totalHeight = padding;
  for (let i = 0; i < tabs.length; i++) {
    const tabKey = tabs[i].key;
    const rows = cached?.[tabKey] || [];
    const contentHeight = headerHeight + Math.max(rows.length, minRows) * rowHeight + 20;
    const gridHeight = Math.max(minGridHeight, Math.min(contentHeight, maxGridHeight));
    totalHeight += gridHeight;
    if (i < tabs.length - 1) totalHeight += gap;
  }

  const maxContainerHeight = window.innerHeight - 100;
  return Math.min(totalHeight, maxContainerHeight);
}

// 检测指定主表行及其子表是否有未保存的修改
function hasUnsavedChanges(masterId: number): boolean {
  // 检查主表行
  const masterRow = getMasterRowById(masterId);
  if (rowStateApi?.hasRowChanges?.(masterRow)) {
    return true;
  }

  // 检查子表
  const masterRowKey = masterRow ? ensureRowKey(masterRow) : null;
  const cached = masterRowKey ? detailCache.get(masterRowKey) : undefined;
  if (cached) {
    for (const rows of Object.values(cached)) {
      for (const row of rows as any[]) {
        if (rowStateApi?.hasRowChanges?.(row)) {
          return true;
        }
      }
    }
  }

  return false;
}

function onDetailRowOpened(event: any) {
  if (isSplitMode.value) return;
  if (!event?.node?.master) return;

  const masterId = normalizeMasterId(event.node?.data?.id);
  const api = event.api;
  const currentNode = event.node;

  // 如果是收起操作，同步清理/回写当前主表上下文
  if (!currentNode.expanded) {
    if (activeMasterId.value === masterId) {
      setActiveMasterContext(getExpandedMasterNode(api)?.data ?? null);
    }
    return;
  }

  // 检查是否有其他展开的行
  let expandedNode: any = null;
  api?.forEachNode?.((node: any) => {
    if (node?.master && node !== currentNode && node.expanded) {
      expandedNode = node;
    }
  });

  if (expandedNode) {
    const expandedMasterId = expandedNode.data?.id;

    // 先收起当前行（阻止本次展开）
    currentNode.setExpanded(false);

    // 检查原展开行是否有未保存的修改
    if (hasUnsavedChanges(expandedMasterId)) {
      dialog.warning({
        title: '提示',
        content: '当前数据有未保存的修改，是否保存？',
        positiveText: '保存',
        negativeText: '稍后保存',
        onPositiveClick: async () => {
          await save();
          // 保存后收起旧行，展开新行
          expandedNode.setExpanded(false);
          setTimeout(() => {
            currentNode.setExpanded(true);
            setActiveMasterContext(currentNode.data);
          }, 50);
        },
        onNegativeClick: () => {
          // 不保存，直接收起旧行，展开新行
          expandedNode.setExpanded(false);
          setTimeout(() => {
            currentNode.setExpanded(true);
            setActiveMasterContext(currentNode.data);
          }, 50);
        }
      });
      return;
    }

    // 没有修改，直接收起旧行，展开新行
    expandedNode.setExpanded(false);
    setTimeout(() => {
      currentNode.setExpanded(true);
      setActiveMasterContext(currentNode.data);
    }, 50);
    return;
  }

  setActiveMasterContext(currentNode.data);

  // 将当前行滚动到顶部
  const rowIndex = currentNode.rowIndex;
  if (rowIndex != null) {
    api?.ensureIndexVisible(rowIndex, 'top');
  }

  // 加载数据，完成后刷新行高
  const masterRowKey = currentNode?.data ? String(ensureRowKey(currentNode.data)) : null;
  if (masterId != null && masterRowKey && !detailCache.get(masterRowKey)) {
    loadDetailData(masterId, masterRowKey).then(() => {
      // 数据加载完成后重新计算行高
      api?.resetRowHeights();
    });
  }
}

</script>

<template>
  <div class="master-detail-layout-v3">
    <!-- 工具栏 -->
    <div class="toolbar-container">
      <NSpace>
        <NButton v-if="canAddRow" type="primary" size="small" @click="addMasterRow">新增</NButton>
        <NButton v-if="canDeleteRow" type="error" size="small" @click="deleteSelectedMasterRows">删除</NButton>
        <NButton v-if="canSave" size="small" @click="save">保存</NButton>

        <!-- 从表内置按钮：明细新增/删除（有从表时自动显示） -->
        <template v-if="hasDetailTabs">
          <!-- 只有一个从表：直接显示按钮 -->
          <template v-if="detailTabs.length === 1">
            <NButton size="small" @click="handleDetailAdd(detailTabs[0].key)">明细新增</NButton>
            <NButton size="small" type="error" @click="handleDetailDelete(detailTabs[0].key)">明细删除</NButton>
          </template>
          <!-- 多个从表：下拉按钮 -->
          <template v-else>
            <NDropdown trigger="click" :options="detailAddOptions" @select="handleDetailAdd">
              <NButton size="small">明细新增 ▾</NButton>
            </NDropdown>
            <NDropdown trigger="click" :options="detailDeleteOptions" @select="handleDetailDelete">
              <NButton size="small" type="error">明细删除 ▾</NButton>
            </NDropdown>
          </template>
        </template>

        <ApprovalActionGroup :runtime="runtime" :get-selected-row="getSelectedMasterRow" />
        <template v-for="item in mergedToolbarItems" :key="item.key">
          <!-- 下拉按钮：多个 tab 同名 action 合并 -->
          <NDropdown
            v-if="item.children"
            trigger="click"
            :options="item.children"
            @select="(key: string) => handleDropdownSelect(key, item)"
          >
            <NButton :type="item.type || 'default'" :disabled="item.disabled" size="small">{{ item.label }} ▾</NButton>
          </NDropdown>
          <!-- 普通按钮 -->
          <NButton
            v-else
            :type="item.type || 'default'"
            :disabled="item.disabled"
            size="small"
            @click="handleToolbarClick(item)"
          >
            {{ item.label }}
          </NButton>
        </template>
      </NSpace>
    </div>

    <NSplit
      v-if="isSplitMode && hasDetailTabs"
      direction="vertical"
      :default-size="splitConfig.defaultSize"
      :min="splitConfig.min"
      :max="splitConfig.max"
      class="split-container"
    >
      <template #1>
        <div class="master-panel">
          <AgGridVue
            key="split-master-grid"
            class="ag-theme-quartz master-grid"
            :column-defs="masterColumnDefs"
            :default-col-def="defaultColDef"
            :get-row-id="getMasterRowId"
            :get-row-class="getRowClass"
            :get-row-style="getRowStyle"
            :row-selection="rowSelection"
            :auto-size-strategy="autoSizeStrategy"
            :get-context-menu-items="getMasterContextMenuItems"
            :master-detail="false"
            :detail-row-auto-height="false"
            :get-row-height="getRowHeight"
            :keep-detail-rows="false"
            :detail-cell-renderer="undefined"
            :context="gridContext"
            :row-height="rowHeight"
            :header-height="headerHeight"
            :undo-redo-cell-editing="true"
            :undo-redo-cell-editing-limit="20"
            v-bind="masterGridRuntimeOptions"
            @grid-ready="handleMasterGridReady"
            @selection-changed="onSelectionChanged"
            @row-group-opened="onDetailRowOpened"
            @cell-editing-started="onCellEditingStarted"
            @cell-editing-stopped="onCellEditingStopped"
            @cell-value-changed="onMasterCellValueChanged"
            @cell-clicked="onMasterCellClicked"
            @filter-changed="onFilterChanged"
          />
        </div>
      </template>
      <template #2>
        <DetailPanelV3
          :tabs="detailTabs"
          :active-master-id="activeMasterId"
          :active-master-row-key="activeMasterRowKey"
          :detail-cache="detailCache"
          :detail-columns-by-tab="detailColumnsByTab"
          :detail-row-editable-rules-by-tab="detailRowEditableRulesByTab"
          :detail-cell-editable-rules-by-tab="detailCellEditableRulesByTab"
          :detail-row-class-by-tab="mergedDetailRowClassByTab"
          :detail-grid-options-by-tab="detailGridOptionsByTab"
          :detail-sum-fields-by-tab="detailSumFieldsByTab"
          :row-state-api="rowStateApi"
          :cell-class-rules="cellClassRules"
          :apply-grid-config="applyGridConfig"
          :on-detail-cell-value-changed="applyDetailCellValueChanged"
          :on-detail-cell-clicked="onDetailCellClicked"
          :on-cell-editing-started="onCellEditingStarted"
          :on-cell-editing-stopped="onCellEditingStopped"
          :load-detail-data="loadDetailData"
          :register-detail-grid-api="registerDetailGridApi"
          :unregister-detail-grid-api="unregisterDetailGridApi"
          :get-detail-context-menu-items="getDetailContextMenuItems"
          :refresh-detail-row-height="refreshDetailRowHeight"
          default-view-mode="stack"
          :view-mode="detailViewMode"
          @update:active-tab="(v: string) => (activeDetailTab = v)"
        />
      </template>
    </NSplit>

    <div v-else class="master-panel">
      <AgGridVue
        key="master-detail-grid"
        class="ag-theme-quartz master-grid"
        :column-defs="masterColumnDefs"
        :default-col-def="defaultColDef"
        :get-row-id="getMasterRowId"
        :get-row-class="getRowClass"
        :get-row-style="getRowStyle"
        :row-selection="rowSelection"
        :auto-size-strategy="autoSizeStrategy"
        :get-context-menu-items="getMasterContextMenuItems"
        :master-detail="hasDetailTabs"
        :detail-row-auto-height="false"
        :get-row-height="getRowHeight"
        :keep-detail-rows="hasDetailTabs"
        :detail-cell-renderer="hasDetailTabs ? DetailRowRendererV3 : undefined"
        :context="gridContext"
        :row-height="rowHeight"
        :header-height="headerHeight"
        :undo-redo-cell-editing="true"
        :undo-redo-cell-editing-limit="20"
        v-bind="masterGridRuntimeOptions"
        @grid-ready="handleMasterGridReady"
        @selection-changed="onSelectionChanged"
        @row-group-opened="onDetailRowOpened"
        @cell-editing-started="onCellEditingStarted"
        @cell-editing-stopped="onCellEditingStopped"
        @cell-value-changed="onMasterCellValueChanged"
        @cell-clicked="onMasterCellClicked"
        @filter-changed="onFilterChanged"
      />
    </div>
  </div>
</template>

<style scoped>
.master-detail-layout-v3 {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

.toolbar-container {
  padding: 4px 0;
  flex-shrink: 0;
}

.split-container {
  flex: 1;
  min-height: 0;
}

.master-panel {
  flex: 1;
  min-height: 0;
  height: 100%;
}

.master-grid {
  width: 100%;
  height: 100%;
}
</style>
