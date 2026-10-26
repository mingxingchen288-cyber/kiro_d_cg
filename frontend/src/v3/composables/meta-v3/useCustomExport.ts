import { ref } from 'vue';
import type { Ref } from 'vue';
import {
  type CustomExportConfig,
  type CustomExportMode,
  type CustomExportSort,
  executeCustomExport,
  fetchCustomExportConfigs
} from '@/service/api/export-config';
import { buildConditionsFromFilterModel } from '@/v3/composables/meta-v3/grid-filter-conditions';

type NotifyFn = (message: string) => void;

type SortModelItem = { colId?: string; sort?: 'asc' | 'desc' };

const LABEL_EXPORT_OK = '导出已开始';
const LABEL_EXPORT_FAIL = '导出失败';

function buildSorts(sortModel: SortModelItem[] | null | undefined): CustomExportSort[] {
  if (!sortModel || sortModel.length === 0) return [];
  return sortModel
    .filter(item => item?.colId && item?.sort)
    .map(item => ({ field: item.colId as string, order: item.sort as CustomExportSort['order'] }));
}

export function useCustomExport(params: {
  pageCode: string;
  masterGridApi: { value: any | null };
  notifyInfo: NotifyFn;
  notifyError: NotifyFn;
  notifySuccess: NotifyFn;
}) {
  const { pageCode, masterGridApi, notifyInfo, notifyError, notifySuccess } = params;
  const customExportConfigs = ref<CustomExportConfig[]>([]);
  const loaded = ref(false);

  async function loadConfigs() {
    if (loaded.value) return;
    loaded.value = true;
    const { data, error } = await fetchCustomExportConfigs(pageCode);
    if (error) {
      notifyError(error.message || LABEL_EXPORT_FAIL);
      return;
    }
    customExportConfigs.value = data || [];
  }

  async function runExport(exportCode: string, mode: CustomExportMode) {
    const api = masterGridApi.value;
    const filterModel = mode === 'current' ? api?.getFilterModel?.() : null;
    const sortModel = mode === 'current' ? api?.getSortModel?.() : null;
    const conditions = mode === 'current' ? buildConditionsFromFilterModel(filterModel) : [];
    const sorts = mode === 'current' ? buildSorts(sortModel) : [];

    notifyInfo(LABEL_EXPORT_OK);
    try {
      await executeCustomExport(exportCode, {
        mode,
        conditions: conditions.length > 0 ? conditions : undefined,
        sorts: sorts.length > 0 ? sorts : undefined
      });
      notifySuccess(LABEL_EXPORT_OK);
    } catch (error: any) {
      notifyError(error?.message || LABEL_EXPORT_FAIL);
    }
  }

  loadConfigs();

  return {
    customExportConfigs,
    executeCustomExport: runExport
  };
}
