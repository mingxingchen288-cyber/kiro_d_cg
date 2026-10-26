import type { Ref, ShallowRef } from 'vue';
import type { GridApi } from 'ag-grid-community';

export function resolveDetailGridTabKey(detailGridId: string | undefined, tabKeys: string[]) {
  return tabKeys.find(tabKey => detailGridId?.includes(tabKey));
}

export function forEachNestedDetailGridApi(params: {
  masterGridApi: ShallowRef<GridApi | null>;
  masterRowKey: string;
  tabKeys: string[];
  callback: (api: any, tabKey: string) => void;
}) {
  const { masterGridApi, masterRowKey, tabKeys, callback } = params;
  const secondLevelInfo = masterGridApi.value?.getDetailGridInfo(`detail_${masterRowKey}`);
  if (!secondLevelInfo?.api) return;

  secondLevelInfo.api.forEachDetailGridInfo((detailInfo: any) => {
    if (!detailInfo?.api) return;
    const tabKey = resolveDetailGridTabKey(detailInfo.id, tabKeys);
    if (tabKey) {
      callback(detailInfo.api, tabKey);
    }
  });
}

export function forEachDetailGridApi(params: {
  masterGridApi: ShallowRef<GridApi | null>;
  detailGridApisByTab?: Ref<Record<string, any>>;
  masterRowKey: string;
  tabKey: string;
  callback: (api: any) => void;
}) {
  const { masterGridApi, detailGridApisByTab, masterRowKey, tabKey, callback } = params;

  forEachNestedDetailGridApi({
    masterGridApi,
    masterRowKey,
    tabKeys: [tabKey],
    callback: api => callback(api)
  });

  const tabApi = detailGridApisByTab?.value?.[tabKey];
  if (tabApi) {
    callback(tabApi);
  }
}
