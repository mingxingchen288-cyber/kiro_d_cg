/** C11 前端装载：外壳提供给前端模块的 ShellApi，以及前端模块的注册接口。 */
import type { Ref } from 'vue';
import type { RouteRecordRaw } from 'vue-router';
import type { CurrentUser, RoleRef } from './http';
import type { RealtimeClient } from './realtime';
import type { CalcWorkerClient } from './rules';

export type QueryValue = string | number | boolean | null | undefined;

export interface HttpRequestOptions {
  /** 前端自动发起、不是用户操作直接引起的请求（C09 第 1 节），带 `X-Background-Request: 1`，不顺延会话 */
  background?: boolean;
  /** 查询参数；值为 null 或 undefined 的不出现 */
  query?: Record<string, QueryValue>;
}

/**
 * 按 C09 实现的 HTTP 客户端：带会话 Cookie；写请求带 `X-CSRF-Token`；失败时抛 `PlatformError`（C03，错误体经
 * `parseErrorResponse` 严格检查）。路径以 `/api/` 开头，不含服务地址。
 */
export interface HttpClient {
  get<T>(path: string, options?: HttpRequestOptions): Promise<T>;
  post<T>(path: string, body?: unknown, options?: HttpRequestOptions): Promise<T>;
  put<T>(path: string, body: unknown, options?: HttpRequestOptions): Promise<T>;
  delete<T>(path: string, options?: HttpRequestOptions): Promise<T>;
  /** 返回文件的接口（导出 xlsx）：POST 请求体，响应为文件内容 */
  download(path: string, body: unknown, options?: HttpRequestOptions): Promise<Blob>;
}

export interface ShellApi {
  http: HttpClient;
  realtime: RealtimeClient;
  calc: CalcWorkerClient;
  session: {
    user: Readonly<Ref<CurrentUser | null>>;
    role: Readonly<Ref<RoleRef | null>>;
    configVersion: Readonly<Ref<number>>;
  };
  tabs: {
    open(path: string, title: string): void;
    close(path: string): void;
    /** 有未保存修改时，关闭页签前确认 */
    setDirty(path: string, dirty: boolean): void;
  };
  message: { success(text: string): void; warning(text: string): void; error(text: string): void };
}

export interface FrontendModule {
  name: 'page' | 'config' | 'approval' | 'admin';
  /** vue-router 路由，路径前缀见 C11 的表 */
  routes: RouteRecordRaw[];
  /** 注册时调用一次 */
  install(shell: ShellApi): void;
}
