/**
 * C09 的前端模拟实现（CT-04）：每个接口默认返回 C09 的样例（samples.ts）。
 * 测试可以按（方法、路径模板）预设返回值或错误，并读取收到的调用。
 */
import { PlatformError } from '../errors';
import type { DownloadedFile, HttpClient, HttpRequestOptions } from '../shell';
import * as s from './samples';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface FakeCall {
  method: HttpMethod;
  path: string;
  /** 路径模板中参数的值，例如 `/api/pages/:pageCode/view` 的 pageCode */
  params: Record<string, string>;
  body: unknown;
  options: HttpRequestOptions | undefined;
}

export type FakeHandler = (call: FakeCall) => unknown;

interface Route {
  method: HttpMethod;
  template: string;
  regex: RegExp;
  names: string[];
  handler: FakeHandler;
  /** 预设错误还剩几次；为 undefined 时不是错误 */
  failTimes?: number;
}

function compile(template: string) {
  const names: string[] = [];
  const source = template.replace(/:(\w+)/g, (_, name: string) => {
    names.push(name);
    return '([^/]+)';
  });
  return { regex: new RegExp(`^${source}$`), names };
}

const clone = <T>(value: T): T => structuredClone(value);
const sample = (value: unknown) => () => clone(value);
const noContent = () => undefined;

/**
 * 导出接口返回的文件（C11 v2 的 `DownloadedFile`）：模拟实现给出一个空的 xlsx 类型文件，`Content-Disposition` 的写法同后端
 * （`attachment; filename*=UTF-8''<百分号编码的文件名>`），文件名为 export.xlsx；测试可以用 `on` 预设别的文件和响应头。
 */
const exportFile = (): DownloadedFile => ({
  blob: new Blob([], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
  contentDisposition: "attachment; filename*=UTF-8''export.xlsx"
});

/** C09 各接口的默认响应 */
const DEFAULTS: Array<[HttpMethod, string, FakeHandler]> = [
  ['POST', '/api/auth/login', sample(s.loginResponseSample)],
  ['POST', '/api/auth/role', sample(s.selectRoleResponseSample)],
  ['POST', '/api/auth/logout', noContent],
  ['GET', '/api/me', sample(s.meResponseSample)],
  ['GET', '/api/admin/accounts', sample(s.accountListSample)],
  ['POST', '/api/admin/accounts', sample(s.accountSample)],
  ['PUT', '/api/admin/accounts/:userId', sample(s.accountSample)],
  ['POST', '/api/admin/accounts/:userId/password', noContent],
  ['GET', '/api/admin/departments', sample(s.departmentListSample)],
  ['GET', '/api/pages/:pageCode/view', sample(s.pageViewSample)],
  ['GET', '/api/rules-packs/:packId/:version', sample(s.rulesPackSample)],
  ['GET', '/api/config/items', sample(s.configItemListSample)],
  ['GET', '/api/config/items/:type/:key', sample(s.configItemSample)],
  ['PUT', '/api/config/items/:type/:key', sample(s.configSaveResponseSample)],
  ['DELETE', '/api/config/items/:type/:key', noContent],
  ['POST', '/api/config/validate', sample(s.configValidateResponseSample)],
  ['POST', '/api/config/wizard/columns', sample(s.wizardColumnsResponseSample)],
  ['POST', '/api/config/schema/columns', sample(s.schemaColumnsResponseSample)],
  // C09 没有写生成接口的响应体，模拟实现返回空
  ['POST', '/api/config/wizard/generate', noContent],
  ['POST', '/api/pages/:pageCode/rows', sample(s.listResponseSample)],
  ['POST', '/api/pages/:pageCode/rows/by-keys', sample(s.rowsByKeysResponseSample)],
  ['GET', '/api/pages/:pageCode/records/:recordKey', sample(s.recordResponseSample)],
  ['POST', '/api/lookups/:lookupCode/search', sample(s.lookupSearchResponseSample)],
  ['GET', '/api/dicts/:dictType', sample(s.dictResponseSample)],
  ['GET', '/api/pages/:pageCode/personal', sample(s.personalConfigSample)],
  ['PUT', '/api/pages/:pageCode/personal', call => clone(call.body)],
  ['GET', '/api/pages/:pageCode/exports', sample(s.exportListSample)],
  ['POST', '/api/pages/:pageCode/export', exportFile],
  ['POST', '/api/commands', sample(s.resultSavedSample)],
  ['GET', '/api/approvals', sample(s.approvalListSample)],
  ['GET', '/api/approvals/:approvalId', sample(s.approvalDetailSample)],
  ['POST', '/api/approvals/:approvalId/preview', sample(s.previewResponseSample)],
  ['POST', '/api/approvals/:approvalId/pass', sample(s.approvalProcessedSample)],
  ['POST', '/api/approvals/:approvalId/reject', sample(s.approvalProcessedSample)],
  ['POST', '/api/approvals/:approvalId/withdraw', sample(s.approvalProcessedSample)],
  ['GET', '/api/inbox', sample(s.inboxListSample)],
  ['POST', '/api/inbox/:deliveryId/read', noContent],
  ['GET', '/api/admin/deliveries', sample(s.deliveryListSample)],
  ['POST', '/api/admin/deliveries/:deliveryId/requeue', noContent],
  ['GET', '/api/admin/command-review', sample(s.commandReviewListSample)],
  ['PUT', '/api/admin/command-review', noContent],
  ['GET', '/health', sample(s.healthSample)]
];

export class FakeHttp implements HttpClient {
  readonly calls: FakeCall[] = [];
  private readonly routes: Route[] = [];

  constructor() {
    for (const [method, template, handler] of DEFAULTS) this.on(method, template, handler);
  }

  /** 预设返回值：后预设的优先；`value` 为函数时按调用计算 */
  on(method: HttpMethod, template: string, value: FakeHandler | unknown) {
    const handler = typeof value === 'function' ? (value as FakeHandler) : () => clone(value);
    this.routes.unshift({ method, template, ...compile(template), handler });
    return this;
  }

  /** 预设错误：接下来 `times` 次调用抛出该错误，之后恢复原来的响应 */
  fail(method: HttpMethod, template: string, error: PlatformError, times = Number.POSITIVE_INFINITY) {
    this.routes.unshift({
      method,
      template,
      ...compile(template),
      handler: () => {
        throw error;
      },
      failTimes: times
    });
    return this;
  }

  /** 某个接口收到的调用 */
  callsTo(method: HttpMethod, template: string) {
    const { regex } = compile(template);
    return this.calls.filter(call => call.method === method && regex.test(call.path));
  }

  private async dispatch(method: HttpMethod, path: string, body: unknown, options?: HttpRequestOptions) {
    const route = this.routes.find(r => r.method === method && r.regex.test(path) && (r.failTimes ?? 1) > 0);
    if (!route) throw new PlatformError(404, 'NOT_FOUND', `模拟实现没有接口 ${method} ${path}`);
    const match = route.regex.exec(path)!;
    const params = Object.fromEntries(route.names.map((name, i) => [name, decodeURIComponent(match[i + 1])]));
    const call: FakeCall = { method, path, params, body: body === undefined ? undefined : clone(body), options };
    this.calls.push(call);
    if (route.failTimes !== undefined) route.failTimes -= 1;
    // 与真实请求一样异步返回
    await Promise.resolve();
    return route.handler(call);
  }

  get<T>(path: string, options?: HttpRequestOptions) {
    return this.dispatch('GET', path, undefined, options) as Promise<T>;
  }

  post<T>(path: string, body?: unknown, options?: HttpRequestOptions) {
    return this.dispatch('POST', path, body, options) as Promise<T>;
  }

  put<T>(path: string, body: unknown, options?: HttpRequestOptions) {
    return this.dispatch('PUT', path, body, options) as Promise<T>;
  }

  delete<T>(path: string, options?: HttpRequestOptions) {
    return this.dispatch('DELETE', path, undefined, options) as Promise<T>;
  }

  /** 返回文件的接口与其他接口一样按（方法、路径模板）找响应，记为 POST 调用 */
  download(path: string, body: unknown, options?: HttpRequestOptions) {
    return this.dispatch('POST', path, body, options) as Promise<DownloadedFile>;
  }
}

export function createFakeHttp() {
  return new FakeHttp();
}
