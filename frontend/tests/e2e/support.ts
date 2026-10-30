/**
 * 端到端用例的测试工具（只有这一份；以后核对界面都写成 tests/e2e 下的正式用例）。
 *
 * - 账号：setup 项目（auth.setup.ts）按账号各登录一次，存登录状态（Cookie 和 sessionStorage 里的会话）。
 *   默认的 `page` 是 admin（`test.use({ user: 'chengben01' })` 换账号）；`as('chengben01')` 另开一个已登录的浏览器上下文；
 *   要从登录页开始的用例用 `fresh()` 开一个没有登录的上下文。
 * - 页面：`openPage(page, '页面编码')` 按页面编码打开通用页面；`openDoc(page, 单据号)` 按单据号筛选主表并选中。
 * - 表格：`cell(grid, rowId, colId)` 按 row-id、col-id 取格子；`edit(page, 格子, 值)`；`canEdit`；`save(page)`；`summary(grid)`。
 * - 提示：`toast(page, 文字)`。
 * - 接口：`api`（默认页面的账号）、`adminApi`、`apiOf(page)`：经平台接口读数据、准备数据。
 * - 测试数据：`data.copyDoc('2550')` 复制出自己的测试成本单（备注带 PF_TEST）；`data.goods()` 测试物料；
 *   `data.account()` 测试账号……用例结束时按依赖顺序自动删除（先驳回还在审批中的审批）。
 * - 平台记录：本 worker 提交的命令和发起的审批，worker 结束时由 backend/tests/e2e/cleanup.py 删掉（命令记录、投递、
 *   站内通知、审批记录）。
 *
 * 不用固定等待（waitForTimeout）：等元素出现、等接口响应、等内容变化；表格要等下一帧时用 `nextFrame`。
 */
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import {
  type APIRequestContext,
  type BrowserContext,
  type ConsoleMessage,
  type Locator,
  type Page,
  type Response,
  test as base,
  expect
} from '@playwright/test';
import type { FieldValue, FieldValues } from '../../src/contracts/command';
import type { PageView } from '../../src/contracts/page-view';
import { type DocRecord, MARKER, type Row, copyPlan, pricedRow } from './data';

export { expect };
export type { Locator, Page };

// ================================================================ 账号和登录状态

export const USERS = {
  admin: { username: 'admin', password: 'admin123..' },
  chengben01: { username: 'chengben01', password: 'Abc123..' },
  jishu01: { username: 'jishu01', password: 'Jishu123..' }
} as const;
export type UserName = keyof typeof USERS;

const AUTH_DIR = fileURLToPath(new URL('../../playwright/.auth/', import.meta.url));
const BACKEND_DIR = fileURLToPath(new URL('../../../backend/', import.meta.url));

/** 账号的 storageState 文件（Cookie） */
export const authFile = (user: UserName) => `${AUTH_DIR}${user}.json`;
/** 账号的 sessionStorage（外壳的会话：CSRF 令牌和角色列表）；storageState 不存 sessionStorage，另存一份 */
export const sessionFile = (user: UserName) => `${AUTH_DIR}${user}.session.json`;

/** 在页面脚本运行前把会话写回 sessionStorage（刷新后外壳按它恢复会话，modules/shell/session.ts 的 restore） */
async function restoreSession(context: BrowserContext, user: UserName) {
  const saved = JSON.parse(readFileSync(sessionFile(user), 'utf8')) as Record<string, string>;
  await context.addInitScript(items => {
    try {
      for (const [key, value] of Object.entries(items))
        if (!sessionStorage.getItem(key)) sessionStorage.setItem(key, value);
    } catch {
      // about:blank 等没有 sessionStorage 的页面
    }
  }, saved);
}

// ================================================================ 平台记录（命令、审批）

type Result = { requestKey?: string; approvals?: Array<{ approvalId: string }> } | null;

/** 一个 worker 提交的命令（请求键）和发起的审批；worker 结束时删掉它们产生的平台记录 */
export class Trail {
  readonly keys = new Set<string>();
  readonly approvals = new Set<string>();

  note(result: Result) {
    if (result?.requestKey) this.keys.add(result.requestKey);
    for (const approval of result?.approvals ?? []) this.approvals.add(approval.approvalId);
  }

  /** backend/tests/e2e/cleanup.py：删掉命令记录、投递、站内通知和审批记录（业务数据由用例自己删） */
  clean() {
    if (!this.keys.size && !this.approvals.size) return;
    const out = backendScript('tests.e2e.cleanup', [
      '--keys',
      [...this.keys].join(','),
      '--approvals',
      [...this.approvals].join(',')
    ]);
    // eslint-disable-next-line no-console
    console.log(out.at(-1));
  }
}

/** 在 backend 目录运行一个测试辅助脚本（直接读写 d_cg 的测试数据），返回输出的各行 */
export function backendScript(module: string, args: string[]) {
  const done = spawnSync('uv', ['run', 'python', '-m', module, ...args], {
    cwd: BACKEND_DIR,
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  });
  if (done.status !== 0) throw new Error(`${module} ${args.join(' ')} 失败：${done.stderr}`);
  return done.stdout.trim().split('\n');
}

/** 命令、通过、驳回、撤回的响应：记下请求键和发起的审批 */
const RECORDED = /\/api\/(commands|approvals\/\d+\/(pass|reject|withdraw))$/;

function watchResults(context: BrowserContext, notes: Array<(result: Result) => void>) {
  context.on('response', (response: Response) => {
    if (response.request().method() !== 'POST' || !RECORDED.test(new URL(response.url()).pathname)) return;
    response
      .json()
      .then((result: Result) => {
        for (const note of notes) note(result);
      })
      .catch(() => undefined);
  });
}

// ================================================================ 接口

export type ApiResult<T = any> = { status: number; body: T };
type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';
type Target = { page: string; operation: string };
export const COST_SAVE: Target = { page: 'COST_PINGGU', operation: 'COST_PINGGU.save' };

/**
 * 平台接口（C09），带这个账号的会话 Cookie；写请求带 CSRF 令牌（读 `/api/me`）和 Origin。
 * 构建产物与后端同源，接口在 `/api`；开发服务器上在 `/proxy-default/api`（`apiPrefix`）。
 */
export class Api {
  private csrf = '';
  private readonly views = new Map<string, PageView>();

  // eslint-disable-next-line max-params -- 请求上下文、接口前缀、Origin、记录结果的回调
  constructor(
    readonly request: APIRequestContext,
    private readonly prefix: string,
    private readonly origin: string,
    private readonly onResult: (result: Result) => void = () => undefined
  ) {}

  async send<T = any>(method: Method, path: string, body?: unknown): Promise<ApiResult<T>> {
    const headers: Record<string, string> = { Origin: this.origin };
    if (method !== 'GET') headers['X-CSRF-Token'] = await this.token();
    const response = await this.request.fetch(`${this.prefix}${path}`, { method, data: body, headers });
    const text = await response.text();
    const parsed = text ? JSON.parse(text) : null;
    if (method === 'POST' && RECORDED.test(path)) this.onResult(parsed);
    return { status: response.status(), body: parsed };
  }

  /** 要求成功（2xx）的请求，返回响应体 */
  async ok<T = any>(method: Method, path: string, body?: unknown): Promise<T> {
    const result = await this.send<T>(method, path, body);
    if (result.status >= 300)
      throw new Error(`${method} ${path} 返回 ${result.status}：${JSON.stringify(result.body)}`);
    return result.body;
  }

  get<T = any>(path: string) {
    return this.ok<T>('GET', path);
  }

  private async token() {
    if (!this.csrf) {
      const me = await this.request.get(`${this.prefix}/api/me`);
      this.csrf = (await me.json()).csrfToken;
    }
    return this.csrf;
  }

  /** 提交一条命令（默认成本核算的保存），返回命令结果 */
  async command(documents: unknown[], target: Target = COST_SAVE, params: Record<string, unknown> = {}) {
    const result = await this.send('POST', '/api/commands', {
      requestKey: crypto.randomUUID(),
      ...target,
      params,
      documents
    });
    return result.body;
  }

  /** 页面视图（C05），每个页面只读一次 */
  async view(page = 'COST_PINGGU') {
    if (!this.views.has(page)) this.views.set(page, await this.get<PageView>(`/api/pages/${page}/view`));
    return this.views.get(page)!;
  }

  /** 一张单据（主表和明细） */
  record(docId: string, page = 'COST_PINGGU') {
    return this.get<DocRecord>(`/api/pages/${page}/records/${docId}`);
  }

  async exists(docId: string, page = 'COST_PINGGU') {
    return (await this.send('GET', `/api/pages/${page}/records/${docId}`)).status === 200;
  }

  /** 物料清单的执行价（T_COST_GOODS_PRICE_V.ZX_PRICE，执行价为空时为参考价格） */
  async listPrices(goodsIds: string[]) {
    const found = await this.ok<{ rows: Row[] }>('POST', '/api/pages/GOODS_PRICE_MANAGE/rows/by-keys', {
      entity: 'COST_GOODS_PRICE',
      rowKeys: [...new Set(goodsIds)]
    });
    return new Map<string, FieldValue>(found.rows.map(r => [String(r.values.GOODSID), r.values.ZX_PRICE ?? null]));
  }

  approval(id: string) {
    return this.get(`/api/approvals/${id}`);
  }

  /** 经接口通过一级审批（指纹取自审批详情） */
  async pass(id: string, comment = '端到端用例经接口通过') {
    const detail = await this.approval(id);
    return this.ok('POST', `/api/approvals/${id}/pass`, {
      requestKey: crypto.randomUUID(),
      fingerprint: detail.fingerprint,
      checkedRows: [],
      comment,
      params: {}
    });
  }

  reject(id: string, comment = '端到端用例结束，驳回') {
    return this.ok('POST', `/api/approvals/${id}/reject`, { requestKey: crypto.randomUUID(), comment });
  }
}

// ================================================================ 测试数据

/** 命令结果应为 saved，否则带上结果报错（不把结果写进断言标题，trace 里的步骤保持简短） */
export function mustSave<T extends { outcome?: string }>(result: T) {
  if (result?.outcome !== 'saved') throw new Error(`保存没有成功：${JSON.stringify(result)}`);
  return result as T & { idMap: Record<string, string>; rows: Row[] };
}

/** 一张测试成本单：新主键和来源明细行到新行的对应 */
export class TestDoc {
  constructor(
    readonly docId: string,
    private readonly rows: Map<string, string>
  ) {}

  /** 来源单据明细行（例如 2550 的 206323）在测试成本单中的主键 */
  row(sourceKey: string) {
    const found = this.rows.get(sourceKey);
    if (!found) throw new Error(`测试成本单 ${this.docId} 没有复制明细 ${sourceKey}（单价与执行价不同的行不复制）`);
    return found;
  }
}

type CopyOptions = {
  /** 带哪些明细：priced 只带单价等于执行价的行（默认），none 不带，或自己挑 */
  details?: 'priced' | 'none' | ((row: Row) => boolean);
  /** 覆盖主表的值；备注默认是 PF_TEST 标记 */
  master?: FieldValues;
};

/**
 * 本用例建的测试数据，用例结束时删除：先驳回本用例发起、还在审批中的审批（解冻），再删成本单（经平台），
 * 再删账号（直接删表，平台没有删除账号的接口）、部门、配置项，最后删测试物料、液体成本单（平台写不了，直接删表）。
 */
export class TestData {
  readonly docs: string[] = [];
  readonly approvals = new Set<string>();
  private readonly goodsIds: string[] = [];
  private readonly liquids: string[] = [];
  private readonly users: string[] = [];
  private readonly departments: string[] = [];
  private readonly configItems: string[] = [];

  constructor(
    private readonly api: Api,
    readonly marker: string
  ) {}

  note(result: Result) {
    for (const approval of result?.approvals ?? []) this.approvals.add(approval.approvalId);
  }

  /** 经平台复制一张成本单（主表新增、明细新增），备注带 PF_TEST 标记 */
  async copyDoc(source: string, options: CopyOptions = {}) {
    const view = await this.api.view();
    const record = await this.api.record(source);
    let keep: (row: Row) => boolean = () => false;
    if (options.details === undefined || options.details === 'priced') {
      const goods = Object.values(record.details)
        .flat()
        .map(r => String(r.values.GOODSID));
      keep = pricedRow(await this.api.listPrices(goods));
    } else if (typeof options.details === 'function') keep = options.details;
    const plan = copyPlan(view, record, {
      keep,
      master: { MEMO: this.marker, ...options.master },
      tmp: () => `tmp-${crypto.randomUUID()}`
    });
    const result = mustSave(await this.api.command([plan.document]));
    const docId = String(result.idMap[plan.masterId]);
    this.docs.push(docId);
    return new TestDoc(docId, new Map([...plan.rows].map(([from, tmp]) => [from, String(result.idMap[tmp])])));
  }

  /** 经平台新建一张成本单（主表取 G5 用过的批量、包装规格等），原辅料为 `materials` */
  async newDoc(materials: FieldValues[], master: FieldValues = {}) {
    const masterId = `tmp-${crypto.randomUUID()}`;
    const ids = materials.map(() => `tmp-${crypto.randomUUID()}`);
    const values = {
      MEMO: this.marker,
      APEX_PL: '1000000',
      P_PERPACK: '112',
      S_PERBACK: '80',
      YIELD: '93.94',
      ...master
    };
    const result = await this.api.command([
      {
        entity: 'COST_PINGGU',
        master: { op: 'add', clientRowId: masterId, values },
        details: materials.map((v, i) => ({ entity: 'COST_MATERIAL', op: 'add', clientRowId: ids[i], values: v }))
      }
    ]);
    mustSave(result);
    const docId = String(result.idMap[masterId]);
    this.docs.push(docId);
    return { docId, rows: ids.map(id => String(result.idMap[id])) };
  }

  /** 页面上新建的单据（例如 Lookup 选产品后保存）也记下，结束时删除 */
  adopt(docId: string) {
    this.docs.push(docId);
  }

  /** 测试物料：模拟 ERP 同步新增一个 ERP 物料（参考价格 `price`，执行价为空；backend/tests/e2e/sample_two.py） */
  goods(price = '10') {
    const { goodsid } = JSON.parse(backendScript('tests.e2e.sample_two', ['goods', '--price', price]).at(-1)!);
    this.goodsIds.push(goodsid);
    return goodsid as string;
  }

  /** 液体成本单一张，明细一行这个物料（液体成本核算没有在平台注册，直接写表） */
  liquid(goodsId: string, price = '10') {
    const made = JSON.parse(
      backendScript('tests.e2e.sample_two', ['liquid', '--goods', goodsId, '--price', price]).at(-1)!
    );
    this.liquids.push(made.docid);
    return made as { docid: string; dtlid: string };
  }

  /** 物料清单执行价、液体明细单价和每批成本（直接读表） */
  // eslint-disable-next-line class-methods-use-this -- 与建测试物料的方法放在一起，用例从 data 上调用
  showGoods(goodsId: string, lqDtl = '') {
    return JSON.parse(backendScript('tests.e2e.sample_two', ['show', '--goods', goodsId, '--lq-dtl', lqDtl]).at(-1)!);
  }

  /** 测试账号（经平台新建；结束时直接删 PF_USER、PF_USER_ROLE） */
  async account(options: { roleCodes?: string[]; departmentId?: string | null; displayName?: string } = {}) {
    const suffix = crypto.randomUUID().slice(0, 8);
    const password = 'PfTest123..';
    const created = await this.api.ok('POST', '/api/admin/accounts', {
      username: `pf_test_${suffix}`,
      displayName: options.displayName ?? `PF_TEST ${suffix}`,
      departmentId: options.departmentId ?? null,
      password,
      roleCodes: options.roleCodes ?? []
    });
    this.users.push(String(created.userId));
    return { ...created, password } as {
      userId: string;
      username: string;
      displayName: string;
      password: string;
      departmentId: string | null;
      roleCodes: string[];
      enabled: boolean;
    };
  }

  /** 页面上新建的账号、部门、配置项也记下，结束时删除 */
  adoptUser(userId: string) {
    this.users.push(userId);
  }

  adoptDepartment(departmentId: string) {
    this.departments.push(departmentId);
  }

  /** 配置项，例如 `role/PF_TEST_xxx`、`approvalFlow/PF_TEST_xxx` */
  adoptConfig(typeAndKey: string) {
    this.configItems.push(typeAndKey);
  }

  /* eslint-disable no-await-in-loop -- 清理按依赖顺序逐个进行：先解冻、再删单据、再删账号和部门 */
  async teardown() {
    const problems: string[] = [];
    const attempt = async (what: string, run: () => Promise<unknown> | unknown) => {
      try {
        await run();
      } catch (error) {
        problems.push(`${what}：${String(error)}`);
      }
    };
    for (const id of this.approvals) {
      await attempt(`驳回审批 ${id}`, async () => {
        if ((await this.api.approval(id)).status === 'pending') await this.api.reject(id);
      });
    }
    const left: string[] = [];
    await attempt('删除测试成本单', async () => {
      for (const docId of this.docs) if (await this.api.exists(docId)) left.push(docId);
      if (!left.length) return;
      const result = await this.api.command(
        left.map(rowKey => ({ entity: 'COST_PINGGU', master: { op: 'delete', rowKey }, details: [] }))
      );
      if (result?.outcome === 'saved') left.length = 0;
    });
    if (this.users.length) {
      await attempt('删除测试账号', () => backendScript('tests.e2e.cleanup', ['--users', this.users.join(',')]));
    }
    for (const id of this.departments)
      await attempt(`删除部门 ${id}`, () => this.api.ok('DELETE', `/api/admin/departments/${id}`));
    for (const item of this.configItems)
      await attempt(`删除配置项 ${item}`, async () => {
        // 用例中途失败时配置项可能还没保存（404 就是没有要删的）
        const result = await this.api.send('DELETE', `/api/config/items/${item}`);
        if (result.status >= 300 && result.status !== 404)
          throw new Error(`返回 ${result.status}：${JSON.stringify(result.body)}`);
      });
    if (left.length || this.goodsIds.length || this.liquids.length) {
      // 平台删不了的（测试物料、液体成本单，以及中途失败留下的成本单）直接按主键删
      await attempt('删除测试物料', () =>
        backendScript('tests.e2e.sample_two', [
          'drop',
          '--goods',
          this.goodsIds.join(','),
          '--lq',
          this.liquids.join(','),
          '--docs',
          left.join(',')
        ])
      );
    }
    expect(problems, '清理测试数据').toEqual([]);
  }
  /* eslint-enable no-await-in-loop */
}

// ================================================================ fixtures

export type E2EOptions = {
  /** 接口前缀：构建产物为空（同源），开发服务器上为 `/proxy-default` */
  apiPrefix: string;
};

type WorkerFixtures = E2EOptions & { trail: Trail };
type TestFixtures = {
  /** 默认 `page` 的账号 */
  user: UserName;
  /** 以某个账号另开一个已登录的浏览器上下文，返回页面 */
  as: (user: UserName) => Promise<Page>;
  /** 开一个没有登录的浏览器上下文（从登录页开始的用例） */
  fresh: () => Promise<Page>;
  /** 某个页面的接口（带这个页面的会话） */
  apiOf: (page: Page) => Api;
  /** 默认 `page` 的接口 */
  api: Api;
  /** admin 的接口（准备数据、核对结果、清理） */
  adminApi: Api;
  /** 本用例建的测试数据，结束时自动删除 */
  data: TestData;
};

export const test = base.extend<TestFixtures, WorkerFixtures>({
  apiPrefix: ['', { option: true, scope: 'worker' }],
  trail: [
    // eslint-disable-next-line no-empty-pattern
    async ({}, use) => {
      const trail = new Trail();
      await use(trail);
      trail.clean();
    },
    { scope: 'worker' }
  ],
  user: ['admin', { option: true }],
  storageState: async ({ user }, use) => use(authFile(user)),
  adminApi: async ({ playwright, baseURL, apiPrefix, trail }, use) => {
    const request = await playwright.request.newContext({ baseURL, storageState: authFile('admin') });
    await use(new Api(request, apiPrefix, new URL(baseURL!).origin, r => trail.note(r)));
    await request.dispose();
  },
  data: async ({ adminApi }, use, testInfo) => {
    // 备注列最长 100 字节：只写用例的文件名和行号（ASCII）
    const data = new TestData(adminApi, `${MARKER} ${testInfo.file.split(/[\\/]/).pop()}:${testInfo.line}`);
    await use(data);
    await data.teardown();
  },
  context: async ({ context, user, trail, data }, use) => {
    await restoreSession(context, user);
    watchResults(context, [r => trail.note(r), r => data.note(r)]);
    await use(context);
  },
  apiOf: async ({ apiPrefix, baseURL, trail, data }, use) => {
    await use(
      p =>
        new Api(p.request, apiPrefix, new URL(baseURL!).origin, r => {
          trail.note(r);
          data.note(r);
        })
    );
  },
  api: async ({ page, apiOf }, use) => use(apiOf(page)),
  as: async ({ browser, trail, data }, use) => {
    const opened: BrowserContext[] = [];
    await use(async user => {
      const context = await browser.newContext({ storageState: authFile(user) });
      opened.push(context);
      await restoreSession(context, user);
      watchResults(context, [r => trail.note(r), r => data.note(r)]);
      return context.newPage();
    });
    await Promise.all(opened.map(context => context.close()));
  },
  fresh: async ({ browser, trail, data }, use) => {
    const opened: BrowserContext[] = [];
    await use(async () => {
      const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
      opened.push(context);
      watchResults(context, [r => trail.note(r), r => data.note(r)]);
      return context.newPage();
    });
    await Promise.all(opened.map(context => context.close()));
  }
});

// ================================================================ 登录、菜单

/** 从登录页登录，等到进入首页 */
export async function login(page: Page, user: { username: string; password: string }) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(user.username);
  await page.getByPlaceholder('请输入密码').fill(user.password);
  await page.getByRole('button', { name: '确认' }).click();
  await page.waitForURL('**/home');
}

/** 顶栏右上角用户名 → 退出登录 → 确认 */
export async function logout(page: Page) {
  await page.locator('header').getByRole('button').last().click();
  await page.getByText('退出登录', { exact: true }).click();
  await page.locator('.n-dialog').getByRole('button', { name: '确认' }).click();
  await page.waitForURL('**/login**');
}

/**
 * 左侧菜单：默认收起、是盖在页面上的抽屉（与旧系统相同）。点顶栏左上角的按钮展开，`group` 为分组（例如"成本"）时先点开分组，
 * 点菜单项后点遮罩收起。
 */
export async function openMenu(page: Page, title: string, group?: string) {
  await expandMenu(page);
  const item = page.locator('aside .n-menu-item-content', { hasText: title }).first();
  if (group && !(await item.isVisible()))
    await page.locator('aside .n-menu-item-content', { hasText: group }).first().click();
  await item.click();
  await closeMenu(page);
}

/** 菜单展开了没有：收起时侧栏宽度为 0（admin-layout 的 mobile sider） */
async function menuOpen(page: Page) {
  const box = await page.locator('aside:has(.n-menu)').first().boundingBox();
  return Boolean(box && box.width > 100);
}

async function expandMenu(page: Page) {
  if (!(await menuOpen(page))) await page.locator('header button').first().click();
  await expect.poll(() => menuOpen(page)).toBe(true);
}

/** 菜单展开时点右边的遮罩收起（遮罩盖住整个页面，点在侧栏右边） */
export async function closeMenu(page: Page) {
  if (await menuOpen(page)) await page.mouse.click(1200, 450);
  await expect.poll(() => menuOpen(page)).toBe(false);
}

/** 菜单里能看到的全部菜单项（分组全部点开） */
export async function menuTitles(page: Page) {
  await expandMenu(page);
  const menu = page.locator('aside .n-menu').first();
  for (const group of await menu.locator('.n-submenu').all()) {
    // 逐个点开分组，按顺序进行
    // eslint-disable-next-line no-await-in-loop
    const open = await group.locator('.n-submenu-children').count();
    // eslint-disable-next-line no-await-in-loop
    if (!open) await group.locator('.n-menu-item-content').first().click();
  }
  const titles = await menu
    .locator('.n-menu-item-content')
    .evaluateAll(els => els.map(e => (e.textContent ?? '').trim()).filter(Boolean));
  await closeMenu(page);
  return titles;
}

// ================================================================ 通用页面

export const masterGrid = (page: Page) => page.getByTestId('master-grid');
export const detailGrid = (page: Page, entity: string) => page.getByTestId(`detail-${entity}`);
export const toolbar = (page: Page) => page.locator('.generic-page__toolbar');

/** 等浏览器画完下一帧（AG Grid 在滚动、改列后按帧渲染） */
export async function nextFrame(page: Page) {
  await page.evaluate(
    () =>
      new Promise<void>(resolve => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      })
  );
}

/** 按页面编码打开通用页面（/page/<编码>），等主表第一行数据出现（底部汇总行先于数据出现，不算） */
export async function openPage(page: Page, code: string) {
  await page.goto(`/page/${code}`);
  await expect(masterGrid(page).locator('.ag-center-cols-container .ag-row').first()).toBeVisible();
}

/**
 * 主表按某列筛选（列头的 AG Grid 筛选），等列表重新查询，返回请求和响应。
 * `type` 为数值筛选的方式（equals），文本列默认 contains。
 */
export async function filterColumn(page: Page, column: string, value: string) {
  const grid = masterGrid(page);
  const header = grid.locator(`.ag-header-cell[col-id="${column}"]`);
  await scrollToColumn(grid, column);
  await header.hover();
  await header.locator('.ag-header-cell-filter-button').click();
  const input = page.locator('.ag-filter input.ag-input-field-input').filter({ visible: true }).first();
  await expect(input).toBeVisible();
  const listed = page.waitForResponse(
    r => r.url().includes(`/api/pages/`) && r.url().endsWith('/rows') && r.request().method() === 'POST'
  );
  await input.fill(value);
  await input.press('Enter');
  const response = await listed;
  await page.keyboard.press('Escape');
  return { request: response.request().postDataJSON(), body: await response.json() };
}

/** 打开成本核算，按单据号筛选主表并选中这张单据 */
export async function openDoc(page: Page, docId: string, code = 'COST_PINGGU') {
  await openPage(page, code);
  await filterColumn(page, 'DOCID', docId);
  // 筛选后表格换上新的一页之前，旧的同一行可能还在：等只剩筛出的这一行
  await expect(masterGrid(page).locator('.ag-pinned-left-cols-container .ag-row')).toHaveCount(1);
  await selectRow(page, docId);
}

/**
 * 明细的显示方式取打开页面的用户自己的个人配置（明细区右上角"Tab / 堆叠"），用例不切换（别人可能正用同一个账号）。
 * 页签方式时点开这个明细的页签；堆叠方式时各明细上下排列，不用点。
 */
export async function showDetail(page: Page, title: string) {
  const tab = page.locator('.generic-page__detail-bar .n-tabs-tab', { hasText: title });
  if (await tab.count()) await tab.click();
}

/** 选中主表这一行（点左侧固定区的单据号），等明细区显示这张单据 */
export async function selectRow(page: Page, rowId: string, keyColumn = 'DOCID') {
  const id = masterGrid(page).locator(
    `.ag-pinned-left-cols-container .ag-row[row-id="${rowId}"] [col-id="${keyColumn}"]`
  );
  await id.click();
  await expect(masterGrid(page).locator(`.ag-row-selected[row-id="${rowId}"]`).first()).toBeVisible();
  await expect(page.locator('.generic-page__empty')).toBeHidden();
}

/** 横向滚动，直到这一列出现在表格里（AG Grid 只渲染视野内的列；宽视口下一般不用滚） */
export async function scrollToColumn(grid: Locator, column: string) {
  await grid
    .locator('.ag-body-horizontal-scroll-viewport')
    .first()
    .evaluate(async (el, col) => {
      const root = el.closest('.ag-root-wrapper') as HTMLElement;
      const shown = () => root.querySelector(`.ag-header-cell[col-id="${col}"]`);
      const frame = () =>
        new Promise(resolve => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        });
      // 视野内渲染出的列：滚动后它变了，说明表格已按新位置画完
      const rendered = () =>
        Array.from(root.querySelectorAll('.ag-header-row-column .ag-header-cell[col-id]'))
          .map(c => c.getAttribute('col-id'))
          .join();
      for (let left = 0; !shown() && left <= el.scrollWidth; left += el.clientWidth) {
        const [before, from] = [rendered(), el.scrollLeft];
        el.scrollLeft = left;
        const moved = el.scrollLeft !== from;
        // 逐段滚，每段等表格按新位置画完再看（机器忙时一帧画不完，最多等 10 次两帧）；位置没变就不用等
        if (moved) {
          for (let i = 0; i < 10 && !shown() && rendered() === before; i += 1)
            // eslint-disable-next-line no-await-in-loop
            await frame();
          // 列变了以后再等两帧，免得只画了一部分
          // eslint-disable-next-line no-await-in-loop
          if (!shown()) await frame();
        }
      }
    }, column);
}

/** 按 row-id 和 col-id 取格子（列不在视野内时先横向滚过去） */
export async function cell(grid: Locator, rowId: string, column: string): Promise<Locator> {
  const found = grid.locator(`.ag-row[row-id="${rowId}"] [col-id="${column}"]`).first();
  if (!(await found.count())) await scrollToColumn(grid, column);
  await expect(found).toBeVisible();
  return found;
}

/** 表头中有没有这一列：从左到右横向滚一遍找（AG Grid 只渲染视野内的列），找完滚回最左边 */
export async function headerShown(grid: Locator, column: string): Promise<boolean> {
  return grid
    .locator('.ag-body-horizontal-scroll-viewport')
    .first()
    .evaluate(async (el, col) => {
      const root = el.closest('.ag-root-wrapper') as HTMLElement;
      const found = () => Boolean(root.querySelector(`.ag-header-cell[col-id="${col}"]`));
      const frame = () =>
        new Promise(resolve => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        });
      let seen = found();
      for (let left = 0; left <= el.scrollWidth && !seen; left += el.clientWidth) {
        el.scrollLeft = left;
        // 每段等表格画完再看（机器忙时一帧画不完，最多等 5 次两帧）
        for (let i = 0; i < 5 && !seen; i += 1) {
          // eslint-disable-next-line no-await-in-loop
          await frame();
          seen = found();
        }
      }
      el.scrollLeft = 0;
      return seen;
    }, column);
}

export async function cellText(grid: Locator, rowId: string, column: string) {
  return ((await (await cell(grid, rowId, column)).textContent()) ?? '').trim();
}

const EDITOR = '.ag-cell-inline-editing, .ag-popup-editor';

/** 双击这一格，全选后输入新值（空串为清空），回车 */
export async function edit(page: Page, target: Locator, value: string) {
  await target.dblclick();
  await expect(page.locator(EDITOR).first()).toBeVisible();
  await page.keyboard.press('Control+A');
  if (value) await page.keyboard.type(value);
  else await page.keyboard.press('Backspace');
  await page.keyboard.press('Enter');
  await expect(page.locator(EDITOR)).toHaveCount(0);
}

/** 双击这一格能不能进入编辑（进入了就按 Escape 取消，不改值） */
export async function canEdit(page: Page, target: Locator) {
  await target.dblclick();
  await nextFrame(page);
  const editing = (await page.locator(EDITOR).count()) > 0;
  if (editing) {
    await page.keyboard.press('Escape');
    await expect(page.locator(EDITOR)).toHaveCount(0);
  }
  return editing;
}

/** 命令结果（C04）中用例要看的部分 */
export type CommandResult = {
  outcome: string;
  requestKey?: string;
  rows: Row[];
  idMap: Record<string, string>;
  approvals: Array<{ approvalId: string; flows: string[] }>;
};

/** 点工具栏"保存"，返回命令结果 */
export async function save(page: Page): Promise<CommandResult> {
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/commands') && r.request().method() === 'POST'),
    toolbar(page).getByRole('button', { name: '保存', exact: true }).click()
  ]);
  return response.json();
}

/** 点一个工具栏按钮并等它提交的命令，返回命令结果 */
export async function runButton(page: Page, label: string): Promise<CommandResult> {
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/commands') && r.request().method() === 'POST'),
    toolbar(page).getByRole('button', { name: label, exact: true }).click()
  ]);
  return response.json();
}

/** 页面顶部的提示（naive-ui 的 message）中出现这段文字 */
export async function toast(page: Page, text: string | RegExp) {
  await expect(page.locator('.n-message__content').filter({ hasText: text }).first()).toBeVisible();
}

/** 表格底部汇总行各格的文字（col-id → 文字） */
export async function summary(grid: Locator) {
  const row = grid.locator('.ag-floating-bottom .ag-row');
  await expect(row.first()).toBeVisible();
  return row.evaluateAll(rows => {
    const out: Record<string, string> = {};
    for (const r of rows)
      for (const c of Array.from(r.querySelectorAll('.ag-cell'))) {
        const id = c.getAttribute('col-id');
        if (id && !(id in out)) out[id] = (c.textContent ?? '').trim();
      }
    return out;
  });
}

/** 表格里某一行渲染出来的全部格（col-id → 文字，左固定区和中间区） */
export async function rowTexts(grid: Locator, rowId: string) {
  return grid.locator(`.ag-row[row-id="${rowId}"]`).evaluateAll(rows => {
    const out: Record<string, string> = {};
    for (const r of rows)
      for (const c of Array.from(r.querySelectorAll('.ag-cell'))) {
        const id = c.getAttribute('col-id');
        if (id) out[id] = (c.textContent ?? '').trim();
      }
    return out;
  });
}

/** 浏览器控制台消息（类型、原文），从调用时开始记 */
export function watchConsole(page: Page) {
  const messages: Array<{ type: string; text: string }> = [];
  page.on('console', (msg: ConsoleMessage) => messages.push({ type: msg.type(), text: msg.text() }));
  page.on('pageerror', error => messages.push({ type: 'pageerror', text: String(error) }));
  return messages;
}

/** 关闭对话框时 naive-ui 的两条报错（NModal 里的 NCard 用 v-if，关闭时卡片先被移除） */
export const DIALOG_SLOT_WARNINGS = /\[naive\/getFirstSlotVNode\]|\[naive\/modal\]: default slot is empty/;

/** 打开顶栏铃铛的"消息中心"，返回含这段文字的通知 */
export async function notice(page: Page, text: string) {
  await page.locator('header button:has(.n-badge)').first().click();
  const drawer = page.locator('.n-drawer');
  await expect(drawer.getByText('消息中心')).toBeVisible();
  return drawer.locator('.notice-item', { hasText: text }).first();
}

/** 这个页面经实时连接（`/ws`，C10）收到的事件 */
export function realtimeEvents(page: Page) {
  const events: Array<{ topic: string; payload: Record<string, string> }> = [];
  page.on('websocket', socket => {
    if (!socket.url().endsWith('/ws')) return;
    socket.on('framereceived', frame => {
      try {
        const message = JSON.parse(String(frame.payload));
        if (message.topic) events.push(message);
      } catch {
        // 不是 JSON 的帧不记
      }
    });
  });
  return events;
}

/** 收到了链接为 `link` 的站内通知（`passed` 时只算标题以"已通过"结尾的） */
export const noticed = (events: ReturnType<typeof realtimeEvents>, link: string, passed = false) =>
  events.some(
    e => e.topic === 'notification' && e.payload.link === link && (!passed || e.payload.title.endsWith('已通过'))
  );

/** 待办中找到这条审批（来源单据号开头）并打开详情 */
export async function openTodo(page: Page, recordKey: string, approvalId: string) {
  await openMenu(page, '待办');
  await page.waitForURL('**/approval');
  const row = page
    .locator('.approval-todo-page .ag-center-cols-container .ag-row', { hasText: `${recordKey}（` })
    .first();
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: '处理' }).click();
  await page.waitForURL(`**/approval/${approvalId}`);
  const detail = page.locator('.approval-detail-page');
  await expect(detail.getByRole('button', { name: '通过' })).toBeVisible();
  return detail;
}

/** 审批详情页点"通过"，等提示和状态 */
export async function passInDetail(page: Page, detail: Locator) {
  await detail.getByRole('button', { name: '通过' }).click();
  await toast(page, '本级审批已提交');
  await expect(detail.locator('.approval-status')).toContainText('已通过');
}
