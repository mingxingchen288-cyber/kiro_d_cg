/**
 * 外壳的会话（FS-02，C09 第 2 节）：单角色跳过选角色；多角色先选角色；刷新页面后恢复；注销；改自己的密码；
 * 请求返回 401 回登录页；角色被撤销时去选角色或回登录页；收到 session.revoked 时核对会话。
 */
import { describe, expect, it } from 'vitest';
import { createPlatformApi } from '../../src/contracts/api';
import { PlatformError } from '../../src/contracts/errors';
import { meResponseSample } from '../../src/contracts/fakes/samples';
import { ROLE_001, TECH_CENTER, createSession, e07Login, e07Me, loggedInE07As001, loggedInYangna } from './support';

const sessionRequired = () => new PlatformError(401, 'SESSION_REQUIRED', '请先登录');
const roleRevoked = () => new PlatformError(401, 'SESSION_ROLE_REVOKED', '当前角色已被撤销，请重新选择角色');

describe('登录和选角色', () => {
  it('杨娜只有"成本会计"一个角色：登录后直接进入，不出现选角色，菜单和配置版本取自 /api/me', async () => {
    const { session, http, store, nav, hooks } = createSession();
    http.on('GET', '/api/me', meResponseSample);

    const status = await session.login('yangna', '正确的密码');

    expect(status).toBe('ready');
    expect(nav).toEqual([{ to: 'entered' }]);
    expect(http.callsTo('POST', '/api/auth/login')[0].body).toEqual({ username: 'yangna', password: '正确的密码' });
    expect(http.callsTo('POST', '/api/auth/role')).toHaveLength(0);
    expect(session.user.value?.displayName).toBe('杨娜');
    expect(session.role.value).toEqual({ code: 'COST_ACCOUNTANT', name: '成本会计', admin: false });
    expect(session.menus.value).toEqual(meResponseSample.menus);
    expect(session.configVersion.value).toBe(13);
    expect(store.value).toEqual({
      csrfToken: 'c',
      roles: [{ code: 'COST_ACCOUNTANT', name: '成本会计', admin: false }]
    });
    expect(session.csrfToken).toBe('c');
    expect(hooks.ready).toBe(1);
  });

  it('E07 的账号有"技术中心"和"001"两个角色：登录后先选角色，选"技术中心"后进入', async () => {
    const { session, http, nav } = createSession();
    http.on('POST', '/api/auth/login', e07Login);
    http.on('POST', '/api/auth/role', { selectedRole: TECH_CENTER });
    http.on('GET', '/api/me', e07Me(TECH_CENTER));

    const status = await session.login('HY190510', '正确的密码');

    expect(status).toBe('roleRequired');
    expect(nav).toEqual([{ to: 'roleSelect' }]);
    expect(session.roles.value.map(r => r.name)).toEqual(['技术中心', '001 海外营销中心-商业运营']);
    expect(http.callsTo('GET', '/api/me')).toHaveLength(0);

    await session.selectRole('技术中心');

    expect(http.callsTo('POST', '/api/auth/role')[0].body).toEqual({ roleCode: '技术中心' });
    expect(session.status.value).toBe('ready');
    expect(session.role.value).toEqual(TECH_CENTER);
    expect(nav).toEqual([{ to: 'roleSelect' }, { to: 'entered' }]);
  });

  it('刷新页面：会话存储里有令牌时用 /api/me 恢复，不重新登录；没选角色时恢复到选角色，角色列表取自会话存储', async () => {
    const ready = createSession();
    ready.store.write({ csrfToken: 'c', roles: [{ code: 'COST_ACCOUNTANT', name: '成本会计', admin: false }] });
    ready.http.on('GET', '/api/me', meResponseSample);
    expect(await ready.session.restore()).toBe('ready');
    expect(ready.http.callsTo('GET', '/api/me')[0].options?.background).toBeFalsy();
    expect(ready.http.callsTo('POST', '/api/auth/login')).toHaveLength(0);
    expect(ready.nav).toEqual([]);

    const choosing = createSession();
    choosing.store.write({ csrfToken: 'csrf-e07', roles: [TECH_CENTER, ROLE_001] });
    choosing.http.on('GET', '/api/me', { ...e07Me(TECH_CENTER), role: null, menus: [] });
    expect(await choosing.session.restore()).toBe('roleRequired');
    expect(choosing.session.roles.value).toEqual([TECH_CENTER, ROLE_001]);
  });

  it('注销：调 /api/auth/logout，清掉会话存储，回登录页且不带回跳地址', async () => {
    const { session, http, store, nav, hooks } = await loggedInYangna();

    await session.logout();

    expect(http.callsTo('POST', '/api/auth/logout')).toHaveLength(1);
    expect(store.value).toBeNull();
    expect(session.status.value).toBe('anonymous');
    expect(session.user.value).toBeNull();
    expect(nav).toEqual([{ to: 'login', keepRedirect: false }]);
    expect(hooks.ended).toBe(1);
  });

  it('改自己的密码：POST /api/auth/password，只传新密码（与旧系统相同）', async () => {
    const { session, http } = await loggedInYangna();
    http.on('POST', '/api/auth/password', undefined);

    await session.changePassword('newPass_2026');

    expect(http.callsTo('POST', '/api/auth/password').map(c => c.body)).toEqual([{ password: 'newPass_2026' }]);
  });
});

describe('会话失效和角色撤销（FS-02）', () => {
  it('杨娜在成本核算页的请求返回 401 SESSION_REQUIRED：回登录页，登录后回到原页面', async () => {
    const { session, http, shellHttp, store, nav, hooks } = await loggedInYangna();
    http.fail('GET', '/api/pages/:pageCode/view', sessionRequired());

    await expect(createPlatformApi(shellHttp).pageView('COST_PINGGU')).rejects.toMatchObject({
      code: 'SESSION_REQUIRED'
    });

    expect(nav).toEqual([{ to: 'login', keepRedirect: true }]);
    expect(session.status.value).toBe('anonymous');
    expect(store.value).toBeNull();
    expect(hooks.ended).toBe(1);
  });

  it('E07 的账号用"001"登录，管理员撤销了"001"：请求返回 SESSION_ROLE_REVOKED，去选角色，只剩"技术中心"', async () => {
    const { session, http, shellHttp, store, nav } = await loggedInE07As001();
    http.fail('POST', '/api/pages/:pageCode/rows', roleRevoked());

    await expect(createPlatformApi(shellHttp).listRows('COST_PINGGU', { startRow: 0, endRow: 100 })).rejects.toThrow();

    expect(nav).toEqual([{ to: 'roleSelect' }]);
    expect(session.status.value).toBe('roleRequired');
    expect(session.roles.value).toEqual([TECH_CENTER]);
    expect(store.value?.roles).toEqual([TECH_CENTER]);
    expect(store.value?.csrfToken).toBe('csrf-e07');
  });

  it('杨娜只有一个角色，这个角色被撤销：回登录页', async () => {
    const { session, http, shellHttp, nav } = await loggedInYangna();
    http.fail('GET', '/api/pages/:pageCode/view', roleRevoked());

    await expect(createPlatformApi(shellHttp).pageView('COST_PINGGU')).rejects.toThrow();

    expect(nav).toEqual([{ to: 'login', keepRedirect: true }]);
    expect(session.status.value).toBe('anonymous');
  });

  it('收到 session.revoked（账号停用）：后台读 /api/me 核对，返回 401 后回登录页', async () => {
    const { session, http, nav } = await loggedInYangna();
    http.fail('GET', '/api/me', new PlatformError(401, 'SESSION_REQUIRED', '账号已停用，请重新登录'));

    await session.verify();

    const check = http.callsTo('GET', '/api/me').at(-1)!;
    expect(check.options?.background).toBe(true);
    expect(nav).toEqual([{ to: 'login', keepRedirect: true }]);
    expect(session.status.value).toBe('anonymous');
  });

  it('收到 session.revoked（撤销角色），但本会话选的"技术中心"没被撤销：核对后继续使用，重新启动实时连接', async () => {
    const { session, http, nav, hooks } = createSession();
    http.on('POST', '/api/auth/login', e07Login);
    http.on('POST', '/api/auth/role', { selectedRole: TECH_CENTER });
    http.on('GET', '/api/me', e07Me(TECH_CENTER));
    await session.login('HY190510', '正确的密码');
    await session.selectRole('技术中心');
    nav.length = 0;
    const readyBefore = hooks.ready;

    await session.verify();

    expect(session.status.value).toBe('ready');
    expect(session.role.value).toEqual(TECH_CENTER);
    expect(nav).toEqual([]);
    expect(hooks.ready).toBe(readyBefore + 1);
  });
});
