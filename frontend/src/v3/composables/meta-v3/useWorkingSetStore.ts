import { ref, type Ref, type ShallowRef } from 'vue';
import type { GridApi } from 'ag-grid-community';
import { createDynamicSaveRequestId, fetchDynamicDataById, saveDynamicData, searchDynamicData, type DynamicQueryCondition, type DynamicSaveParam } from '@/service/api';
import { useAuthStore } from '@/store/modules/auth';
import { forEachNestedDetailGridApi } from '@/v3/composables/meta-v3/detail-grid-apis';
import { applyCopiedRowFields } from '@/v3/composables/meta-v3/copy-row-fields';
import { createMasterServerSideDataSource } from '@/v3/composables/meta-v3/master-server-side-data-source';
import { applyRowPatch, type RowFieldChange } from '@/v3/composables/meta-v3/row-patch';
import { isPersistedRow } from '@/v3/composables/meta-v3/row-persistence';
import { findRowByIdentity, isSameRowIdentity } from '@/v3/composables/meta-v3/row-identity';
import {
  type ParsedPageConfig,
  type RowData,
  type ValidationRule,
  ensureRowKey,
  formatValidationErrors,
  generateTempId,
  initRowData,
  validateRows
} from '@/v3/logic/calc-engine';

type QueryCondition = DynamicQueryCondition;
type NotifyFn = (message: string) => void;
type DetailValidationRules = Record<string, ValidationRule[]>;
type ColumnMetaByTab = Record<string, any[]>;
type DetailCache = Map<string, Record<string, RowData[]>>;

export type RowChangeType = 'user' | 'calc';

export type RowFieldState = {
  originalValue: any;
  newValue: any;
  type: RowChangeType;
};

export type RowChangeState = {
  status: 'new' | 'updated' | 'deleted';
  fields: Record<string, RowFieldState>;
};

export type RowStateApi = {
  getRowChange: (row: RowData | string | null | undefined) => RowChangeState | null;
  getDirtyFields: (row: RowData | string | null | undefined) => Record<string, RowFieldState>;
  getFieldChangeType: (row: RowData | string | null | undefined, field?: string | null) => RowChangeType | undefined;
  isRowNew: (row: RowData | string | null | undefined) => boolean;
  isRowDeleted: (row: RowData | string | null | undefined) => boolean;
  hasDirtyFields: (row: RowData | string | null | undefined) => boolean;
  hasRowChanges: (row: RowData | string | null | undefined) => boolean;
  markRowNew: (row: RowData) => void;
  markRowDeleted: (row: RowData) => void;
  clearRowChanges: (row: RowData | string | null | undefined) => void;
  markFieldChange: (row: RowData, field: string, oldValue: any, newValue: any, type: RowChangeType) => void;
};

export function useWorkingSetStore(params: {
  pageCode: string;
  pageConfig: Ref<ParsedPageConfig | null>;
  detailFkColumnByTab: Ref<Record<string, string>>;
  masterPkColumn: Ref<string>;
  detailPkColumnByTab: Ref<Record<string, string>>;
  masterValidationRules: Ref<ValidationRule[]>;
  detailValidationRulesByTab: Ref<DetailValidationRules>;
  masterColumnMeta: Ref<any[]>;
  detailColumnMetaByTab: Ref<ColumnMetaByTab>;
  masterGridApi: ShallowRef<GridApi | null>;
  detailGridApisByTab?: Ref<Record<string, any>>;
  activeMasterRowKey?: Ref<string | null>;
  initialMasterId?: number | null;
  notifyInfo: NotifyFn;
  notifyError: NotifyFn;
  notifySuccess: NotifyFn;
}) {
  const {
    pageCode,
    pageConfig,
    detailFkColumnByTab,
    masterPkColumn,
    detailPkColumnByTab,
    masterValidationRules,
    detailValidationRulesByTab,
    masterColumnMeta,
    detailColumnMetaByTab,
    masterGridApi,
    detailGridApisByTab,
    activeMasterRowKey,
    initialMasterId,
    notifyInfo,
    notifyError,
    notifySuccess
  } = params;
  const authStore = useAuthStore();

  const detailCache: DetailCache = new Map();
  const advancedConditions = ref<QueryCondition[]>([]);
  const routeMasterId = ref<number | null>(initialMasterId ?? null);
  const changeSet = new Map<string, RowChangeState>();
  const loadingDetailKeys = new Set<string>();
  const loadingDetailTimers = new Map<string, ReturnType<typeof setTimeout>>();
  let isLoadingMasterRowsFlag = false;
  let loadingMasterRowsTimer: ReturnType<typeof setTimeout> | null = null;
  const isSaving = ref(false);
  // Keep the exact request until the server confirms its outcome. A manual retry must use the same key and content.
  const unconfirmedSaves = new Map<string, { requestId: string; payloadJson: string }>();

  function resolveRowKey(row: RowData | string | null | undefined) {
    if (!row) return null;
    if (typeof row === 'string') return row;
    return ensureRowKey(row);
  }

  function getRowChange(row: RowData | string | null | undefined): RowChangeState | null {
    const rowKey = resolveRowKey(row);
    if (!rowKey) return null;
    return changeSet.get(rowKey) || null;
  }

  function getDirtyFields(row: RowData | string | null | undefined) {
    return getRowChange(row)?.fields || {};
  }

  function getFieldChangeType(row: RowData | string | null | undefined, field?: string | null) {
    if (!field) return undefined;
    return getDirtyFields(row)[field]?.type;
  }

  function isRowNew(row: RowData | string | null | undefined) {
    return getRowChange(row)?.status === 'new';
  }

  function isRowDeleted(row: RowData | string | null | undefined) {
    return getRowChange(row)?.status === 'deleted';
  }

  function hasDirtyFields(row: RowData | string | null | undefined) {
    return Object.keys(getDirtyFields(row)).length > 0;
  }

  function hasRowChanges(row: RowData | string | null | undefined) {
    return Boolean(getRowChange(row));
  }

  function setRowChange(rowKey: string, next: RowChangeState | null) {
    if (!next) {
      changeSet.delete(rowKey);
      return;
    }
    if (next.status === 'updated' && Object.keys(next.fields).length === 0) {
      changeSet.delete(rowKey);
      return;
    }
    changeSet.set(rowKey, next);
  }

  function markRowNew(row: RowData) {
    const rowKey = ensureRowKey(row);
    const previous = getRowChange(rowKey);
    setRowChange(rowKey, {
      status: 'new',
      fields: previous?.fields || {}
    });
  }

  function markRowDeleted(row: RowData) {
    const rowKey = ensureRowKey(row);
    const previous = getRowChange(rowKey);
    setRowChange(rowKey, {
      status: 'deleted',
      fields: previous?.fields || {}
    });
  }

  function clearRowChanges(row: RowData | string | null | undefined) {
    const rowKey = resolveRowKey(row);
    if (!rowKey) return;
    changeSet.delete(rowKey);
  }

  function markFieldChange(row: RowData, field: string, oldValue: any, newValue: any, type: RowChangeType) {
    const rowKey = ensureRowKey(row);
    const previous = getRowChange(rowKey);
    const fields = { ...(previous?.fields || {}) };
    const fieldState = fields[field];
    const originalValue = fieldState ? fieldState.originalValue : oldValue;

    if (Object.is(newValue, originalValue)) {
      delete fields[field];
    } else {
      fields[field] = {
        originalValue,
        newValue,
        type: fieldState?.type === 'user' || type === 'user' ? 'user' : type
      };
    }

    const nextStatus = previous?.status || (isPersistedRow(row) ? 'updated' : 'new');
    setRowChange(rowKey, {
      status: nextStatus,
      fields
    });
  }

  const rowStateApi: RowStateApi = {
    getRowChange,
    getDirtyFields,
    getFieldChangeType,
    isRowNew,
    isRowDeleted,
    hasDirtyFields,
    hasRowChanges,
    markRowNew,
    markRowDeleted,
    clearRowChanges,
    markFieldChange
  };

  function getMasterRowByRowKey(rowKey: string): RowData | null {
    if (!rowKey) return null;
    const api = masterGridApi.value as any;
    const node = api?.getRowNode?.(String(rowKey));
    if (node?.data) return node.data as RowData;
    return null;
  }

  function getMasterRowById(id: number): RowData | null {
    if (id == null) return null;
    const api = masterGridApi.value as any;
    let found: RowData | null = null;
    api?.forEachNode?.((node: any) => {
      if (node?.data?.id === id) {
        found = node.data;
      }
    });
    return found;
  }

  function resolveMasterRowKey(masterId: number): string | null {
    const row = getMasterRowById(masterId);
    if (!row) return null;
    ensureRowKey(row);
    return row._rowKey || null;
  }

  function setAdvancedConditions(conditions: QueryCondition[]) {
    advancedConditions.value = Array.isArray(conditions)
      ? conditions.filter(condition => Boolean(condition?.field) && Boolean(condition?.operator))
      : [];
  }

  function clearAdvancedConditions() {
    advancedConditions.value = [];
  }

  function getMasterQueryConditions() {
    const conditions = [...advancedConditions.value];
    if (routeMasterId.value != null) {
      conditions.push({ field: masterPkColumn.value, operator: 'eq', value: routeMasterId.value });
    }
    return conditions;
  }

  function setRouteMasterId(masterId: number | null) {
    routeMasterId.value = masterId;
  }

  const createServerSideDataSource = createMasterServerSideDataSource({
    pageCode,
    getTableCode: () => pageConfig.value?.masterTableCode,
    getMasterPkColumn: () => masterPkColumn.value,
    getAdvancedConditions: getMasterQueryConditions,
    notifyError,
    markMasterRowsLoading
  });

  function markMasterRowsLoading() {
    isLoadingMasterRowsFlag = true;
    if (loadingMasterRowsTimer) clearTimeout(loadingMasterRowsTimer);
    loadingMasterRowsTimer = setTimeout(() => {
      isLoadingMasterRowsFlag = false;
      loadingMasterRowsTimer = null;
    }, 100);
  }

  function isLoadingMasterRows() {
    return isLoadingMasterRowsFlag;
  }

  function getDetailLoadingKey(masterRowKey: string, tabKey: string) {
    return `${masterRowKey}::${tabKey}`;
  }

  function markDetailRowsLoading(masterRowKey: string, tabKey: string) {
    const key = getDetailLoadingKey(masterRowKey, tabKey);
    loadingDetailKeys.add(key);
    const existingTimer = loadingDetailTimers.get(key);
    if (existingTimer) clearTimeout(existingTimer);
    const timer = setTimeout(() => {
      loadingDetailKeys.delete(key);
      loadingDetailTimers.delete(key);
    }, 100);
    loadingDetailTimers.set(key, timer);
  }

  function isLoadingDetailRows(masterRowKey?: string | null, tabKey?: string | null) {
    if (!masterRowKey || !tabKey) return false;
    return loadingDetailKeys.has(getDetailLoadingKey(String(masterRowKey), String(tabKey)));
  }

  function setDetailRows(masterRowKey: string, tabKey: string, rows: RowData[]) {
    markDetailRowsLoading(masterRowKey, tabKey);

    forEachNestedDetailGridApi({
      masterGridApi,
      masterRowKey,
      tabKeys: [tabKey],
      callback: api => {
        api?.setGridOption?.('rowData', rows);
      }
    });

    const activeApi = detailGridApisByTab?.value?.[tabKey];
    if (activeApi && activeMasterRowKey?.value === masterRowKey) {
      activeApi.setGridOption?.('rowData', rows);
    }
  }

  async function loadDetailData(masterId: number, masterRowKey?: string) {
    const resolvedRowKey = masterRowKey ?? resolveMasterRowKey(masterId);
    if (!resolvedRowKey) {
      notifyError('无法定位主表行，明细加载失败');
      return;
    }

    const tabs = pageConfig.value?.tabs || [];
    const grouped: Record<string, RowData[]> = {};

    for (const tab of tabs) {
      const tableCode = tab.tableCode || pageConfig.value?.detailTableCode;
      const fkColumn = detailFkColumnByTab.value[tab.key] || 'masterId';
      if (!tableCode) continue;

      const { data, error } = await searchDynamicData(tableCode, {
        pageCode,
        conditions: [{ field: fkColumn, operator: 'eq', value: masterId }]
      });

      grouped[tab.key] = error
        ? []
        : (data?.list || []).map((row: any) => initRowData(row, false, detailPkColumnByTab.value[tab.key]));
    }

    detailCache.set(resolvedRowKey, grouped);
    for (const [tabKey, rows] of Object.entries(grouped)) {
      setDetailRows(resolvedRowKey, tabKey, rows);
    }
  }

  function clearAllCache() {
    detailCache.clear();
    loadingDetailKeys.clear();
    loadingDetailTimers.forEach(timer => clearTimeout(timer));
    loadingDetailTimers.clear();
    if (loadingMasterRowsTimer) clearTimeout(loadingMasterRowsTimer);
    loadingMasterRowsTimer = null;
    isLoadingMasterRowsFlag = false;
  }

  function applyMasterPatch(
    rowId: number | null,
    rowKey: string | null,
    patch: Record<string, any>,
    fallbackChanges?: RowFieldChange[]
  ) {
    const row = (rowKey ? getMasterRowByRowKey(rowKey) : null) ?? (rowId != null ? getMasterRowById(rowId) : null);
    if (!row) return null;

    const resolvedRowKey = String(ensureRowKey(row));
    const node = masterGridApi.value?.getRowNode?.(resolvedRowKey) ?? null;
    const appliedChanges = applyRowPatch(row, patch);
    const changes =
      appliedChanges.length > 0
        ? appliedChanges
        : (fallbackChanges || []).filter(change => !Object.is(change.oldValue, change.newValue));

    return {
      row,
      rowKey: resolvedRowKey,
      node,
      changes
    };
  }

  async function reloadMasterRow(masterId: number, masterRowKey?: string) {
    const tableCode = pageConfig.value?.masterTableCode;
    const resolvedRowKey = masterRowKey ?? resolveMasterRowKey(masterId);
    if (!tableCode || !resolvedRowKey) return null;

    const api = masterGridApi.value as any;
    const currentNode = api?.getRowNode?.(String(resolvedRowKey));
    const currentRow = currentNode?.data as RowData | undefined;
    if (hasRowChanges(currentRow)) {
      return currentRow ?? null;
    }

    const { data, error } = await fetchDynamicDataById(tableCode, masterId);
    if (error || !data) {
      notifyError('加载主表数据失败');
      return currentRow ?? null;
    }

    const refreshedRow = initRowData(data, false, masterPkColumn.value);
    refreshedRow._rowKey = resolvedRowKey;

    if (currentNode?.setData) {
      currentNode.setData(refreshedRow);
    } else {
      api?.applyServerSideTransaction?.({
        route: [],
        update: [refreshedRow]
      });
    }

    return refreshedRow;
  }

  function findDetailGridNode(api: any, detailRowKey: string) {
    return (
      api?.getRowNode?.(String(detailRowKey)) ??
      (() => {
        let matchedNode: any = null;
        api?.forEachNode?.((candidate: any) => {
          if (!matchedNode && candidate?.data?._rowKey === detailRowKey) {
            matchedNode = candidate;
          }
        });
        return matchedNode;
      })()
    );
  }

  function applyDetailPatch(
    tabKey: string,
    rowId: number | null,
    rowKey: string | null,
    patch: Record<string, any>,
    fallbackChanges?: RowFieldChange[]
  ) {
    for (const [masterRowKey, tabData] of detailCache.entries()) {
      const rows = tabData[tabKey];
      if (!rows) continue;

      const row =
        (rowKey ? rows.find(candidate => String(candidate._rowKey || '') === rowKey) : null) ??
        (rowId != null ? rows.find(candidate => candidate.id === rowId) : null);
      if (!row) continue;

      const detailRowKey = String(row._rowKey || '');
      const fkColumn = detailFkColumnByTab.value[tabKey] || 'masterId';
      const masterIdRaw = row[fkColumn];
      if (masterIdRaw == null) return null;
      const masterId = Number(masterIdRaw);
      if (Number.isNaN(masterId)) return null;
      const appliedChanges = applyRowPatch(row, patch);
      const changes =
        appliedChanges.length > 0
          ? appliedChanges
          : (fallbackChanges || []).filter(change => !Object.is(change.oldValue, change.newValue));

      return {
        row,
        masterId,
        masterRowKey,
        detailRowKey,
        changes,
        applyToGrids(callback: (api: any, node: any) => void) {
          forEachNestedDetailGridApi({
            masterGridApi,
            masterRowKey,
            tabKeys: [tabKey],
            callback: api => {
              callback(api, findDetailGridNode(api, detailRowKey));
            }
          });

          const activeApi = detailGridApisByTab?.value?.[tabKey];
          if (activeApi && activeMasterRowKey?.value === masterRowKey) {
            callback(activeApi, findDetailGridNode(activeApi, detailRowKey));
          }
        }
      };
    }

    return null;
  }

  function focusInsertedMasterRow(insertIndex: number, rowKey: string) {
    const api = masterGridApi.value;
    setTimeout(() => {
      api?.ensureIndexVisible(insertIndex, 'middle');
      const newNode = api?.getRowNode(String(rowKey));
      if (newNode) {
        newNode.setSelected(true, true);
      }
    }, 100);
  }

  function insertMasterRow(row: RowData, insertIndex: number) {
    const api = masterGridApi.value;
    if (!api) return;
    api.applyServerSideTransaction({
      route: [],
      add: [row],
      addIndex: insertIndex
    });
    focusInsertedMasterRow(insertIndex, String(row._rowKey));
  }

  function formatDateTime(date: Date, mode: 'date' | 'datetime') {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    if (mode === 'date') {
      return `${year}-${month}-${day}`;
    }
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    const second = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
  }

  function parseDefaultConfig(raw: any) {
    if (raw == null || raw === '') return null;
    if (typeof raw === 'string') {
      try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : { type: 'static', value: raw };
      } catch {
        return { type: 'static', value: raw };
      }
    }
    return typeof raw === 'object' ? raw : { type: 'static', value: raw };
  }

  function resolveBuiltinDefaultValue(code: string, dataType?: string) {
    const userInfo = authStore.userInfo as any;
    switch (code) {
      case 'currentUserId':
        return userInfo.userId ?? '';
      case 'currentDeptId':
        return userInfo.departmentId ?? userInfo.deptId ?? userInfo.currentDeptId ?? '';
      case 'currentUserName':
        return userInfo.realName ?? userInfo.userName ?? '';
      case 'currentDeptName':
        return userInfo.departmentName ?? userInfo.deptName ?? '';
      case 'currentRoleId':
        return userInfo.roleId ?? userInfo.currentRoleId ?? userInfo.roles?.[0] ?? '';
      case 'currentTime':
        return formatDateTime(new Date(), dataType === 'date' ? 'date' : 'datetime');
      default:
        return '';
    }
  }

  function resolveColumnDefaultValue(column: any) {
    const config = parseDefaultConfig(column?.defaultValue);
    if (!config) {
      return column?.dataType === 'number' ? 0 : '';
    }
    if (config.type === 'builtin') {
      return resolveBuiltinDefaultValue(String(config.value || ''), column?.dataType);
    }
    if (config.type === 'multi') {
      const values = Array.isArray(config.value) ? config.value : String(config.value || '').split(',');
      return values.map((item: any) => String(item).trim()).filter(Boolean)[0] ?? '';
    }
    return config.value ?? '';
  }

  function buildDefaultRow(columns: any[] | undefined, base: Record<string, any>) {
    const row: Record<string, any> = {};
    for (const column of columns || []) {
      if (!column?.columnName) continue;
      row[column.columnName] = resolveColumnDefaultValue(column);
    }
    return { ...row, ...base };
  }

  function addMasterRow() {
    const api = masterGridApi.value;
    const newRow = initRowData(buildDefaultRow(masterColumnMeta.value, { id: generateTempId() }), true);
    ensureRowKey(newRow);
    markRowNew(newRow);

    const selectedNodes = api?.getSelectedNodes() || [];
    const insertIndex =
      selectedNodes.length > 0 && selectedNodes[0].rowIndex != null ? selectedNodes[0].rowIndex + 1 : 0;

    insertMasterRow(newRow, insertIndex);
    return newRow;
  }

  function deleteMasterRow(row: RowData) {
    if (!row) return;
    const api = masterGridApi.value;
    const rowKey = row._rowKey ? String(row._rowKey) : null;
    const currentRow =
      (rowKey ? getMasterRowByRowKey(rowKey) : null) ??
      (isPersistedRow(row) ? getMasterRowById(Number(row.id)) : null) ??
      row;

    if (!isPersistedRow(currentRow) || isRowNew(currentRow)) {
      clearRowChanges(currentRow);
      api?.applyServerSideTransaction({
        route: [],
        remove: [currentRow]
      });
      return;
    }

    markRowDeleted(currentRow);
    const node = currentRow._rowKey ? api?.getRowNode?.(String(currentRow._rowKey)) : null;
    api?.refreshCells({
      rowNodes: node ? [node] : undefined,
      force: true
    });
    api?.redrawRows?.({
      rowNodes: node ? [node] : undefined
    });
  }

  async function copyMasterRow(sourceRow: RowData) {
    if (!sourceRow) return null;
    const api = masterGridApi.value;
    const sourceMasterId = sourceRow.id;
    ensureRowKey(sourceRow);
    const sourceRowKey = sourceRow._rowKey as string;
    const newMasterId = generateTempId();
    const newRow = initRowData({ id: newMasterId }, true);
    ensureRowKey(newRow);
    markRowNew(newRow);

    applyCopiedRowFields({
      sourceRow,
      targetRow: newRow,
      excludeFields: [masterPkColumn.value],
      clearFields: [masterPkColumn.value]
    });

    const sourceNode = api?.getRowNode(String(sourceRowKey));
    const insertIndex = sourceNode?.rowIndex != null ? sourceNode.rowIndex + 1 : 0;

    if (sourceMasterId != null && sourceRowKey) {
      let sourceCached = detailCache.get(sourceRowKey);
      if (!sourceCached) {
        await loadDetailData(sourceMasterId, sourceRowKey);
        sourceCached = detailCache.get(sourceRowKey);
      }

      if (sourceCached) {
        const newCached: Record<string, RowData[]> = {};
        for (const [tabKey, rows] of Object.entries(sourceCached)) {
          const fkColumn = detailFkColumnByTab.value[tabKey] || 'masterId';
          const detailPkColumn = detailPkColumnByTab.value[tabKey];
          newCached[tabKey] = rows
            .filter(candidate => !isRowDeleted(candidate))
            .map(candidate => {
              const newDetailRow = initRowData({ id: generateTempId(), [fkColumn]: newMasterId }, true);
              ensureRowKey(newDetailRow);
              markRowNew(newDetailRow);
              applyCopiedRowFields({
                sourceRow: candidate,
                targetRow: newDetailRow,
                excludeFields: [detailPkColumn, fkColumn],
                clearFields: [detailPkColumn]
              });
              return newDetailRow;
            });
        }
        detailCache.set(newRow._rowKey as string, newCached);
      }
    }

    insertMasterRow(newRow, insertIndex);
    return newRow;
  }

  function resolveDetailRows(masterId: number, tabKey: string, masterRowKey?: string) {
    const resolvedRowKey = masterRowKey ?? resolveMasterRowKey(masterId);
    if (!resolvedRowKey) return null;
    const cached = detailCache.get(resolvedRowKey);
    const rows = cached?.[tabKey];
    if (!rows) return null;
    return {
      masterRowKey: resolvedRowKey,
      rows
    };
  }

  function appendDetailRow(detailRows: { masterRowKey: string; rows: RowData[] }, tabKey: string, row: RowData) {
    detailRows.rows.push(row);
    setDetailRows(detailRows.masterRowKey, tabKey, detailRows.rows);
  }

  function addDetailRow(masterId: number, tabKey: string, masterRowKey?: string) {
    const detailRows = resolveDetailRows(masterId, tabKey, masterRowKey);
    if (!detailRows) return null;
    const fkColumn = detailFkColumnByTab.value[tabKey] || 'masterId';
    const newRow = initRowData(
      buildDefaultRow(detailColumnMetaByTab.value[tabKey], { id: generateTempId(), [fkColumn]: masterId }),
      true
    );
    ensureRowKey(newRow);
    markRowNew(newRow);
    appendDetailRow(detailRows, tabKey, newRow);
    return newRow;
  }

  function deleteDetailRow(masterId: number, tabKey: string, row: RowData, masterRowKey?: string) {
    if (!row) return false;
    const detailRows = resolveDetailRows(masterId, tabKey, masterRowKey);
    if (!detailRows) return false;
    const currentRow = findRowByIdentity(detailRows.rows, row);
    if (!currentRow) return false;

    if (!isPersistedRow(currentRow) || isRowNew(currentRow)) {
      clearRowChanges(currentRow);
      const idx = detailRows.rows.findIndex(candidate => isSameRowIdentity(candidate, currentRow));
      if (idx >= 0) detailRows.rows.splice(idx, 1);
      setDetailRows(detailRows.masterRowKey, tabKey, detailRows.rows);
    } else {
      markRowDeleted(currentRow);
      const currentRowKey = String(ensureRowKey(currentRow));
      forEachNestedDetailGridApi({
        masterGridApi,
        masterRowKey: detailRows.masterRowKey,
        tabKeys: [tabKey],
        callback: api => {
          const node = findDetailGridNode(api, currentRowKey);
          api?.refreshCells?.({
            rowNodes: node ? [node] : undefined,
            force: true
          });
          api?.redrawRows?.({
            rowNodes: node ? [node] : undefined
          });
        }
      });

      const activeApi = detailGridApisByTab?.value?.[tabKey];
      if (activeApi && activeMasterRowKey?.value === detailRows.masterRowKey) {
        const node = findDetailGridNode(activeApi, currentRowKey);
        activeApi?.refreshCells?.({
          rowNodes: node ? [node] : undefined,
          force: true
        });
        activeApi?.redrawRows?.({
          rowNodes: node ? [node] : undefined
        });
      }
    }

    return true;
  }

  function copyDetailRow(masterId: number, tabKey: string, sourceRow: RowData, masterRowKey?: string) {
    if (!sourceRow) return null;
    const detailRows = resolveDetailRows(masterId, tabKey, masterRowKey);
    if (!detailRows) return null;
    const fkColumn = detailFkColumnByTab.value[tabKey] || 'masterId';
    const detailPkColumn = detailPkColumnByTab.value[tabKey];
    const newRow = initRowData({ id: generateTempId(), [fkColumn]: masterId }, true);
    ensureRowKey(newRow);
    markRowNew(newRow);

    applyCopiedRowFields({
      sourceRow,
      targetRow: newRow,
      excludeFields: [detailPkColumn, fkColumn],
      clearFields: [detailPkColumn]
    });

    appendDetailRow(detailRows, tabKey, newRow);
    return newRow;
  }

  function normalizeIdMapping(raw?: Record<string, number> | null) {
    const mapping = new Map<number, number>();
    if (!raw) return mapping;
    for (const [key, value] of Object.entries(raw)) {
      const fromId = Number(key);
      const toId = Number(value);
      if (!Number.isNaN(fromId) && !Number.isNaN(toId)) {
        mapping.set(fromId, toId);
      }
    }
    return mapping;
  }

  function applyIdMapping(idMapping: Map<number, number>) {
    if (idMapping.size === 0) return;
    const api = masterGridApi.value as any;
    const masterPkField = masterPkColumn.value;

    api?.forEachNode?.((node: any) => {
      const row = node?.data;
      if (!row) return;
      const mapped = idMapping.get(Number(row.id));
      if (mapped) {
        row.id = mapped;
        if (masterPkField) {
          row[masterPkField] = mapped;
        }
      }
    });

    for (const [, tabData] of detailCache.entries()) {
      for (const [tabKey, rows] of Object.entries(tabData)) {
        const fkColumn = detailFkColumnByTab.value[tabKey] || 'masterId';
        const detailPkField = detailPkColumnByTab.value[tabKey];
        for (const row of rows) {
          const mappedRowId = idMapping.get(Number(row.id));
          if (mappedRowId) {
            row.id = mappedRowId;
            if (detailPkField) {
              row[detailPkField] = mappedRowId;
            }
          }
          const mappedFk = idMapping.get(Number(row[fkColumn]));
          if (mappedFk) row[fkColumn] = mappedFk;
        }
      }
    }
  }

  function buildRecordItem(row: RowData, tableCode: string, extraExcludeFields: string[] = []) {
    const rowChange = getRowChange(row);
    const status =
      rowChange?.status === 'deleted'
        ? 'deleted'
        : rowChange?.status === 'new'
          ? 'added'
          : rowChange?.status === 'updated'
            ? 'modified'
            : 'unchanged';

    const dirtyFields = rowChange?.fields || {};
    const excludeFields = new Set<string>(['masterId', 'id', ...extraExcludeFields.filter(Boolean)]);
    const data: Record<string, any> = { _tableCode: tableCode };

    if (status === 'added') {
      for (const [key, value] of Object.entries(row)) {
        if (!key.startsWith('_') && !excludeFields.has(key)) data[key] = value;
      }
    } else if (status === 'modified') {
      for (const field of Object.keys(dirtyFields)) {
        if (!excludeFields.has(field)) {
          data[field] = row[field];
        }
      }
    }

    const changes = Object.entries(dirtyFields)
      .filter(([field]) => !excludeFields.has(field))
      .map(([field, info]) => ({
        field,
        oldValue: info.originalValue,
        newValue: row[field],
        changeType: info.type
      }));

    return {
      id: row.id,
      status,
      data,
      changes: changes.length > 0 ? changes : undefined
    };
  }

  async function save() {
    if (isSaving.value) {
      notifyInfo('正在保存中，请稍候...');
      return;
    }

    isSaving.value = true;

    try {
      const dirtyMaster: RowData[] = [];
      const dirtyDetailByTab: Record<string, RowData[]> = {};

      const api = masterGridApi.value as any;
      api?.forEachNode?.((node: any) => {
        const row = node.data as RowData | undefined;
        if (row && hasRowChanges(row)) {
          dirtyMaster.push(row);
        }
      });

      for (const [, tabData] of detailCache.entries()) {
        for (const [tabKey, rows] of Object.entries(tabData)) {
          for (const row of rows) {
            if (hasRowChanges(row)) {
              if (!dirtyDetailByTab[tabKey]) dirtyDetailByTab[tabKey] = [];
              dirtyDetailByTab[tabKey].push(row);
            }
          }
        }
      }

      const saveStats = { successCount: 0, pendingApprovalCount: 0, errors: [] as string[] };
      if (dirtyMaster.length === 0 && !Object.values(dirtyDetailByTab).some(rows => rows.length > 0)) {
        notifyInfo('没有需要保存的数据');
        return;
      }

      const masterToValidate = dirtyMaster.filter(row => !isRowDeleted(row));
      if (masterToValidate.length > 0) {
        const masterResult = validateRows(masterToValidate, masterValidationRules.value, masterColumnMeta.value);
        if (!masterResult.valid) {
          notifyError(`主表校验失败:\n${formatValidationErrors(masterResult.errors)}`);
          return;
        }
      }

      for (const [tabKey, rows] of Object.entries(dirtyDetailByTab)) {
        const rowsToValidate = rows.filter(row => !isRowDeleted(row));
        if (rowsToValidate.length === 0) continue;
        const rules = detailValidationRulesByTab.value[tabKey] || [];
        const meta = detailColumnMetaByTab.value[tabKey] || [];
        const result = validateRows(rowsToValidate, rules, meta);
        if (!result.valid) {
          const tabTitle = pageConfig.value?.tabs?.find(tab => tab.key === tabKey)?.title || tabKey;
          notifyError(`${tabTitle} 校验失败:\n${formatValidationErrors(result.errors)}`);
          return;
        }
      }

      const masterIdsToSave = new Set<number>();
      for (const row of dirtyMaster) {
        if (row.id != null) masterIdsToSave.add(row.id);
      }

      for (const [masterRowKey, tabData] of detailCache.entries()) {
        const masterRow = getMasterRowByRowKey(masterRowKey);
        const masterId = masterRow?.id;
        if (masterId == null) continue;
        for (const rows of Object.values(tabData)) {
          if (rows.some(row => hasRowChanges(row))) {
            masterIdsToSave.add(masterId);
            break;
          }
        }
      }

      const savedMasterIds: number[] = [];
      const pendingMasterRowKeys = new Set<string>();
      const pendingAddedMasterRowKeys = new Set<string>();
      const masterReloadTargets = new Map<number, string>();
      const detailReloadTargets = new Map<number, string>();

      for (const masterId of masterIdsToSave) {
        const masterRow = getMasterRowById(masterId);
        if (!masterRow) continue;

        const detailsMap: Record<string, any[]> = {};
        const masterRowKey = resolveMasterRowKey(masterId);
        const cached = masterRowKey ? detailCache.get(masterRowKey) : undefined;
        let hasDirtyDetails = false;

        if (cached) {
          for (const tab of pageConfig.value?.tabs || []) {
            const tableCode = tab.tableCode || pageConfig.value?.detailTableCode;
            if (!tableCode) continue;
            const rows = cached[tab.key] || [];
            const dirtyRows = rows.filter(row => hasRowChanges(row));
            if (dirtyRows.length > 0) {
              hasDirtyDetails = true;
              const fkField = detailFkColumnByTab.value[tab.key] || 'masterId';
              detailsMap[tableCode] = dirtyRows.map(row => buildRecordItem(row, tableCode, [fkField]));
            }
          }
        }

        const paramsToSave = {
          pageCode,
          master: buildRecordItem(masterRow, pageConfig.value?.masterTableCode || ''),
          details: Object.keys(detailsMap).length > 0 ? detailsMap : undefined
        };

        const requestRowKey = ensureRowKey(masterRow);
        const payloadJson = JSON.stringify(paramsToSave);
        let pendingRequest = unconfirmedSaves.get(requestRowKey);
        if (pendingRequest && pendingRequest.payloadJson !== payloadJson) {
          saveStats.errors.push(`主表 ${masterId}: 上次保存结果尚未确认，当前内容已改变。请先核对审批记录和业务数据；不能将修改后的内容作为上次请求重发。`);
          continue;
        }
        if (!pendingRequest) {
          pendingRequest = { requestId: createDynamicSaveRequestId(), payloadJson };
          unconfirmedSaves.set(requestRowKey, pendingRequest);
        }
        const submittedParams: DynamicSaveParam = {
          ...JSON.parse(pendingRequest.payloadJson),
          requestId: pendingRequest.requestId
        };
        const { error, data } = await saveDynamicData(submittedParams);
        if (error) {
          const responseData = (error as any)?.response?.data;
          const confirmedFailure = responseData?.code != null && typeof responseData?.msg === 'string';
          if (confirmedFailure) unconfirmedSaves.delete(requestRowKey);
          const responseDetail = responseData?.data;
          const errorLines = [
            `主表 ${masterId}: ${responseData?.msg || (error as any)?.msg || error.message || '保存失败'}`
          ];
          if (responseDetail?.oraCode) errorLines.push(`ORA错误码: ${responseDetail.oraCode}`);
          if (responseDetail?.sql) errorLines.push(`报错SQL: ${responseDetail.sql}`);
          if (responseDetail?.rootCause) errorLines.push(`根因: ${responseDetail.rootCause}`);
          if (!confirmedFailure) errorLines.push('保存结果尚未确认，请先核对审批记录和业务数据。保持内容不变再次保存时，会沿用本次请求标识；不会自动重试。');
          saveStats.errors.push(errorLines.join('\n'));
          continue;
        }
        if (!data) {
          saveStats.errors.push(`主表 ${masterId}: 保存接口未返回结果，请先核对审批记录和业务数据；本次请求标识已保留。`);
          continue;
        }
        unconfirmedSaves.delete(requestRowKey);

        const mapping = normalizeIdMapping((data as any)?.idMapping);
        const backendMasterId = Number((data as any)?.masterId);
        const resolvedMasterId =
          !Number.isNaN(backendMasterId) && backendMasterId > 0
            ? backendMasterId
            : Number(mapping.get(masterId) ?? masterId);

        if (!mapping.has(masterId) && resolvedMasterId > 0 && resolvedMasterId !== masterId) {
          mapping.set(masterId, resolvedMasterId);
        }
        if (mapping.size > 0) {
          applyIdMapping(mapping);
        }

        const pendingApproval = Boolean(data.pendingApproval || data.committed === false);
        if (pendingApproval) {
          saveStats.successCount++;
          saveStats.pendingApprovalCount++;
          savedMasterIds.push(resolvedMasterId);
          pendingMasterRowKeys.add(requestRowKey);
          if (submittedParams.master.status === 'added') {
            // The reserved ID identifies an approval request; the new business row does not exist yet.
            pendingAddedMasterRowKeys.add(requestRowKey);
          } else {
            masterReloadTargets.set(resolvedMasterId, requestRowKey);
            if (hasDirtyDetails) detailReloadTargets.set(resolvedMasterId, requestRowKey);
          }
          continue;
        }

        const returnedMasterRow = (data as any)?.masterRow;
        if (returnedMasterRow && !isRowDeleted(masterRow)) {
          for (const [key, value] of Object.entries(returnedMasterRow)) {
            if (!key.startsWith('_')) {
              masterRow[key] = value;
            }
          }
        } else if (!isRowDeleted(masterRow)) {
          masterReloadTargets.set(resolvedMasterId, requestRowKey);
        }

        if (!isRowDeleted(masterRow) && resolvedMasterId > 0) {
          masterRow.id = resolvedMasterId;
          const masterPkField = masterPkColumn.value;
          if (masterPkField && masterRow[masterPkField] == null) {
            masterRow[masterPkField] = resolvedMasterId;
          }
        }

        saveStats.successCount++;
        savedMasterIds.push(resolvedMasterId);
        if (hasDirtyDetails && !isRowDeleted(masterRow)) {
          detailReloadTargets.set(resolvedMasterId, ensureRowKey(masterRow));
        }
      }

      const rowsToUpdate: RowData[] = [];
      const rowsToRemove: RowData[] = [];
      const touchedDetailKeys = new Set<string>();

      for (const masterId of savedMasterIds) {
        const masterRow = getMasterRowById(masterId);
        const masterRowKey = masterRow ? ensureRowKey(masterRow) : resolveMasterRowKey(masterId);
        const isPending = Boolean(masterRowKey && pendingMasterRowKeys.has(masterRowKey));
        const isPendingAdded = Boolean(masterRowKey && pendingAddedMasterRowKeys.has(masterRowKey));
        if (masterRow) {
          if (isPendingAdded || (isRowDeleted(masterRow) && !isPending)) {
            rowsToRemove.push(masterRow);
            clearRowChanges(masterRow);
          } else {
            clearRowChanges(masterRow);
            rowsToUpdate.push(masterRow);
          }
        }

        const cached = masterRowKey ? detailCache.get(masterRowKey) : undefined;
        if (cached && masterRowKey) {
          for (const [tabKey, rows] of Object.entries(cached)) {
            if (isPendingAdded) {
              rows.forEach(clearRowChanges);
              setDetailRows(masterRowKey, tabKey, []);
              continue;
            }
            cached[tabKey] = rows.filter(row => {
              if (isRowDeleted(row)) {
                clearRowChanges(row);
                return false;
              }
              clearRowChanges(row);
              return true;
            });
          }
          if (isPendingAdded) {
            detailCache.delete(masterRowKey);
          } else {
            touchedDetailKeys.add(masterRowKey);
          }
        }
        if (isPendingAdded && activeMasterRowKey?.value === masterRowKey) activeMasterRowKey.value = null;
      }

      const gridApi = masterGridApi.value as any;
      if (rowsToUpdate.length > 0) {
        gridApi?.applyServerSideTransaction?.({ route: [], update: rowsToUpdate });
      }
      if (rowsToRemove.length > 0) {
        gridApi?.applyServerSideTransaction?.({ route: [], remove: rowsToRemove });
      }

      for (const [masterId, masterRowKey] of masterReloadTargets.entries()) {
        await reloadMasterRow(masterId, masterRowKey);
      }

      for (const [masterId, masterRowKey] of detailReloadTargets.entries()) {
        await loadDetailData(masterId, masterRowKey);
        touchedDetailKeys.add(masterRowKey);
      }

      for (const masterRowKey of touchedDetailKeys) {
        const cached = detailCache.get(masterRowKey);
        if (!cached) continue;

        forEachNestedDetailGridApi({
          masterGridApi,
          masterRowKey,
          tabKeys: Object.keys(cached),
          callback: (api, tabKey) => {
            api.setGridOption?.('rowData', cached[tabKey]);
            api.refreshCells?.({ force: true });
          }
        });

        if (detailGridApisByTab?.value && activeMasterRowKey?.value === masterRowKey) {
          for (const [tabKey, rows] of Object.entries(cached)) {
            const detailApi = detailGridApisByTab.value[tabKey];
            detailApi?.setGridOption?.('rowData', rows);
            detailApi?.refreshCells?.({ force: true });
          }
        }
      }

      masterGridApi.value?.refreshCells({ force: true });

      const committedCount = saveStats.successCount - saveStats.pendingApprovalCount;
      if (saveStats.errors.length > 0) {
        const successText =
          saveStats.pendingApprovalCount > 0
            ? `保存 ${committedCount} 条，提交审批 ${saveStats.pendingApprovalCount} 条`
            : `成功 ${saveStats.successCount} 条`;
        notifyError(`${successText}，失败 ${saveStats.errors.length} 条\n${saveStats.errors.join('\n')}`);
      } else if (saveStats.pendingApprovalCount > 0) {
        if (committedCount > 0) {
          notifySuccess(`保存成功 ${committedCount} 条，提交审批 ${saveStats.pendingApprovalCount} 条，审批通过后生效`);
        } else {
          notifySuccess(`已提交审批 ${saveStats.pendingApprovalCount} 条，审批通过后生效`);
        }
      } else {
        notifySuccess('保存成功');
      }
    } finally {
      isSaving.value = false;
    }
  }

  return {
    isSaving,
    save,
    changeSet,
    rowStateApi,
    detailCache,
    clearAllCache,
    isLoadingMasterRows,
    isLoadingDetailRows,
    loadDetailData,
    getMasterRowByRowKey,
    getMasterRowById,
    resolveMasterRowKey,
    reloadMasterRow,
    createServerSideDataSource,
    routeMasterId,
    setRouteMasterId,
    setAdvancedConditions,
    clearAdvancedConditions,
    applyMasterPatch,
    applyDetailPatch,
    addMasterRow,
    deleteMasterRow,
    copyMasterRow,
    addDetailRow,
    deleteDetailRow,
    copyDetailRow
  };
}
