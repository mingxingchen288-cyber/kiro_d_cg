/**
 * 端到端用例共用：登录、打开成本核算并选中成本单、AG Grid 横向滚到某一格、经开发服务器代理调用后端接口、
 * 收集本次运行提交的命令和发起的审批（结束时由 backend/tests/e2e/cleanup.py 删掉这些平台记录）。
 */
import { spawnSync } from 'node:child_process';
import process from 'node:process';
import { type Locator, type Page, type Response, expect } from '@playwright/test';

/** 开发服务器的地址，写请求的 Origin（后端的 PLATFORM_ALLOWED_ORIGINS 要包含它） */
export const ORIGIN = `http://localhost:${process.env.E2E_FRONTEND_PORT ?? '9527'}`;
/** 开发服务器上后端接口的代理前缀（VITE_HTTP_PROXY=Y） */
const API = '/proxy-default';

export const ADMIN = { username: 'admin', password: 'admin123..' };
export const ACCOUNTANT = { username: 'chengben01', password: 'Abc123..', userId: '88' };

export async function login(page: Page, user: { username: string; password: string } = ADMIN) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(user.username);
  await page.getByPlaceholder('请输入密码').fill(user.password);
  await page.getByRole('button', { name: '确认' }).click();
  await page.waitForURL('**/home');
}

export const masterGrid = (page: Page) => page.getByTestId('master-grid');
export const detailGrid = (page: Page, entity: string) => page.getByTestId(`detail-${entity}`);

/** AG Grid 只渲染视野内的列：像用户拖动横向滚动条一样，逐段向右滚到这一格出现 */
export async function cell(grid: Locator, rowId: string, column: string): Promise<Locator> {
  const selector = `.ag-row[row-id="${rowId}"] [col-id="${column}"]`;
  await grid.locator('.ag-body-horizontal-scroll-viewport').evaluate(async (el, sel) => {
    const root = el.closest('.ag-root-wrapper') as HTMLElement;
    if (root.querySelector(sel)) return;
    for (let left = 0; left < 20_000 && !root.querySelector(sel); left += 300) {
      el.scrollLeft = left;
      // eslint-disable-next-line no-await-in-loop
      await new Promise(resolve => {
        setTimeout(resolve, 60);
      });
    }
  }, selector);
  const found = grid.locator(selector).first();
  await expect(found).toBeVisible();
  return found;
}

export async function cellText(grid: Locator, rowId: string, column: string) {
  return ((await (await cell(grid, rowId, column)).textContent()) ?? '').trim();
}

/** 双击这一格，全选后输入新值，回车 */
export async function typeInto(page: Page, target: Locator, value: string) {
  await target.dblclick();
  await page.keyboard.press('Control+A');
  await page.keyboard.type(value);
  await page.keyboard.press('Enter');
}

/** 打开成本核算（通用页面 /page/COST_PINGGU），选中一张成本单，等原辅料明细出现；明细为页签时切到"原料/辅料" */
export async function openCost(page: Page, docId: string, materialRow: string) {
  await page.goto('/page/COST_PINGGU');
  const id = masterGrid(page).locator(`.ag-pinned-left-cols-container .ag-row[row-id="${docId}"] [col-id="DOCID"]`);
  await expect(id).toBeVisible({ timeout: 30_000 });
  await id.click();
  const tab = page.locator('.n-tabs-tab', { hasText: '原料/辅料' });
  if (await tab.count()) await tab.click();
  await expect(detailGrid(page, 'COST_MATERIAL').locator(`.ag-row[row-id="${materialRow}"]`).first()).toBeVisible({
    timeout: 30_000
  });
}

/** 经开发服务器代理调用后端接口，带这个页面的会话 Cookie；写请求带 CSRF 令牌（外壳存在 sessionStorage）和 Origin */
// eslint-disable-next-line max-params -- 页面、方法、路径、请求体，与一次 HTTP 请求一一对应
export async function api(page: Page, method: 'GET' | 'POST' | 'PUT', path: string, body?: unknown) {
  const token = await page.evaluate(() => {
    const key = Object.keys(sessionStorage).find(k => k.endsWith('shell-session'));
    return key ? (JSON.parse(sessionStorage.getItem(key) ?? '{}').csrfToken as string) : '';
  });
  const response = await page.request.fetch(`${API}${path}`, {
    method,
    data: body,
    headers: { Origin: ORIGIN, ...(method === 'GET' ? {} : { 'X-CSRF-Token': token }) }
  });
  const text = await response.text();
  return { status: response.status(), body: text ? JSON.parse(text) : null };
}

/** 表头中有没有这一列：像用户拖动横向滚动条一样从左滚到右找（AG Grid 只渲染视野内的列），找完滚回最左边 */
export async function headerShown(grid: Locator, column: string): Promise<boolean> {
  return grid.locator('.ag-body-horizontal-scroll-viewport').evaluate(async (el, col) => {
    const root = el.closest('.ag-root-wrapper') as HTMLElement;
    const found = () => Boolean(root.querySelector(`.ag-header-cell[col-id="${col}"]`));
    let seen = found();
    for (let left = 0; left <= el.scrollWidth && !seen; left += 300) {
      el.scrollLeft = left;
      // eslint-disable-next-line no-await-in-loop
      await new Promise(resolve => {
        setTimeout(resolve, 60);
      });
      seen = found();
    }
    el.scrollLeft = 0;
    return seen;
  }, column);
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

/** 本次运行提交的命令（请求键）和发起的审批，结束时删掉它们产生的平台记录 */
export class Trail {
  readonly keys = new Set<string>();
  readonly approvals = new Set<string>();

  /** 记下这个页面上命令、通过、驳回的结果 */
  watch(page: Page) {
    page.on('response', (response: Response) => {
      const url = response.url();
      if (
        response.request().method() !== 'POST' ||
        !/\/api\/(commands|approvals\/\d+\/(pass|reject|withdraw))$/.test(url)
      )
        return;
      response
        .json()
        .then(result => this.note(result))
        .catch(() => undefined);
    });
  }

  note(result: { requestKey?: string; approvals?: Array<{ approvalId: string }> } | null) {
    if (result?.requestKey) this.keys.add(result.requestKey);
    for (const approval of result?.approvals ?? []) this.approvals.add(approval.approvalId);
  }

  /** backend/tests/e2e/cleanup.py：删掉命令记录、投递、站内通知和审批记录（业务数据由用例自己改回） */
  clean() {
    const args = ['run', 'python', '-m', 'tests.e2e.cleanup', '--keys', [...this.keys].join(',')];
    args.push('--approvals', [...this.approvals].join(','));
    const done = spawnSync('uv', args, {
      cwd: '../backend',
      encoding: 'utf8',
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
    });
    // eslint-disable-next-line no-console
    console.log(done.stdout.trim(), done.stderr.trim().split('\n').slice(-3).join('\n'));
    expect(done.status, done.stderr).toBe(0);
  }
}
