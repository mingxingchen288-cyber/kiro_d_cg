import type { Ref } from 'vue';
import { useLookupDialog } from '@/v3/composables/meta-v3/useLookupDialog';
import { buildCellEditableCallback } from '@/v3/composables/meta-v3/usePageRules';
import type { RowStateApi } from '@/v3/composables/meta-v3/useWorkingSetStore';
import type { RuntimeFeatures } from './types';

type RuntimeLookupMeta = {
  masterCellEditableRules?: Ref<any[]>;
  masterRowEditableRules?: Ref<any[]>;
  masterLookupRules: Ref<any[]>;
  detailLookupRulesByTab: Ref<Record<string, any[]>>;
};

type RuntimeLookupOptions = {
  resolvedFeatures: Ref<Required<RuntimeFeatures>>;
  meta: RuntimeLookupMeta;
  rowStateApi: RowStateApi;
  commitMasterPatch: (params: {
    rowId: number | null;
    rowKey: string | null;
    patch: Record<string, any>;
    changeType?: 'user' | 'calc';
  }) => Promise<any>;
  commitDetailPatch: (params: {
    masterId?: number | null;
    tabKey: string;
    rowId: number | null;
    rowKey: string | null;
    patch: Record<string, any>;
    changeType?: 'user' | 'calc';
  }) => any;
};

function createMasterRowEditableChecker(meta: RuntimeLookupMeta, rowStateApi: RowStateApi) {
  return (row: any) => {
    const cellRules = meta.masterCellEditableRules?.value || [];
    const rowRules = meta.masterRowEditableRules?.value || [];
    if (cellRules.length === 0 && rowRules.length === 0) return true;
    const callback = buildCellEditableCallback(cellRules, rowRules);
    return callback ? callback({ data: row, colDef: {}, context: { rowStateApi } }) : true;
  };
}

export function useRuntimeLookup(options: RuntimeLookupOptions) {
  const { resolvedFeatures, meta, ...lookupOptions } = options;
  const isRowEditable = createMasterRowEditableChecker(meta, options.rowStateApi);
  const {
    onMasterCellClicked,
    onDetailCellClicked,
    onLookupSelect,
    onLookupCancel,
    ...lookupState
  } = useLookupDialog({
    ...lookupOptions,
    masterLookupRules: meta.masterLookupRules,
    detailLookupRulesByTab: meta.detailLookupRulesByTab,
    isRowEditable
  });

  return {
    ...lookupState,
    onMasterCellClicked: (event: any) => {
      if (!resolvedFeatures.value.lookup) return;
      onMasterCellClicked(event);
    },
    onDetailCellClicked: (event: any, masterId: number, tabKey: string) => {
      if (!resolvedFeatures.value.lookup) return;
      onDetailCellClicked(event, masterId, tabKey);
    },
    onLookupSelect: (fillData: Record<string, any> | Record<string, any>[]) => {
      if (!resolvedFeatures.value.lookup) return;
      onLookupSelect(fillData);
    },
    onLookupCancel: () => {
      if (!resolvedFeatures.value.lookup) return;
      onLookupCancel();
    }
  };
}
