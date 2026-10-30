/**
 * 平台后端的 HTTP 客户端（C09 第 1 节）：会话 Cookie 由浏览器带上；写请求（POST、PUT、DELETE，登录除外）带 X-CSRF-Token；
 * 后台请求带 `X-Background-Request: 1`；错误体按 C03 第 1 节严格检查（contracts 的 parseErrorResponse）。
 * 实现 C11 的 `HttpClient`；外壳再在外面加会话处理（modules/shell/http.ts）后交给各模块。
 */
import { getServiceBaseURL } from '@/utils/service';
import { networkError, parseErrorResponse } from '@/contracts/errors';
import type { HttpClient, HttpRequestOptions } from '@/contracts/shell';

const isHttpProxy = import.meta.env.DEV && import.meta.env.VITE_HTTP_PROXY === 'Y';

/**
 * 后端服务地址。开发服务器上为代理前缀（`VITE_HTTP_PROXY=Y`，代理到 `VITE_SERVICE_BASE_URL`）或 `VITE_SERVICE_BASE_URL`；
 * 构建产物由后端以静态文件提供，与 `/api`、`/ws` 同源（T-AS-7），为页面的 origin。
 */
const baseURL = import.meta.env.DEV ? getServiceBaseURL(import.meta.env, isHttpProxy).baseURL : window.location.origin;

/** 后端服务地址（开发时为代理前缀，构建产物为页面的 origin） */
export const serviceBaseURL = baseURL;

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

function urlOf(path: string, options?: HttpRequestOptions) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options?.query ?? {})) {
    if (value !== null && value !== undefined) query.set(key, String(value));
  }
  const text = query.toString();
  return `${baseURL}${path}${text ? `?${text}` : ''}`;
}

async function json<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** `csrfToken` 返回当前的 CSRF 令牌（登录响应或 `/api/me` 的 `csrfToken`） */
export function createPlatformHttp(csrfToken: () => string): HttpClient {
  async function send(
    method: Method,
    path: string,
    { body, options }: { body?: unknown; options?: HttpRequestOptions } = {}
  ): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && path !== '/api/auth/login') headers['X-CSRF-Token'] = csrfToken();
    if (options?.background) headers['X-Background-Request'] = '1';
    let response: Response;
    try {
      response = await fetch(urlOf(path, options), {
        method,
        headers,
        credentials: 'same-origin',
        body: body === undefined ? undefined : JSON.stringify(body)
      });
    } catch {
      throw networkError();
    }
    if (!response.ok) throw parseErrorResponse(response.status, await response.text());
    return response;
  }

  return {
    get: async (path, options) => json(await send('GET', path, { options })),
    post: async (path, body, options) => json(await send('POST', path, { body, options })),
    put: async (path, body, options) => json(await send('PUT', path, { body, options })),
    delete: async (path, options) => json(await send('DELETE', path, { options })),
    download: async (path, body, options) => (await send('POST', path, { body, options })).blob()
  };
}
