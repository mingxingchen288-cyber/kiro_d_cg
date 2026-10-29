/**
 * 平台后端的 HTTP 客户端（C09 第 1 节）：会话 Cookie 由浏览器带上；写请求（POST、PUT、DELETE，登录除外）带 X-CSRF-Token；
 * 后台请求带 `X-Background-Request: 1`；错误体按 C03 第 1 节严格检查（contracts 的 parseErrorResponse）。
 * 实现 C11 的 `HttpClient`；外壳的登录和 /api/me 也经它调用。
 */
import { sessionStg } from '@/utils/storage';
import { getServiceBaseURL } from '@/utils/service';
import { createPlatformApi } from '@/contracts/api';
import { networkError, parseErrorResponse } from '@/contracts/errors';
import type { CurrentUser } from '@/contracts/http';
import type { HttpClient, HttpRequestOptions } from '@/contracts/shell';

export type { CurrentUser };

const isHttpProxy = import.meta.env.DEV && import.meta.env.VITE_HTTP_PROXY === 'Y';
const { baseURL } = getServiceBaseURL(import.meta.env, isHttpProxy);

/** 后端服务地址（开发时为代理前缀） */
export const serviceBaseURL = baseURL;

/** 登录响应和 /api/me 中的 csrfToken，存在会话存储里，与旧外壳判断是否登录用的 token 是同一项 */
function csrfToken() {
  return sessionStg.get('token') || '';
}

type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

function urlOf(path: string, options?: HttpRequestOptions) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options?.query ?? {})) {
    if (value !== null && value !== undefined) query.set(key, String(value));
  }
  const text = query.toString();
  return `${baseURL}${path}${text ? `?${text}` : ''}`;
}

async function send(method: Method, path: string, body: unknown, options?: HttpRequestOptions): Promise<Response> {
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

async function json<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const platformHttp: HttpClient = {
  get: async (path, options) => json(await send('GET', path, undefined, options)),
  post: async (path, body, options) => json(await send('POST', path, body, options)),
  put: async (path, body, options) => json(await send('PUT', path, body, options)),
  delete: async (path, options) => json(await send('DELETE', path, undefined, options)),
  download: async (path, body, options) => (await send('POST', path, body, options)).blob()
};

const api = createPlatformApi(platformHttp);

export function login(username: string, password: string) {
  return api.login(username, password);
}

export function me() {
  return api.me();
}
