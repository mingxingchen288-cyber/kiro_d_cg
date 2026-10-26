import type { Ref, ShallowRef } from 'vue';
import type { GridApi } from 'ag-grid-community';
import { executePageRuleAction } from '@/service/api/dynamic';
import type { ParsedPageConfig } from '@/v3/logic/calc-engine';

export type RuntimeActionRefreshMode = 'all' | 'row' | 'detail' | 'none';

export type RuntimeActionOptions = {
  data?: Record<string, any>;
  selectedRow?: Record<string, any> | null;
  refreshMode?: RuntimeActionRefreshMode;
  componentKey?: string;
};

export type RuntimeActionHandler = (context: {
  actionCode: string;
  runtime: any;
  options?: RuntimeActionOptions;
}) => Promise<void> | void;

type RuntimeActionsParams = {
  pageCode: string;
  notifyError: (message: string) => void;
  notifySuccess: (message: string) => void;
  getRuntime: () => any;
  masterGridApi: ShallowRef<GridApi | null>;
  activeMasterRowKey: Ref<string | null>;
  pageConfig: ShallowRef<ParsedPageConfig | null>;
  data: {
    detailCache?: Map<string, any>;
    getMasterRowByRowKey: (rowKey: string) => any;
    reloadMasterRow: (rowId: number, rowKey?: string) => Promise<any>;
    loadDetailData: (masterId: number, rowKey: string) => Promise<void>;
    clearAllCache: () => void;
  };
};

export function useRuntimeActions(params: RuntimeActionsParams) {
  const actionHandlers = new Map<string, RuntimeActionHandler>();

  function registerActionHandler(actionCode: string, handler: RuntimeActionHandler) {
    if (!actionCode || typeof handler !== 'function') return;
    actionHandlers.set(actionCode, handler);
  }

  function resolveActionHandler(actionCode: string): RuntimeActionHandler | null {
    return actionHandlers.get(actionCode) || null;
  }

  async function executeAction(actionCode: string, options?: RuntimeActionOptions) {
    if (!actionCode) return;

    const handler = resolveActionHandler(actionCode);
    if (handler) {
      try {
        await handler({ actionCode, runtime: params.getRuntime(), options });
      } catch (error: any) {
        params.notifyError(error?.message || 'Action failed');
      }
      return;
    }

    const { data, error } = await executePageRuleAction(params.pageCode, {
      componentKey: options?.componentKey,
      actionCode,
      data: options?.data
    });
    if (error) {
      params.notifyError('Action failed');
      return;
    }

    params.notifySuccess(data?.vars?.message || '执行成功');

    const refreshMode = options?.refreshMode ?? 'detail';
    if (refreshMode === 'none') {
      return;
    }

    const currentRow =
      options?.selectedRow ??
      (params.activeMasterRowKey.value ? params.data.getMasterRowByRowKey(params.activeMasterRowKey.value) : null);
    const rowId = currentRow?.id;
    const rowKey = currentRow?._rowKey ?? params.activeMasterRowKey.value;
    const hasDetailTabs = (params.pageConfig.value?.tabs?.length || 0) > 0;

    const syncCurrentContext = async () => {
      if (rowId === null || rowId === undefined || !rowKey) return;
      await params.data.reloadMasterRow(rowId, rowKey);
      if (hasDetailTabs) {
        await params.data.loadDetailData(rowId, rowKey);
      }
    };

    const restoreSelection = () => {
      const api = params.masterGridApi.value as any;
      setTimeout(() => {
        api?.forEachNode?.((node: any) => {
          if (node.data?.id === rowId) {
            node.setSelected(true);
          }
        });
      }, 100);
    };

    if (refreshMode === 'all') {
      params.data.clearAllCache();
    } else if (rowKey && params.data.detailCache) {
      params.data.detailCache.delete(rowKey);
    }

    if (refreshMode === 'detail') {
      await syncCurrentContext();
      return;
    }

    if (refreshMode === 'row') {
      await syncCurrentContext();
      restoreSelection();
      return;
    }

    params.masterGridApi.value?.refreshServerSide?.({ purge: false });
    await syncCurrentContext();
    restoreSelection();
  }

  return {
    registerActionHandler,
    resolveActionHandler,
    executeAction
  };
}
