import { getAuthorization } from '@/service/request/shared';
import { getServiceBaseURL } from '@/utils/service';
import { request } from '../request';

export type CustomExportConfig = {
  id: number;

  exportCode: string;

  exportName: string;

  pageCode: string;

  displayOrder?: number;
};

export type QueryCondition = {
  field: string;

  operator: string;

  value: any;

  value2?: any;
};

export type CustomExportMode = 'all' | 'current';

export type CustomExportSort = {
  field: string;

  order?: 'asc' | 'desc' | string;
};

export type CustomExportRequest = {
  mode: CustomExportMode;

  conditions?: QueryCondition[];

  sorts?: CustomExportSort[];
};

const isHttpProxy = import.meta.env.DEV && import.meta.env.VITE_HTTP_PROXY === 'Y';

const { baseURL } = getServiceBaseURL(import.meta.env, isHttpProxy);

function parseFileName(contentDisposition: string | null, fallback: string) {
  if (!contentDisposition) return fallback;

  const match = /filename\*?=(?:UTF-8''|"?)([^";]+)/i.exec(contentDisposition);

  if (!match || !match[1]) return fallback;

  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

export function fetchCustomExportConfigs(pageCode: string) {
  return request<CustomExportConfig[]>({
    url: `/api/export-config/custom/${pageCode}`
  });
}

export async function executeCustomExport(exportCode: string, payload: CustomExportRequest) {
  const Authorization = getAuthorization();

  const response = await fetch(`${baseURL}/api/export-config/custom/${exportCode}/export`, {
    method: 'POST',

    headers: {
      'Content-Type': 'application/json',

      ...(Authorization ? { Authorization } : {})
    },

    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    let message = 'export failed';

    try {
      const data = await response.json();

      if (data?.msg) message = data.msg;
    } catch {
      // ignore
    }

    throw new Error(message);
  }

  const blob = await response.blob();

  const fallback = 'export.xlsx';

  const filename = parseFileName(response.headers.get('content-disposition'), fallback);

  const link = document.createElement('a');

  link.href = URL.createObjectURL(blob);

  link.download = filename;

  link.click();

  URL.revokeObjectURL(link.href);
}
