/**
 * 自定义导出（FP-19）：主表右键菜单的"自定义导出"子菜单、导出请求、下载文件名和浏览器下载。
 * 对应旧系统 `cost-web/src/v3/composables/meta-v3/useGridContextMenu.ts` 第 367–406 行（子菜单）、
 * `useCustomExport.ts`（导出当前、导出所有的条件）、`service/api/export-config.ts`（文件名、下载）。
 */
import type { ExportList, ExportRequest, ListRequest } from '../../contracts/http';

/** 右键菜单中子菜单的名称（旧系统 LABEL_CUSTOM_EXPORT） */
export const EXPORT_MENU = '自定义导出';

/** 响应头中取不到文件名时用的文件名（旧系统 executeCustomExport 的 fallback） */
export const FALLBACK_FILE_NAME = 'export.xlsx';

export type ExportScope = 'current' | 'all';

export interface ExportMenuItem {
  label: string;
  exportCode: string;
  scope: ExportScope;
}

/**
 * 子菜单的项：每个可用的导出配置两项，"<导出名称> - 导出当前"、"<导出名称> - 导出所有"，按接口给出的顺序
 * （旧系统 buildCustomExportSubMenu）。没有可用的导出配置时为空，菜单中不出现"自定义导出"。
 */
export function exportMenuItems(items: ExportList['items']): ExportMenuItem[] {
  return items.flatMap(item => [
    { label: `${item.name} - 导出当前`, exportCode: item.exportCode, scope: 'current' as const },
    { label: `${item.name} - 导出所有`, exportCode: item.exportCode, scope: 'all' as const }
  ]);
}

/**
 * 按导出配置导出的请求（C09 第 4 节，`mode: config`）：导出当前带主表当前列表请求的筛选、高级查询和排序；
 * 导出所有都不带（旧系统 all 时不取筛选和排序；后端 all 时也会按 `sortModel` 排序，所以排序同样不带）。
 * 导出不分页，`startRow`、`endRow` 写 0。
 */
export function exportRequest(exportCode: string, scope: ExportScope, current: ListRequest | null): ExportRequest {
  const request: ListRequest = { startRow: 0, endRow: 0 };
  if (scope === 'current' && current) {
    if (current.sortModel) request.sortModel = current.sortModel;
    if (current.filterModel) request.filterModel = current.filterModel;
    if (current.advanced) request.advanced = current.advanced;
  }
  return { mode: 'config', exportCode, scope, request };
}

/**
 * 下载用的文件名：取响应头 `Content-Disposition` 的 `filename*=UTF-8''…`（或 `filename=…`）并解码，解码失败用原文；
 * 没有这个头或取不到时为 export.xlsx。与旧系统 parseFileName 用同一个正则。
 */
export function fileNameOf(contentDisposition: string | null): string {
  if (!contentDisposition) return FALLBACK_FILE_NAME;
  const match = /filename\*?=(?:UTF-8''|"?)([^";]+)/i.exec(contentDisposition);
  if (!match?.[1]) return FALLBACK_FILE_NAME;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

/** 浏览器下载：a 标签 + object URL（旧系统 executeCustomExport 第 102–110 行） */
export function saveFile(blob: Blob, fileName: string) {
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(link.href);
}
