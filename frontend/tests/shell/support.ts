/**
 * 外壳测试的公共部分：内存中的会话存储、记录跳转的导航、按 C09 模拟实现创建的会话。
 *
 * 账号和角色：单角色账号取 C09 的样例（杨娜 112，成本会计）；多角色账号取业务例子 E07（"技术中心"和"001"两个角色，
 * 假设的场景；账号 HY190510（381）是 cmx 中有技术中心角色的真实账号，见 backend/tests/authz/samples.py）。
 */
import { createFakeHttp } from '../../src/contracts/fakes/http';
import { loginResponseSample, meResponseSample } from '../../src/contracts/fakes/samples';
import type { LoginResponse, MeResponse, RoleRef } from '../../src/contracts/http';
import { withSessionHandling } from '../../src/modules/shell/http';
import { type SessionStore, ShellSession, type StoredSession } from '../../src/modules/shell/session';

export const TECH_CENTER: RoleRef = { code: '技术中心', name: '技术中心', admin: false };
export const ROLE_001: RoleRef = { code: '001', name: '001 海外营销中心-商业运营', admin: false };

const E07_USER = {
  userId: '381',
  username: 'HY190510',
  displayName: 'HY190510',
  departmentId: null,
  departmentName: null
};

/** E07 的账号登录：两个角色，后端不自动选定 */
export const e07Login: LoginResponse = {
  user: E07_USER,
  roles: [TECH_CENTER, ROLE_001],
  selectedRole: null,
  csrfToken: 'csrf-e07'
};

/** E07 的账号选了某个角色之后的 `/api/me` */
export function e07Me(role: RoleRef): MeResponse {
  return {
    user: E07_USER,
    role,
    menus: [
      {
        key: 'cost',
        title: '成本',
        kind: 'group',
        children: [{ key: 'COST_PINGGU', title: '成本核算', kind: 'page', pageCode: 'COST_PINGGU' }]
      }
    ],
    configVersion: 13,
    csrfToken: 'csrf-e07'
  };
}

/** 与浏览器的 sessionStorage 一样按 JSON 存取 */
export class MemoryStore implements SessionStore {
  value: StoredSession | null = null;

  read() {
    return this.value ? (JSON.parse(JSON.stringify(this.value)) as StoredSession) : null;
  }

  write(value: StoredSession | null) {
    this.value = value ? (JSON.parse(JSON.stringify(value)) as StoredSession) : null;
  }
}

export type NavCall = { to: 'login'; keepRedirect: boolean } | { to: 'roleSelect' } | { to: 'entered' };

/** 创建会话：HTTP 用 C09 的模拟实现；`shellHttp` 是交给模块的客户端（带会话处理） */
export function createSession(store = new MemoryStore()) {
  const http = createFakeHttp();
  const nav: NavCall[] = [];
  const hooks = { ready: 0, ended: 0 };
  const session = new ShellSession({
    http,
    store,
    nav: {
      toLogin: keepRedirect => nav.push({ to: 'login', keepRedirect }),
      toRoleSelect: () => nav.push({ to: 'roleSelect' }),
      entered: () => nav.push({ to: 'entered' })
    },
    hooks: {
      onReady: () => {
        hooks.ready += 1;
      },
      onEnded: () => {
        hooks.ended += 1;
      }
    }
  });
  const shellHttp = withSessionHandling(http, problem => session.onProblem(problem));
  return { session, http, shellHttp, store, nav, hooks };
}

/** 杨娜（单角色，成本会计）已登录 */
export async function loggedInYangna() {
  const ctx = createSession();
  ctx.http.on('POST', '/api/auth/login', loginResponseSample);
  ctx.http.on('GET', '/api/me', meResponseSample);
  await ctx.session.login('yangna', '正确的密码');
  ctx.nav.length = 0;
  return ctx;
}

/** E07 的账号选了"001"之后 */
export async function loggedInE07As001() {
  const ctx = createSession();
  ctx.http.on('POST', '/api/auth/login', e07Login);
  ctx.http.on('POST', '/api/auth/role', { selectedRole: ROLE_001 });
  ctx.http.on('GET', '/api/me', e07Me(ROLE_001));
  await ctx.session.login('HY190510', '正确的密码');
  await ctx.session.selectRole('001');
  ctx.nav.length = 0;
  return ctx;
}
