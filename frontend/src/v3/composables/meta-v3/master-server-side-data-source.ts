import type { IServerSideGetRowsParams } from 'ag-grid-community';
import { type DynamicQueryCondition, searchDynamicData } from '@/service/api';
import { debugLog } from '@/v3/composables/meta-v3/debug';
import { buildConditionsFromFilterModel } from '@/v3/composables/meta-v3/grid-filter-conditions';
import { initRowData } from '@/v3/logic/calc-engine';

type QueryCondition = DynamicQueryCondition;

type CreateMasterServerSideDataSourceParams = {
  pageCode: string;
  getTableCode: () => string | undefined;
  getMasterPkColumn: () => string;
  getAdvancedConditions: () => QueryCondition[];
  notifyError: (message: string) => void;
  markMasterRowsLoading?: () => void;
};

export function createMasterServerSideDataSource(params: CreateMasterServerSideDataSourceParams) {
  const { pageCode, getTableCode, getMasterPkColumn, getAdvancedConditions, notifyError, markMasterRowsLoading } = params;

  return (options?: { tableCode?: string; pageSize?: number }) => {
    const tableCode = options?.tableCode || getTableCode();
    const pageSizeFallback = options?.pageSize || 100;
    if (!tableCode) return null;

    let pendingRequest: Promise<void> | null = null;
    let lastRequestTime = 0;
    const requestDebounceMs = 50;
    let cachedRowCount: number | undefined;
    let lastRequestKey = '';

    return {
      getRows: async (params: IServerSideGetRowsParams) => {
        const now = Date.now();
        if (now - lastRequestTime < requestDebounceMs && pendingRequest) {
          debugLog('ssrm debounce skip', { timeSinceLastRequest: now - lastRequestTime });
          return;
        }

        lastRequestTime = now;

        const request = params.request;
        const startRow = request.startRow ?? 0;
        const endRow = request.endRow ?? startRow + pageSizeFallback;
        const pageSize = Math.max(endRow - startRow, 1);
        const page = Math.floor(startRow / pageSize) + 1;

        const sortModel = request.sortModel ?? [];
        const sortField = sortModel[0]?.colId;
        const sortOrder = sortModel[0]?.sort;

        const filterModel = request.filterModel;
        const advancedConditions = getAdvancedConditions();
        const filterConditions = buildConditionsFromFilterModel(filterModel);
        const conditions = [...filterConditions, ...advancedConditions];

        const requestKey = JSON.stringify({
          filterModel,
          sortModel,
          advancedConditions
        });
        if (requestKey !== lastRequestKey) {
          lastRequestKey = requestKey;
          cachedRowCount = undefined;
        }

        debugLog('ssrm request', { page, pageSize, sortField, sortOrder, conditions });

        try {
          const requestPromise = searchDynamicData(tableCode, {
            pageCode,
            page,
            pageSize,
            sortField,
            sortOrder,
            conditions: conditions.length > 0 ? conditions : undefined
          });
          pendingRequest = requestPromise.then(() => {
            pendingRequest = null;
          });

          const { data, error } = await requestPromise;

          if (error) {
            params.fail();
            notifyError('加载主表数据失败');
            return;
          }

          const rows = (data?.list || []).map((row: any) => initRowData(row, false, getMasterPkColumn()));
          const total = data?.total;

          if (total != null && cachedRowCount === undefined) {
            cachedRowCount = total;
          }

          debugLog('ssrm response', { rowCount: rows.length, total });

          const successParams: any = { rowData: rows };
          if (startRow === 0 && cachedRowCount != null) {
            successParams.rowCount = cachedRowCount;
          }

          markMasterRowsLoading?.();
          params.success(successParams);
        } catch (_error) {
          params.fail();
          notifyError('加载主表数据失败');
        }
      }
    };
  };
}
