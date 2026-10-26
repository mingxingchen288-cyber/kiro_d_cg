import { type Ref, nextTick, ref } from 'vue';
import type { LookupRule } from '@/v3/composables/meta-v3/useMetaColumns';
import { type RowData, ensureRowKey } from '@/v3/logic/calc-engine';

type LookupDialogExpose = { open: () => void };

function joinLookupValues(values: unknown[]) {
  return values
    .map(value => String(value ?? '').trim())
    .filter(Boolean)
    .join(',');
}

function mergeMultipleLookupFillData(fillData: Record<string, any>[]) {
  const fieldMap = new Map<string, unknown[]>();

  for (const item of fillData) {
    for (const [field, value] of Object.entries(item || {})) {
      const list = fieldMap.get(field) || [];
      list.push(value);
      fieldMap.set(field, list);
    }
  }

  const patch: Record<string, string> = {};
  for (const [field, values] of fieldMap.entries()) {
    patch[field] = joinLookupValues(values);
  }
  return patch;
}

export function useLookupDialog(params: {
  commitMasterPatch: (params: {
    rowId: number | null,
    rowKey: string | null,
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
  masterLookupRules: Ref<LookupRule[]>;
  detailLookupRulesByTab: Ref<Record<string, LookupRule[]>>;
  isRowEditable?: (row: RowData) => boolean;
  isDetailRowEditable?: (row: RowData, tabKey: string) => boolean;
}) {
  const {
    commitMasterPatch,
    commitDetailPatch,
    masterLookupRules,
    detailLookupRulesByTab,
    isRowEditable,
    isDetailRowEditable
  } = params;

  const lookupDialogRef = ref<LookupDialogExpose | null>(null);
  const currentLookupRule = ref<LookupRule | null>(null);
  const currentLookupRowId = ref<number | null>(null);
  const currentLookupRowKey = ref<string | null>(null);
  const currentLookupRowData = ref<RowData | null>(null);
  const currentLookupCellValue = ref<any>(null);
  const currentLookupIsMaster = ref<boolean>(true);
  const currentLookupTabKey = ref<string>('');

  function resetLookupState() {
    currentLookupRule.value = null;
    currentLookupRowId.value = null;
    currentLookupRowKey.value = null;
    currentLookupRowData.value = null;
    currentLookupCellValue.value = null;
  }

  async function onMasterCellClicked(event: any) {
    if (event.node?.rowPinned) return;
    const field = event.colDef?.field;
    const rowData = event.data;
    if (!field || !rowData) return;

    const rule = masterLookupRules.value.find(r => r.columnName === field);
    if (!rule) return;

    if (isRowEditable && !isRowEditable(rowData) && !rule.noFillback) return;

    currentLookupRule.value = rule;
    currentLookupRowId.value = rowData.id;
    currentLookupRowKey.value = ensureRowKey(rowData);
    currentLookupRowData.value = rowData;
    currentLookupCellValue.value = rowData[field];
    currentLookupIsMaster.value = true;
    currentLookupTabKey.value = '';
    await nextTick();
    lookupDialogRef.value?.open();
  }

  async function onDetailCellClicked(event: any, _masterId: number, tabKey: string) {
    if (event.node?.rowPinned) return;
    const field = event.colDef?.field;
    const rowData = event.data;
    if (!field || !rowData) return;

    const rule = detailLookupRulesByTab.value[tabKey]?.find(r => r.columnName === field);
    if (!rule) return;

    if (isDetailRowEditable && !isDetailRowEditable(rowData, tabKey) && !rule.noFillback) return;

    currentLookupRule.value = rule;
    currentLookupRowId.value = rowData.id;
    currentLookupRowKey.value = ensureRowKey(rowData);
    currentLookupRowData.value = rowData;
    currentLookupCellValue.value = rowData[field];
    currentLookupIsMaster.value = false;
    currentLookupTabKey.value = tabKey;
    await nextTick();
    lookupDialogRef.value?.open();
  }

  async function onLookupSelect(fillData: Record<string, any> | Record<string, any>[]) {
    if (currentLookupRule.value?.noFillback) {
      resetLookupState();
      return;
    }

    const rowId = currentLookupRowId.value;
    const rowKey = currentLookupRowKey.value;
    if (rowId == null && !rowKey) return;
    const patch = Array.isArray(fillData) ? mergeMultipleLookupFillData(fillData) : fillData;

    if (currentLookupIsMaster.value) {
      await commitMasterPatch({
        rowId,
        rowKey,
        patch,
        changeType: 'user'
      });
    } else {
      const tabKey = currentLookupTabKey.value;
      commitDetailPatch({
        tabKey,
        rowId,
        rowKey,
        patch,
        changeType: 'user'
      });
    }

    resetLookupState();
  }

  function onLookupCancel() {
    resetLookupState();
  }

  return {
    lookupDialogRef,
    currentLookupRule,
    currentLookupRowId,
    currentLookupRowKey,
    currentLookupRowData,
    currentLookupCellValue,
    currentLookupIsMaster,
    currentLookupTabKey,
    onMasterCellClicked,
    onDetailCellClicked,
    onLookupSelect,
    onLookupCancel
  };
}
