import type { Ref } from 'vue';
import type { RowData } from '@/v3/logic/calc-engine';
import type { RuntimeFeatures } from './types';

type RunMasterCalc = (node: any, row: RowData, valueOverrides?: Record<string, any>) => string[] | void;

type RunDetailCalc = (
  node: any,
  api: any,
  row: RowData,
  masterId: number,
  tabKey: string,
  masterRowKey?: string,
  changedFields?: string | string[],
  valueOverrides?: Record<string, any>
) => string[] | void;

type RecalcAggregates = (masterId: number, masterRowKey?: string) => void;
type BroadcastToDetail = (masterId: number, row: RowData, changedFields?: string | string[]) => Promise<void> | void;
type MarkFieldChange = (row: RowData, field: string, oldValue: any, newValue: any, type: 'user' | 'calc') => void;
type RowChange = { field: string; oldValue: any; newValue: any };
type MasterPatchResult = {
  row: RowData;
  rowKey: string;
  node: any;
  changes: RowChange[];
} | null;
type DetailPatchResult = {
  row: RowData;
  masterId: number;
  masterRowKey: string;
  detailRowKey: string;
  changes: RowChange[];
  applyToGrids: (callback: (api: any, node: any) => void) => void;
} | null;

type AddMasterRow = () => RowData | null | undefined;
type DeleteMasterRow = (row: RowData) => void;
type CopyMasterRow = (row: RowData) => Promise<RowData | null | undefined> | RowData | null | undefined;
type AddDetailRow = (masterId: number, tabKey: string, masterRowKey?: string) => RowData | null | undefined;
type DeleteDetailRow = (masterId: number, tabKey: string, row: RowData, masterRowKey?: string) => boolean;
type CopyDetailRow = (masterId: number, tabKey: string, sourceRow: RowData, masterRowKey?: string) => RowData | null | undefined;

export function useRuntimeMutations(params: {
  resolvedFeatures: Ref<Required<RuntimeFeatures>>;
  masterGridApi: Ref<any>;
  detailGridApisByTab: Ref<Record<string, any>>;
  activeMasterRowKey?: Ref<string | null>;
  addMasterRowRaw: AddMasterRow;
  deleteMasterRowRaw: DeleteMasterRow;
  copyMasterRowRaw: CopyMasterRow;
  addDetailRowRaw: AddDetailRow;
  deleteDetailRowRaw: DeleteDetailRow;
  copyDetailRowRaw: CopyDetailRow;
  applyMasterPatchRaw: (
    rowId: number | null,
    rowKey: string | null,
    patch: Record<string, any>,
    fallbackChanges?: RowChange[]
  ) => MasterPatchResult;
  applyDetailPatchRaw: (
    tabKey: string,
    rowId: number | null,
    rowKey: string | null,
    patch: Record<string, any>,
    fallbackChanges?: RowChange[]
  ) => DetailPatchResult;
  markFieldChange: MarkFieldChange;
  runMasterCalc: RunMasterCalc;
  runDetailCalc: RunDetailCalc;
  recalcAggregates: RecalcAggregates;
  broadcastToDetail?: BroadcastToDetail;
  isLoadingMasterRows?: () => boolean;
  isLoadingDetailRows?: (masterRowKey?: string | null, tabKey?: string | null) => boolean;
}) {
  const {
    resolvedFeatures,
    masterGridApi,
    detailGridApisByTab,
    activeMasterRowKey,
    addMasterRowRaw,
    deleteMasterRowRaw,
    copyMasterRowRaw,
    addDetailRowRaw,
    deleteDetailRowRaw,
    copyDetailRowRaw,
    applyMasterPatchRaw,
    applyDetailPatchRaw,
    markFieldChange,
    runMasterCalc,
    runDetailCalc,
    recalcAggregates,
    broadcastToDetail,
    isLoadingMasterRows,
    isLoadingDetailRows
  } = params;

  function resolveChangeMeta(event: any) {
    const source = String(event?.source || '').toLowerCase();
    const isApiChange = source === 'api' || source === 'rowdatachanged';
    return {
      isApiChange,
      changeType: isApiChange ? 'calc' : 'user'
    } as const;
  }

  function normalizeEventCellValue(event: any, value: any) {
    if (event?.colDef?.context?.dataType !== 'checkbox') {
      return value;
    }
    if (value === true) return 1;
    if (value === false) return 0;
    if (typeof value === 'number') return value !== 0 ? 1 : 0;
    const text = String(value ?? '').trim().toLowerCase();
    return ['1', 'true', 'y', 'yes', '是'].includes(text) ? 1 : 0;
  }

  function applyChangeMarks(row: RowData, changes: RowChange[], changeType: 'user' | 'calc') {
    changes.forEach(change => {
      markFieldChange(row, change.field, change.oldValue, change.newValue, changeType);
    });
  }

  function refreshMasterRow(node: any, apiOverride?: any) {
    const api = apiOverride ?? masterGridApi.value;
    api?.refreshCells?.({
      rowNodes: node ? [node] : undefined,
      force: true
    });
    api?.redrawRows?.({
      rowNodes: node ? [node] : undefined
    });
  }

  function refreshDetailRows(patchResult: Exclude<DetailPatchResult, null>) {
    patchResult.applyToGrids((api, node) => {
      api?.refreshCells?.({
        rowNodes: node ? [node] : undefined,
        force: true
      });
      api?.redrawRows?.({
        rowNodes: node ? [node] : undefined
      });
    });
  }

  function finalizeDetailMutation(masterId: number, tabKey: string, row: RowData | null | undefined, masterRowKey?: string) {
    if (!row) return row;
    if (resolvedFeatures.value.detailTabs) {
      const api = detailGridApisByTab.value?.[tabKey];
      runDetailCalc(null, api, row, masterId, tabKey, masterRowKey);
    }
    recalcAggregates(masterId, masterRowKey);
    return row;
  }

  function addMasterRow() {
    const row = addMasterRowRaw();
    if (row) {
      runMasterCalc(null, row);
    }
    return row;
  }

  function deleteMasterRow(row: RowData) {
    deleteMasterRowRaw(row);
  }

  async function copyMasterRow(sourceRow: RowData) {
    const row = await copyMasterRowRaw(sourceRow);
    if (row) {
      runMasterCalc(null, row);
    }
    return row;
  }

  function addDetailRow(masterId: number, tabKey: string, masterRowKey?: string) {
    const row = addDetailRowRaw(masterId, tabKey, masterRowKey);
    return finalizeDetailMutation(masterId, tabKey, row, masterRowKey);
  }

  function deleteDetailRow(masterId: number, tabKey: string, row: RowData, masterRowKey?: string) {
    const deleted = deleteDetailRowRaw(masterId, tabKey, row, masterRowKey);
    if (deleted) {
      recalcAggregates(masterId, masterRowKey);
    }
    return deleted;
  }

  function copyDetailRow(masterId: number, tabKey: string, sourceRow: RowData, masterRowKey?: string) {
    const row = copyDetailRowRaw(masterId, tabKey, sourceRow, masterRowKey);
    return finalizeDetailMutation(masterId, tabKey, row, masterRowKey);
  }

  async function commitMasterPatch(params: {
    rowId: number | null;
    rowKey: string | null;
    patch: Record<string, any>;
    fallbackChanges?: RowChange[];
    changeType?: 'user' | 'calc';
    node?: any;
    api?: any;
    valueOverrides?: Record<string, any>;
    runCalc?: boolean;
    broadcast?: boolean;
  }) {
    const patchResult = applyMasterPatchRaw(params.rowId, params.rowKey, params.patch, params.fallbackChanges);
    if (!patchResult || patchResult.changes.length === 0) return null;

    const changeType = params.changeType ?? 'user';
    applyChangeMarks(patchResult.row, patchResult.changes, changeType);

    const changedFields = patchResult.changes.map(change => change.field).filter(Boolean);
    const targetNode = patchResult.node ?? params.node ?? null;
    refreshMasterRow(targetNode, params.api);

    const shouldRunCalc = params.runCalc ?? changeType === 'user';
    const calcChanged = shouldRunCalc ? runMasterCalc(targetNode, patchResult.row, params.valueOverrides) || [] : [];

    if ((params.broadcast ?? shouldRunCalc) && broadcastToDetail && patchResult.row.id != null) {
      const triggerFields = [...changedFields, ...calcChanged].filter(Boolean);
      if (triggerFields.length > 0) {
        await broadcastToDetail(patchResult.row.id, patchResult.row, triggerFields);
      }
    }

    return {
      ...patchResult,
      changedFields,
      calcChanged
    };
  }

  function commitDetailPatch(params: {
    masterId?: number | null;
    tabKey: string;
    rowId: number | null;
    rowKey: string | null;
    patch: Record<string, any>;
    fallbackChanges?: RowChange[];
    changeType?: 'user' | 'calc';
    masterRowKey?: string;
    node?: any;
    api?: any;
    valueOverrides?: Record<string, any>;
    runCalc?: boolean;
    recalc?: boolean;
  }) {
    const patchResult = applyDetailPatchRaw(params.tabKey, params.rowId, params.rowKey, params.patch, params.fallbackChanges);
    if (!patchResult || patchResult.changes.length === 0) return null;

    const changeType = params.changeType ?? 'user';
    applyChangeMarks(patchResult.row, patchResult.changes, changeType);

    const resolvedRowKey = params.masterRowKey ?? patchResult.masterRowKey ?? activeMasterRowKey?.value ?? undefined;
    const changedFields = patchResult.changes.map(change => change.field).filter(Boolean);
    const shouldRunCalc = params.runCalc ?? changeType === 'user';

    if (shouldRunCalc) {
      let calcApi = params.api;
      let calcNode = params.node;
      patchResult.applyToGrids((api, node) => {
        if (!calcApi && api) calcApi = api;
        if (!calcNode && node) calcNode = node;
      });
      runDetailCalc(
        calcNode ?? null,
        calcApi,
        patchResult.row,
        patchResult.masterId,
        params.tabKey,
        resolvedRowKey,
        changedFields,
        params.valueOverrides
      );
    }

    refreshDetailRows(patchResult);
    patchResult.applyToGrids(api => {
      api?.refreshClientSideRowModel?.('aggregate');
    });

    const resolvedMasterId = params.masterId ?? patchResult.masterId;
    if ((params.recalc ?? shouldRunCalc) && resolvedMasterId != null) {
      recalcAggregates(resolvedMasterId, resolvedRowKey);
    }

    return {
      ...patchResult,
      changedFields,
      masterRowKey: resolvedRowKey ?? patchResult.masterRowKey
    };
  }

  async function onMasterCellValueChanged(event: any) {
    const field = event.colDef?.field;
    const row = event.data as RowData | undefined;
    const masterId = row?.id;
    if (!field || masterId == null || event.node?.rowPinned) return false;
    if (isLoadingMasterRows?.()) return false;
    const oldValue = normalizeEventCellValue(event, event.oldValue);
    const newValue = normalizeEventCellValue(event, event.data?.[field] ?? event.newValue);
    if (Object.is(oldValue, newValue)) return false;

    const { isApiChange, changeType } = resolveChangeMeta(event);
    const patchResult = await commitMasterPatch({
      rowId: row?.id ?? null,
      rowKey: row?._rowKey ?? null,
      patch: { [field]: newValue },
      fallbackChanges: [{ field, oldValue, newValue }],
      changeType,
      node: event.node,
      api: event.api,
      valueOverrides: !isApiChange ? { [field]: newValue } : undefined,
      runCalc: !isApiChange,
      broadcast: !isApiChange
    });

    return Boolean(patchResult);
  }

  function onDetailCellValueChanged(event: any, masterId: number, tabKey: string, masterRowKey?: string) {
    const field = event.colDef?.field;
    const row = event.data as RowData | undefined;
    if (!field || !masterId || event.node?.rowPinned) return false;
    if (isLoadingDetailRows?.(masterRowKey, tabKey)) return false;
    const oldValue = normalizeEventCellValue(event, event.oldValue);
    const newValue = normalizeEventCellValue(event, event.data?.[field] ?? event.newValue);
    if (Object.is(oldValue, newValue)) return false;

    const { isApiChange, changeType } = resolveChangeMeta(event);
    const patchResult = commitDetailPatch({
      masterId,
      tabKey,
      rowId: row?.id ?? null,
      rowKey: row?._rowKey ?? null,
      patch: { [field]: newValue },
      fallbackChanges: [{ field, oldValue, newValue }],
      changeType,
      masterRowKey,
      node: event.node,
      api: event.api,
      valueOverrides: !isApiChange ? { [field]: newValue } : undefined,
      runCalc: !isApiChange,
      recalc: !isApiChange
    });

    return Boolean(patchResult);
  }

  return {
    addMasterRow,
    deleteMasterRow,
    copyMasterRow,
    addDetailRow,
    deleteDetailRow,
    copyDetailRow,
    commitMasterPatch,
    commitDetailPatch,
    onMasterCellValueChanged,
    onDetailCellValueChanged
  };
}
