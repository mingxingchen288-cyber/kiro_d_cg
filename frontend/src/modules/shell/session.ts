/**
 * 外壳的会话（C09 第 2 节、FS-02）：登录、选角色、注销、改自己的密码、刷新页面后恢复，以及会话失效、角色被撤销时的去向。
 *
 * - 账号只有一个角色时登录即选定（后端自动选定），直接进入；有多个角色时先选角色（登录页的选角色一步）。
 * - 会话标识在 HttpOnly Cookie 中；浏览器会话存储里只放 CSRF 令牌和登录时返回的角色列表（`/api/me` 不返回角色列表，
 *   刷新页面后或角色被撤销后选角色要用）。
 * - 请求返回 401 回登录页；401 SESSION_ROLE_REVOKED 时还有别的角色就去选角色；403 ROLE_SELECTION_REQUIRED 去选角色。
 * - 收到 `session.revoked` 或实时连接以 4401 关闭时，后台读一次 `/api/me` 核对：会话仍有效就继续（重连实时），
 *   否则按上面的错误码处理（realtime 缺口 1、3：撤销角色按用户发布，会关掉同一用户用别的角色登录的连接）。
 */
import { ref } from 'vue';
import { type PlatformApi, createPlatformApi } from '../../contracts/api';
import type { CurrentUser, MenuItem, RoleRef } from '../../contracts/http';
import type { HttpClient } from '../../contracts/shell';
import { type SessionProblem, sessionProblemOf } from './http';

/** anonymous：没有登录；roleRequired：已登录、还没有选定角色；ready：已选定角色 */
export type SessionStatus = 'anonymous' | 'roleRequired' | 'ready';

export interface StoredSession {
  csrfToken: string;
  roles: RoleRef[];
}

/** 浏览器会话存储（sessionStorage），测试中用内存实现 */
export interface SessionStore {
  read(): StoredSession | null;
  write(value: StoredSession | null): void;
}

/** 外壳的页面跳转，由路由实现 */
export interface SessionNavigator {
  /** 回登录页。`keepRedirect` 为 true 时登录后回到当前页面（会话失效）；注销时为 false */
  toLogin(keepRedirect: boolean): unknown;
  /** 到选角色 */
  toRoleSelect(): unknown;
  /** 登录或选角色完成，进入首页或登录前要去的页面 */
  entered(): unknown;
}

export interface SessionHooks {
  /** `/api/me` 确认会话可用（登录、选角色、恢复、核对之后）：启动实时连接和通知 */
  onReady?(): void;
  /** 会话结束或角色失效：停止实时连接和通知 */
  onEnded?(): void;
}

export class ShellSession {
  readonly status = ref<SessionStatus>('anonymous');
  readonly user = ref<CurrentUser | null>(null);
  readonly role = ref<RoleRef | null>(null);
  /** 账号的角色（登录响应的 `roles`），选角色时列出 */
  readonly roles = ref<RoleRef[]>([]);
  readonly menus = ref<MenuItem[]>([]);
  readonly configVersion = ref(0);

  private readonly http: HttpClient;
  private readonly api: PlatformApi;
  private readonly store: SessionStore;
  private readonly nav: SessionNavigator;
  private readonly hooks: SessionHooks;
  private checking: Promise<void> | null = null;
  private loggingOut = false;

  /** `http` 是不带会话处理的 C09 客户端：会话自己处理登录、恢复和核对时的错误 */
  constructor(deps: { http: HttpClient; store: SessionStore; nav: SessionNavigator; hooks?: SessionHooks }) {
    this.http = deps.http;
    this.api = createPlatformApi(deps.http);
    this.store = deps.store;
    this.nav = deps.nav;
    this.hooks = deps.hooks ?? {};
  }

  /** 写请求要带的 CSRF 令牌（C09 第 1 节） */
  get csrfToken() {
    return this.store.read()?.csrfToken ?? '';
  }

  async login(username: string, password: string): Promise<SessionStatus> {
    const result = await this.api.login(username, password);
    this.store.write({ csrfToken: result.csrfToken, roles: result.roles });
    this.user.value = result.user;
    this.roles.value = result.roles;
    if (!result.selectedRole) {
      this.role.value = null;
      this.status.value = 'roleRequired';
      await this.nav.toRoleSelect();
      return this.status.value;
    }
    await this.loadMe(false);
    await this.nav.entered();
    return this.status.value;
  }

  async selectRole(roleCode: string): Promise<void> {
    await this.api.selectRole(roleCode);
    await this.loadMe(false);
    await this.nav.entered();
  }

  /**
   * 刷新页面后恢复会话：会话存储里有令牌时读 `/api/me`（用户打开页面，不是后台请求）。
   * 只更新状态，不跳转，由路由守卫按状态决定去向。
   */
  async restore(): Promise<SessionStatus> {
    const saved = this.store.read();
    if (!saved) return this.status.value;
    this.roles.value = saved.roles;
    try {
      await this.loadMe(false);
    } catch (error) {
      const problem = sessionProblemOf(error);
      if (!problem) throw error;
      this.apply(problem);
    }
    return this.status.value;
  }

  /**
   * 注销：先停止实时连接和通知（之后收到本会话的 `session.revoked` 不再处理），注销请求要带 CSRF 令牌，
   * 请求结束后再清掉本地状态，回登录页、不带回跳地址。
   */
  async logout(): Promise<void> {
    this.loggingOut = true;
    this.hooks.onEnded?.();
    try {
      await this.api.logout();
    } finally {
      this.clear();
      this.loggingOut = false;
      await this.nav.toLogin(false);
    }
  }

  /** 改自己的密码：`POST /api/auth/password`（C09 之外，identity 缺口 2），不要求旧密码，与旧系统相同 */
  async changePassword(password: string): Promise<void> {
    await this.http.post<unknown>('/api/auth/password', { password });
  }

  /** 请求返回会话问题（FS-02）：回登录页或选角色。已经退出时不再处理 */
  onProblem(problem: SessionProblem): void {
    if (this.status.value === 'anonymous' || this.loggingOut) return;
    this.apply(problem);
    if (this.status.value === 'roleRequired') this.nav.toRoleSelect();
    else this.nav.toLogin(true);
  }

  /** 收到 `session.revoked` 或实时连接以 4401 关闭：后台读一次 `/api/me` 核对会话 */
  verify(): Promise<void> {
    if (this.status.value !== 'ready' || this.loggingOut) return Promise.resolve();
    this.checking ??= this.loadMe(true)
      .catch(error => {
        const problem = sessionProblemOf(error);
        if (problem) this.onProblem(problem);
      })
      .finally(() => {
        this.checking = null;
      });
    return this.checking;
  }

  /** 收到 `config.changed`（C10）时更新配置版本 */
  noteConfigVersion(version: number) {
    if (version > this.configVersion.value) this.configVersion.value = version;
  }

  private async loadMe(background: boolean) {
    const me = await this.api.me(background);
    const roles = [...this.roles.value];
    if (me.role && !roles.some(r => r.code === me.role!.code)) roles.push(me.role);
    this.store.write({ csrfToken: me.csrfToken, roles });
    this.roles.value = roles;
    this.user.value = me.user;
    this.role.value = me.role;
    this.menus.value = me.menus;
    this.configVersion.value = me.configVersion;
    if (me.role) {
      this.status.value = 'ready';
      this.hooks.onReady?.();
    } else {
      this.leaveReady('roleRequired');
    }
  }

  private apply(problem: SessionProblem) {
    if (problem === 'roleRevoked') {
      const revoked = this.role.value?.code;
      const remaining = this.roles.value.filter(r => r.code !== revoked);
      if (remaining.length) {
        this.roles.value = remaining;
        this.store.write({ csrfToken: this.csrfToken, roles: remaining });
        this.leaveReady('roleRequired');
        return;
      }
      this.clear();
      return;
    }
    if (problem === 'roleRequired') {
      this.leaveReady('roleRequired');
      return;
    }
    this.clear();
  }

  private leaveReady(next: 'roleRequired') {
    const wasReady = this.status.value === 'ready';
    this.role.value = null;
    this.menus.value = [];
    this.status.value = next;
    if (wasReady) this.hooks.onEnded?.();
  }

  private clear() {
    const wasReady = this.status.value === 'ready' && !this.loggingOut;
    this.store.write(null);
    this.status.value = 'anonymous';
    this.user.value = null;
    this.role.value = null;
    this.roles.value = [];
    this.menus.value = [];
    this.configVersion.value = 0;
    if (wasReady) this.hooks.onEnded?.();
  }
}
