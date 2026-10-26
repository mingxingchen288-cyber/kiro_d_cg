import { nextTick, type Ref } from 'vue';
import { clearCalcCache } from '@/v3/logic/calc-engine';
import type { RowStateApi } from '@/v3/composables/meta-v3/useWorkingSetStore';
import {
  columnDefsEquivalent,
  detailColumnDefsMapEquivalent,
  findFirstGridKey,
  shouldUseCalcOnlyHotReload
} from './helpers';
import type { ComponentStateByKey, GridState, RuntimeFeatures } from './types';

type HotReloadMasterTarget = {
  masterId: number;
  rowKey: string;
  row: any;
  node?: any;
};

type RuntimeMetadataReloadOptions = {
  pageCode: string;
  resolvedFeatures: Ref<Required<RuntimeFeatures>>;
  meta: {
    pageComponents: Ref<any[]>;
    masterGridKey: Ref<string | null>;
    masterColumnDefs: Ref<any[]>;
    detailColumnsByTab: Ref<Record<string, any[]>>;
  };
  componentStateByKey: Ref<ComponentStateByKey>;
  masterGridApi: Ref<any>;
  detailGridApisByTab: Ref<Record<string, any>>;
  detailCache: Map<string, any>;
  resolveMasterRowKey: (masterId: number) => string | null;
  rowStateApi: RowStateApi;
  applyGridConfig: (gridKey: string, api: any, columnApi: any, sourceColumnDefs: any[]) => Promise<void>;
  loadComponents: () => Promise<boolean>;
  parseConfig: () => boolean;
  loadMeta: () => Promise<boolean>;
  compileRules: () => boolean;
  refreshAutoFeatures: () => void;
  runMasterCalc: (node: any, row: any) => void;
  broadcastToDetail: (masterId: number, row: any) => Promise<unknown>;
};

export function useRuntimeMetadataReload(options: RuntimeMetadataReloadOptions) {
  const {
    resolvedFeatures,
    meta,
    componentStateByKey,
    masterGridApi,
    detailGridApisByTab,
    detailCache,
    resolveMasterRowKey,
    rowStateApi,
    applyGridConfig,
    loadComponents,
    parseConfig,
    loadMeta,
    compileRules,
    refreshAutoFeatures,
    runMasterCalc,
    broadcastToDetail
  } = options;

  function isMasterRowDirty(row: any): boolean {
    if (!row) return false;
    if (rowStateApi.isRowDeleted(row)) return false;
    return rowStateApi.hasRowChanges(row);
  }

  function collectDirtyMasterTargets(): HotReloadMasterTarget[] {
    const api = masterGridApi.value as any;
    if (!api?.forEachNode) return [];

    const targetMap = new Map<string, HotReloadMasterTarget>();
    api.forEachNode((node: any) => {
      const row = node?.data;
      if (!row || !isMasterRowDirty(row)) return;

      const masterId = row?.id != null ? Number(row.id) : Number.NaN;
      if (Number.isNaN(masterId)) return;

      const rowKey = row?._rowKey ? String(row._rowKey) : resolveMasterRowKey(masterId);
      if (!rowKey) return;

      targetMap.set(String(rowKey), {
        masterId,
        rowKey: String(rowKey),
        row,
        node
      });
    });

    return Array.from(targetMap.values());
  }

  function recalcDirtyMasterRowsForHotReload(targets?: HotReloadMasterTarget[]) {
    const resolvedTargets = targets || collectDirtyMasterTargets();
    if (resolvedTargets.length === 0) return [];

    for (const target of resolvedTargets) {
      runMasterCalc(target.node, target.row);
    }
    return resolvedTargets;
  }

  async function cascadeDirtyMasterRowsForHotReload(targets: HotReloadMasterTarget[]) {
    if (!resolvedFeatures.value.detailTabs) return;
    if (targets.length === 0) return;
    for (const target of targets) {
      if (!detailCache.has(target.rowKey)) continue;
      await broadcastToDetail(target.masterId, target.row);
    }
  }

  function refreshRenderedMasterCellsForHotReload() {
    const api = masterGridApi.value as any;
    if (!api?.getRenderedNodes) return;
    const renderedNodes = api.getRenderedNodes() || [];
    if (renderedNodes.length === 0) return;
    api.refreshCells({ rowNodes: renderedNodes, force: true, suppressFlash: true });
  }

  function updateMasterGridStateColumnDefs(defs: any[]) {
    const masterKey = meta.masterGridKey.value || findFirstGridKey(meta.pageComponents.value || []);
    const gridState = masterKey ? (componentStateByKey.value[masterKey] as GridState | undefined) : undefined;
    if (gridState) {
      gridState.columnDefs = defs;
    }
  }

  function preserveUnchangedColumnRefs(params: {
    previousMasterColumnDefs: any[];
    previousDetailColumnsByTab: Record<string, any[]>;
  }) {
    const { previousMasterColumnDefs, previousDetailColumnsByTab } = params;
    const latestMasterColumnDefs = meta.masterColumnDefs.value || [];
    const latestDetailColumnsByTab = meta.detailColumnsByTab.value || {};
    const masterColumnDefsChanged = !columnDefsEquivalent(previousMasterColumnDefs, latestMasterColumnDefs);
    const detailColumnDefsChanged = !detailColumnDefsMapEquivalent(
      previousDetailColumnsByTab,
      latestDetailColumnsByTab
    );

    if (!masterColumnDefsChanged) {
      meta.masterColumnDefs.value = previousMasterColumnDefs;
    }
    if (!detailColumnDefsChanged) {
      meta.detailColumnsByTab.value = previousDetailColumnsByTab;
    }

    return {
      masterColumnDefsChanged,
      latestMasterColumnDefs: meta.masterColumnDefs.value || latestMasterColumnDefs
    };
  }

  function applyMasterColumnDefsForHotReload(params: {
    masterColumnDefsChanged: boolean;
    latestMasterColumnDefs: any[];
  }) {
    const { masterColumnDefsChanged, latestMasterColumnDefs } = params;
    const api = masterGridApi.value as any;
    if (!api) return;
    if (!masterColumnDefsChanged || latestMasterColumnDefs.length === 0) {
      updateMasterGridStateColumnDefs(meta.masterColumnDefs.value || []);
      return;
    }

    api.setGridOption('columnDefs', latestMasterColumnDefs);
    updateMasterGridStateColumnDefs(latestMasterColumnDefs);
  }

  async function reapplyGridConfigsForHotReload() {
    await nextTick();

    const masterApi = masterGridApi.value as any;
    const masterKey = meta.masterGridKey.value || findFirstGridKey(meta.pageComponents.value || []);
    if (masterApi && masterKey) {
      await applyGridConfig(
        masterKey,
        masterApi,
        masterApi.columnApi ?? masterApi.getColumnApi?.(),
        meta.masterColumnDefs.value || []
      );
    }

    const detailApis = detailGridApisByTab.value || {};
    for (const [tabKey, api] of Object.entries(detailApis)) {
      if (!api) continue;
      await applyGridConfig(tabKey, api, (api as any).columnApi ?? api.getColumnApi?.(), meta.detailColumnsByTab.value?.[tabKey] || []);
    }
  }

  async function reloadCalcRulesOnly() {
    clearCalcCache();
    const componentsOk = await loadComponents();
    if (!componentsOk) return;
    parseConfig();
    compileRules();
    refreshAutoFeatures();

    const dirtyTargets = recalcDirtyMasterRowsForHotReload();
    await cascadeDirtyMasterRowsForHotReload(dirtyTargets);
    refreshRenderedMasterCellsForHotReload();
  }

  async function reloadMetadata(payload?: Record<string, any>) {
    console.log(`[MetaRuntime] reloadMetadata for ${options.pageCode}`, payload || {});
    if (shouldUseCalcOnlyHotReload(payload)) {
      await reloadCalcRulesOnly();
      return;
    }

    const previousMasterColumnDefs = meta.masterColumnDefs.value || [];
    const previousDetailColumnsByTab = meta.detailColumnsByTab.value || {};
    clearCalcCache();
    const componentsOk = await loadComponents();
    if (!componentsOk) return;
    parseConfig();
    await loadMeta();
    compileRules();
    refreshAutoFeatures();

    const { masterColumnDefsChanged, latestMasterColumnDefs } = preserveUnchangedColumnRefs({
      previousMasterColumnDefs,
      previousDetailColumnsByTab
    });
    applyMasterColumnDefsForHotReload({ masterColumnDefsChanged, latestMasterColumnDefs });
    await reapplyGridConfigsForHotReload();

    const dirtyTargets = recalcDirtyMasterRowsForHotReload();
    await cascadeDirtyMasterRowsForHotReload(dirtyTargets);
    refreshRenderedMasterCellsForHotReload();
  }

  return { reloadMetadata };
}
