import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { computed, reactive, ref } from 'vue';
import { defineStore } from 'pinia';
import { useAuthStore } from '../auth';

export interface SqlTraceSqlDetail {
  seqNo: number;
  sqlType: string;
  sqlText: string;
  costMs: number;
  affectedRows?: number | null;
  status: 'SUCCESS' | 'FAILED';
  errorMsg?: string | null;
}

export interface SqlTraceSession {
  traceId: string;
  method: string;
  path: string;
  queryString?: string | null;
  userName?: string | null;
  startTime: string;
  endTime?: string | null;
  costMs: number;
  responseStatus: number;
  errorMsg?: string | null;
  sqlDetails: SqlTraceSqlDetail[];
}

export interface SqlTraceRequestRecord {
  id: string;
  traceId?: string;
  method: string;
  url: string;
  page: string;
  params?: unknown;
  data?: unknown;
  status?: number;
  startedAt: number;
  costMs?: number;
  errorMsg?: string;
}

type TraceConfig = InternalAxiosRequestConfig & {
  sqlTraceRecordId?: string;
  sqlTraceStartedAt?: number;
};

const MAX_RECORDS = 80;
const TRACE_ID_HEADER = 'x-sql-trace-id';

function getHeader(response: AxiosResponse | undefined, name: string) {
  if (!response?.headers) return undefined;
  const headers = response.headers as Record<string, string | undefined> & {
    get?: (key: string) => string | null | undefined;
  };
  return headers.get?.(name) || headers[name] || headers[name.toLowerCase()];
}

function clonePayload(payload: unknown) {
  if (payload == null) return undefined;
  if (typeof payload === 'string') {
    try {
      return JSON.parse(payload);
    } catch {
      return payload;
    }
  }
  try {
    return JSON.parse(JSON.stringify(payload));
  } catch {
    return payload;
  }
}

function getRequestUrl(config: InternalAxiosRequestConfig) {
  const url = config.url || '';
  if (!config.baseURL || url.startsWith('http')) return url;
  return `${config.baseURL.replace(/\/$/, '')}/${url.replace(/^\//, '')}`;
}

function isDebugOrAuthRequest(url: string) {
  return (
    url.includes('/debug/sql-traces') ||
    url.includes('/auth/login') ||
    url.includes('/auth/refreshToken') ||
    url.includes('/auth/getUserInfo')
  );
}

export const useSqlTraceStore = defineStore('sql-trace-store', () => {
  const records = ref<SqlTraceRequestRecord[]>([]);
  const selectedRecordId = ref<string | null>(null);
  const drawerVisible = ref(false);
  const enabled = ref(true);
  const sessions = reactive<Record<string, SqlTraceSession | null>>({});

  const authStore = useAuthStore();

  const isAdmin = computed(() => {
    return authStore.userInfo.userName === 'admin';
  });

  const selectedRecord = computed(() => records.value.find(item => item.id === selectedRecordId.value) || null);

  function shouldTrace(config: InternalAxiosRequestConfig) {
    if (!enabled.value || !isAdmin.value) return false;
    return !isDebugOrAuthRequest(config.url || '');
  }

  function beforeRequest(config: InternalAxiosRequestConfig) {
    if (!shouldTrace(config)) return;

    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const startedAt = Date.now();
    const record: SqlTraceRequestRecord = {
      id,
      method: (config.method || 'GET').toUpperCase(),
      url: getRequestUrl(config),
      page: `${window.location.pathname}${window.location.search}`,
      params: clonePayload(config.params),
      data: clonePayload(config.data),
      startedAt
    };

    records.value.unshift(record);
    records.value = records.value.slice(0, MAX_RECORDS);
    selectedRecordId.value ||= id;

    const traceConfig = config as TraceConfig;
    traceConfig.sqlTraceRecordId = id;
    traceConfig.sqlTraceStartedAt = startedAt;
    Object.assign(config.headers, {
      'X-Sql-Trace': '1',
      'X-Sql-Trace-Page': record.page
    });
  }

  function afterResponse(response: AxiosResponse | undefined, errorMsg?: string) {
    const config = response?.config as TraceConfig | undefined;
    const id = config?.sqlTraceRecordId;
    if (!id) return;

    const record = records.value.find(item => item.id === id);
    if (!record) return;

    record.status = response?.status;
    record.costMs = Date.now() - (config?.sqlTraceStartedAt || record.startedAt);
    record.errorMsg = errorMsg;

    const traceId = getHeader(response, TRACE_ID_HEADER);
    if (traceId) {
      record.traceId = traceId;
      selectedRecordId.value = id;
    }
  }

  function afterError(config: InternalAxiosRequestConfig | undefined, errorMsg?: string) {
    const traceConfig = config as TraceConfig | undefined;
    const id = traceConfig?.sqlTraceRecordId;
    if (!id) return;

    const record = records.value.find(item => item.id === id);
    if (!record) return;

    record.costMs = Date.now() - (traceConfig?.sqlTraceStartedAt || record.startedAt);
    record.errorMsg = errorMsg;
  }

  function openDrawer(recordId?: string) {
    if (recordId) selectedRecordId.value = recordId;
    drawerVisible.value = true;
  }

  function clearRecords() {
    records.value = [];
    selectedRecordId.value = null;
    Object.keys(sessions).forEach(key => {
      delete sessions[key];
    });
  }

  function setSession(traceId: string, session: SqlTraceSession | null) {
    sessions[traceId] = session;
  }

  return {
    records,
    selectedRecordId,
    selectedRecord,
    drawerVisible,
    enabled,
    sessions,
    isAdmin,
    beforeRequest,
    afterResponse,
    afterError,
    openDrawer,
    clearRecords,
    setSession
  };
});
