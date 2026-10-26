import { request } from '../request';

/** 获取表元数据（原始，不含权限） */
export function fetchTableMetadata(tableCode: string) {
  return request<Api.Metadata.TableMetadata>({
    url: `/api/metadata/table/${tableCode}`
  });
}

/** 获取表元数据（合并权限） */
export function fetchTableMetadataWithPermission(tableCode: string, pageCode: string, gridKey?: string) {
  return request<Api.Metadata.TableMetadata>({
    url: `/api/metadata/table/${tableCode}/page/${pageCode}`,
    params: gridKey ? { gridKey } : undefined
  });
}

/** 获取页面组件树 */
export function fetchPageComponents(pageCode: string) {
  return request<Api.Metadata.PageComponent[]>({
    url: `/api/metadata/page/${pageCode}`
  });
}

/** 获取字典项 */
export function fetchDictItems(dictType: string) {
  return request<Api.Metadata.DictItem[]>({
    url: `/api/metadata/dict/${dictType}`
  });
}

/** 获取弹窗选择器配置 */
export function fetchLookupConfig(lookupCode: string) {
  return request<Api.Metadata.LookupConfig>({
    url: `/api/metadata/lookup/${lookupCode}`
  });
}
