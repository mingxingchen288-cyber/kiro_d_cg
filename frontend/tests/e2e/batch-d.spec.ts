/**
 * T-AS-7 批次 D（真实联调，浏览器 → 开发服务器 → 后端 → d_cg）。成本核算页 /page/COST_PINGGU，成本单 2550。
 *
 * 1. 保存后不整页刷新、页面与数据库一致；同一单据的前端预览与后端计算按 C01 一致：admin 把 206324 预胶化淀粉的每片含量
 *    15 → 16，页面按 Worker 的预览显示每批成本 200；保存后 window 上的标记和主表表格的 DOM 元素都还在（没有整页刷新、
 *    没有重建表格），页面显示的值与后端重新读出的单据相同；预览的计算字段与命令结果中后端算出的值按 C01 第 3 节一致
 *    （后端写入前按 WP-15 保留 8 位小数，所以预览值先按 WP-15 处理再比较）。最后改回 15。
 * 2. 管理员保存配置后，已打开的页面无需刷新即生效：chengben01 开着成本核算；admin 保存页面配置把主表"产品英文名"列
 *    设为不显示，chengben01 的页面上这一列随即消失、页面没有刷新；改回后这一列又出现。（页面配置的列宽用 initialWidth，
 *    已打开的表格不跟着变，FP-08、FP-09，所以用列的显示与否来看配置是否生效。）
 * 3. 复制成本单 2550：只勾选原辅料中的聚维酮K30、玉米淀粉两行，主表不勾"备注""年需求量"，明细不勾"额外投料量""备注"，
 *    包材一行不勾；保存后新单据只有这两行明细、没有包材，没勾的字段为空，勾了的字段与 2550 相同，每批数量、每批成本、
 *    主表每批辅料成本为后端按新单据重算的值。最后删掉新单据。
 * 4. 停用账号后浏览器立即回到登录页：chengben01 开着成本核算，admin 停用它，chengben01 的页面不用任何操作就回到登录页；
 *    恢复启用后能重新登录。
 * 5. 在浏览器中完成审批（C06 7.8 样例一，d_cg 的 COST_TO_GOODS 只有第 1 级）：chengben01 把 206323 聚维酮K30 的单价
 *    75 → 90 保存，提示已提交审批、单价仍显示 75.00，再双击单价弹出审批进度；admin 的铃铛不刷新就多一条通知，在待办中
 *    打开详情（单价 75.00 → 90.00）并通过；chengben01 的铃铛收到"已通过"。最后经接口把单价改回 75（再走一次审批）。
 *
 * 运行前：后端（E2E_BACKEND_PORT）的 PLATFORM_ALLOWED_ORIGINS 包含 http://localhost:<E2E_FRONTEND_PORT>。
 * 结束时用 backend/tests/e2e/cleanup.py 删掉本次的命令记录、投递、站内通知和审批记录。
 */
import { type Browser, type Page, expect, test } from '@playwright/test';
import { numbersConsistent } from '../../src/contracts/decimal-text';
import { formatScale } from '../../src/modules/page/fields';
import {
  ACCOUNTANT,
  Trail,
  api,
  cell,
  cellText,
  detailGrid,
  headerShown,
  login,
  masterGrid,
  openCost,
  realtimeEvents,
  typeInto
} from './support';

const DOCID = '2550';
const K30 = '206323';
const PREGEL = '206324';
const CORN = '206326';
const trail = new Trail();

test.afterAll(() => trail.clean());

type Row = { entity: string; rowKey?: string; values: Record<string, string | boolean | null> };
type ViewField = { name: string; scale: number | null; calculated: boolean };

/** 在页面加载前包一层 Worker：记下每次求值的请求和结果（C07 第 5 节的消息） */
function captureCalc() {
  const NativeWorker = window.Worker;
  const calls: Array<{ request: string; result: string | null }> = [];
  (window as unknown as { e2eCalc: typeof calls }).e2eCalc = calls;
  window.Worker = class extends NativeWorker {
    constructor(url: string | URL, options?: WorkerOptions) {
      super(url, options);
      const sent = new Map<number, string>();
      const post = this.postMessage.bind(this);
      this.postMessage = ((message: { id?: number; type?: string; request?: string }, transfer?: Transferable[]) => {
        if (message?.type === 'evaluate' && message.id !== undefined) sent.set(message.id, message.request ?? '');
        return transfer ? post(message, transfer) : post(message);
      }) as Worker['postMessage'];
      this.addEventListener('message', ({ data }: MessageEvent<{ id: number; ok: boolean; result?: string }>) => {
        if (!sent.has(data.id)) return;
        calls.push({ request: sent.get(data.id)!, result: data.ok ? (data.result ?? null) : null });
        sent.delete(data.id);
      });
    }
  };
}

/** WP-15：最多保留 8 位小数，按第 9 位四舍五入（负数按绝对值） */
function wp15(text: string) {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return text;
  const [, sign, integer, fraction = ''] = match;
  if (fraction.length <= 8) return text;
  const digits = BigInt(integer + fraction.slice(0, 8)) + (Number(fraction[8]) >= 5 ? 1n : 0n);
  const padded = digits.toString().padStart(9, '0');
  return `${sign}${padded.slice(0, -8)}.${padded.slice(-8)}`;
}

async function save(page: Page) {
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/commands') && r.request().method() === 'POST'),
    page.getByRole('button', { name: '保存', exact: true }).click()
  ]);
  return response.json();
}

async function newPage(browser: Browser) {
  const context = await browser.newContext();
  const page = await context.newPage();
  trail.watch(page);
  return page;
}

// ---------------------------------------------------------------- 1

test('保存后不整页刷新、页面与数据库一致；前端预览与后端计算按 C01 一致', async ({ page }) => {
  trail.watch(page);
  await page.addInitScript(captureCalc);
  await login(page);
  await openCost(page, DOCID, PREGEL);
  const grid = detailGrid(page, 'COST_MATERIAL');
  const before = (await api(page, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body;
  const original = before.details.COST_MATERIAL.find((r: Row) => r.rowKey === PREGEL).values.PER_HL as string;
  expect(original).toBe('15');
  // 整页刷新会丢掉 window 上的标记；重建表格会换掉表格的 DOM 元素
  await page.evaluate(() => {
    (window as unknown as { e2eKept: string }).e2eKept = 'kept';
  });
  await masterGrid(page)
    .locator('.ag-root-wrapper')
    .evaluate(el => {
      (el as unknown as { e2eKept: string }).e2eKept = 'kept';
    });
  try {
    await typeInto(page, await cell(grid, PREGEL, 'PER_HL'), '16');
    await expect(await cell(grid, PREGEL, 'COST_BATCH')).toHaveText('200'); // 本地预览算出的每批成本
    const calls = await page.evaluate(
      () => (window as unknown as { e2eCalc: Array<{ result: string | null }> }).e2eCalc
    );
    const preview = JSON.parse(calls.findLast(c => c.result?.includes(`"${PREGEL}"`))!.result!) as {
      rows: Array<{ entity: string; rowKey?: string; computed: Record<string, string | null> }>;
    };
    const result = await save(page);
    await expect(page.getByText('已保存')).toBeVisible();
    expect(result.outcome).toBe('saved');
    expect(await page.evaluate(() => (window as unknown as { e2eKept?: string }).e2eKept)).toBe('kept');
    expect(
      await masterGrid(page)
        .locator('.ag-root-wrapper')
        .evaluate(el => (el as unknown as { e2eKept?: string }).e2eKept)
    ).toBe('kept');

    // 预览与后端：命令结果中的行（本次写入的明细和重算的主表）每个计算字段都按 C01 第 3 节比较
    const compared: string[] = [];
    for (const row of result.rows as Row[]) {
      const previewed = preview.rows.find(p => p.entity === row.entity && p.rowKey === row.rowKey);
      expect(previewed, `${row.entity} ${row.rowKey} 没有预览结果`).toBeTruthy();
      for (const [field, value] of Object.entries(previewed!.computed)) {
        const backend = row.values[field] as string | null;
        expect(
          numbersConsistent(value === null ? null : wp15(value), backend),
          `${field}：预览 ${value}，后端 ${backend}`
        ).toBe(true);
        compared.push(`${row.entity}.${field} ${value} ${backend}`);
      }
    }
    expect(compared.length).toBeGreaterThan(10);
    // eslint-disable-next-line no-console
    console.log(`预览与后端（字段 预览值 后端值）：\n${compared.join('\n')}`);

    // 页面与数据库：后端重新读出的单据，按页面视图的小数位显示，与页面上的格子相同
    const view = (await api(page, 'GET', '/api/pages/COST_PINGGU/view')).body;
    const record = (await api(page, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body;
    type Shown = { region: { fields: ViewField[] }; on: ReturnType<typeof masterGrid>; row: Row; names: string[] };
    const shown = async ({ region, on, row, names }: Shown) => {
      for (const name of names) {
        const field = region.fields.find(f => f.name === name)!;
        const expected = formatScale(String(row.values[name] ?? ''), field.scale);
        // 逐格横向滚动后读取，按顺序进行
        // eslint-disable-next-line no-await-in-loop
        expect(await cellText(on, row.rowKey!, name), name).toBe(expected);
      }
    };
    const materialRow = record.details.COST_MATERIAL.find((r: Row) => r.rowKey === PREGEL);
    expect(materialRow.values.PER_HL).toBe('16');
    await shown({ region: view.details[0], on: grid, row: materialRow, names: ['PER_HL', 'BATCH_QTY', 'COST_BATCH'] });
    await shown({
      region: view.master,
      on: masterGrid(page),
      row: { ...record.master, rowKey: DOCID },
      names: ['TOTAL_FL', 'TOTAL_COST', 'COST_PERBOX', 'JGF_BATCH']
    });
  } finally {
    const now = (await api(page, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body;
    if (now.details.COST_MATERIAL.find((r: Row) => r.rowKey === PREGEL).values.PER_HL !== original) {
      const restored = await api(page, 'POST', '/api/commands', {
        requestKey: crypto.randomUUID(),
        page: 'COST_PINGGU',
        operation: 'COST_PINGGU.save',
        params: {},
        documents: [
          {
            entity: 'COST_PINGGU',
            master: { op: 'none', rowKey: DOCID },
            details: [{ entity: 'COST_MATERIAL', op: 'modify', rowKey: PREGEL, changes: { PER_HL: original } }]
          }
        ]
      });
      trail.note(restored.body);
      expect(restored.body.outcome).toBe('saved');
    }
  }
  expect((await api(page, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body).toEqual(before);
});

// ---------------------------------------------------------------- 2

test('管理员保存配置后，已打开的成本核算页无需刷新即生效', async ({ browser }) => {
  const viewer = await newPage(browser);
  const events = realtimeEvents(viewer);
  await login(viewer, ACCOUNTANT);
  await viewer.goto('/page/COST_PINGGU');
  const grid = masterGrid(viewer);
  await expect(grid.locator('.ag-header-cell[col-id="GOODSNAME_EN"]')).toBeVisible({ timeout: 30_000 });
  await viewer.evaluate(() => {
    (window as unknown as { e2eKept: string }).e2eKept = 'kept';
  });

  const admin = await newPage(browser);
  await login(admin);
  const item = (await api(admin, 'GET', '/api/config/items/page/COST_PINGGU')).body;
  expect(item.content.master.fields.GOODSNAME_EN).toBeUndefined();
  const changed = structuredClone(item.content);
  changed.master.fields.GOODSNAME_EN = { visible: false };
  try {
    expect(
      (await api(admin, 'PUT', '/api/config/items/page/COST_PINGGU', { name: item.name, content: changed })).status
    ).toBe(200);
    // 经 WebSocket 收到 config.changed，重新读取页面视图，整张表都找不到这一列
    await expect.poll(() => events.some(e => e.topic === 'config.changed'), { timeout: 20_000 }).toBe(true);
    await expect.poll(() => headerShown(grid, 'GOODSNAME_EN'), { timeout: 20_000 }).toBe(false);
  } finally {
    const restored = await api(admin, 'PUT', '/api/config/items/page/COST_PINGGU', {
      name: item.name,
      content: item.content
    });
    expect(restored.status).toBe(200);
  }
  await expect.poll(() => headerShown(grid, 'GOODSNAME_EN'), { timeout: 20_000 }).toBe(true);
  const order = await grid
    .locator('.ag-header-row-column .ag-header-cell')
    .evaluateAll(cells => cells.map(c => c.getAttribute('col-id')));
  // eslint-disable-next-line no-console
  console.log(`改回后表头（视野内）：${order.join(', ')}`);
  expect(await viewer.evaluate(() => (window as unknown as { e2eKept?: string }).e2eKept)).toBe('kept');
  expect((await api(admin, 'GET', '/api/config/items/page/COST_PINGGU')).body.content).toEqual(item.content);
});

// ---------------------------------------------------------------- 3

/** 复制对话框中一组复选框：`labels` 中的每一项按 `checked` 勾选或取消（默认全选） */
async function choose(group: ReturnType<Page['locator']>, labels: string[], checked: boolean) {
  // 像用户一样逐个点，按顺序进行
  for (const label of labels) {
    const box = group.getByRole('checkbox', { name: label, exact: true });
    // eslint-disable-next-line no-await-in-loop
    await expect(box).toBeChecked();
    // eslint-disable-next-line no-await-in-loop
    if (!checked) await box.setChecked(false);
  }
}

/** 复制对话框中明细行的文字（CopyDialog.vue 的 rowLabel：除主键外前三个可见字段，按页面视图显示） */
function rowLabel(region: { primaryKey: string; fields: Array<ViewField & { visible: boolean }> }, row: Row) {
  return region.fields
    .filter(f => f.visible && f.name !== region.primaryKey)
    .slice(0, 3)
    .map(f => (row.values[f.name] === null ? '' : formatScale(String(row.values[f.name]), f.scale)))
    .filter(Boolean)
    .join(' / ');
}

test('复制成本单：只勾选部分明细行和字段，新单据只含这些行，未勾选的字段为空，计算字段为后端重算的值', async ({
  page
}) => {
  trail.watch(page);
  await login(page);
  await openCost(page, DOCID, K30);
  const source = (await api(page, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body;
  await page.getByRole('button', { name: '复制', exact: true }).click();
  const dialog = page.locator('.copy-dialog');
  await expect(dialog).toBeVisible();
  // 对话框中依次为：主表字段；原料/辅料的行、字段；包材的行、字段
  const groups = dialog.locator('.n-checkbox-group');
  await expect(groups).toHaveCount(5);
  const view = (await api(page, 'GET', '/api/pages/COST_PINGGU/view')).body;
  const [materials, packages] = view.details;
  await choose(groups.nth(0), ['备注', '年需求量'], false);
  const kept = source.details.COST_MATERIAL.filter((r: Row) => [K30, CORN].includes(r.rowKey!));
  const dropped = source.details.COST_MATERIAL.filter((r: Row) => ![K30, CORN].includes(r.rowKey!));
  await choose(
    groups.nth(1),
    kept.map((r: Row) => rowLabel(materials, r)),
    true
  );
  await choose(
    groups.nth(1),
    dropped.map((r: Row) => rowLabel(materials, r)),
    false
  );
  await choose(groups.nth(2), ['额外投料量', '备注'], false);
  await choose(
    groups.nth(3),
    source.details.COST_PACKAGE.map((r: Row) => rowLabel(packages, r)),
    false
  );
  await dialog.getByRole('button', { name: '确定' }).click();
  await expect(dialog).toBeHidden();

  const result = await save(page);
  await expect(page.getByText('已保存')).toBeVisible();
  expect(result.outcome).toBe('saved');
  const masterNew = (result.rows as Row[]).find(r => r.entity === 'COST_PINGGU' && r.rowKey !== DOCID)!;
  const newDoc = masterNew.rowKey!;
  try {
    const copied = (await api(page, 'GET', `/api/pages/COST_PINGGU/records/${newDoc}`)).body;
    const m = copied.master.values;
    // 没勾的字段为空；勾了的、可写的字段与 2550 相同
    expect([m.MEMO, m.ANNUAL_QTY]).toEqual([null, null]);
    for (const name of [
      'APEX_PL',
      'P_PERPACK',
      'S_PERBACK',
      'X_PERBACK',
      'YIELD',
      'PACKTYPE',
      'DOSAGE',
      'USESTATUS',
      'FMRATE'
    ])
      expect(m[name], name).toEqual(source.master.values[name]);
    // 明细只有勾选的两行，没有包材
    expect(copied.details.COST_PACKAGE).toEqual([]);
    const lines = copied.details.COST_MATERIAL as Row[];
    expect(
      lines.map(r => [r.values.GOODSID, r.values.PER_HL, r.values.PRICE, r.values.EXADD_MATER, r.values.MEMO])
    ).toEqual(kept.map((r: Row) => [r.values.GOODSID, r.values.PER_HL, r.values.PRICE, null, null]));
    // 计算字段为后端按新单据重算：每批数量 = 每片含量 × 批量 / 1000000，每批成本 = 每批数量 × 单价；没有原料，辅料合计不除以 1.13
    expect(lines.map(r => [r.values.BATCH_QTY, r.values.COST_BATCH])).toEqual([
      ['10', '750'],
      ['42.5', '935']
    ]);
    expect(m.TOTAL_FL).toBe('1685');
    expect(m.TOTAL_FL).not.toBe(source.master.values.TOTAL_FL);
  } finally {
    const removed = await api(page, 'POST', '/api/commands', {
      requestKey: crypto.randomUUID(),
      page: 'COST_PINGGU',
      operation: 'COST_PINGGU.save',
      params: {},
      documents: [{ entity: 'COST_PINGGU', master: { op: 'delete', rowKey: newDoc }, details: [] }]
    });
    trail.note(removed.body);
    expect(removed.body.outcome).toBe('saved');
  }
  expect((await api(page, 'GET', `/api/pages/COST_PINGGU/records/${newDoc}`)).status).toBe(404);
  expect((await api(page, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body).toEqual(source);
});

// ---------------------------------------------------------------- 4

test('停用账号后，浏览器立即回到登录页', async ({ browser }) => {
  const user = await newPage(browser);
  await login(user, ACCOUNTANT);
  await user.goto('/page/COST_PINGGU');
  await expect(masterGrid(user).locator('.ag-row').first()).toBeVisible({ timeout: 30_000 });

  const admin = await newPage(browser);
  await login(admin);
  const rows = (await api(admin, 'GET', `/api/admin/accounts?keyword=${ACCOUNTANT.username}`)).body.rows;
  const account = rows.find((r: { username: string }) => r.username === ACCOUNTANT.username);
  expect(account.enabled).toBe(true);
  const update = { displayName: account.displayName, departmentId: account.departmentId, roleCodes: account.roleCodes };
  try {
    expect(
      (await api(admin, 'PUT', `/api/admin/accounts/${account.userId}`, { ...update, enabled: false })).status
    ).toBe(200);
    await user.waitForURL('**/login**', { timeout: 15_000 }); // 收到 session.revoked，不用任何操作
    await expect(user.getByPlaceholder('请输入用户名')).toBeVisible();
  } finally {
    expect(
      (await api(admin, 'PUT', `/api/admin/accounts/${account.userId}`, { ...update, enabled: true })).status
    ).toBe(200);
  }
  await login(user, ACCOUNTANT);
  const after = (await api(admin, 'GET', `/api/admin/accounts?keyword=${ACCOUNTANT.username}`)).body.rows;
  expect(after.find((r: { username: string }) => r.username === ACCOUNTANT.username)).toEqual(account);
});

// ---------------------------------------------------------------- 5

/** 打开顶栏铃铛的"消息中心"，返回最上面（最新）的一条通知 */
async function newestNotice(page: Page) {
  await page.locator('header button:has(.n-badge)').first().click();
  const drawer = page.locator('.n-drawer');
  await expect(drawer.getByText('消息中心')).toBeVisible();
  return drawer.locator('.notice-item').first();
}

/** 经接口提交一次通过：指纹取自审批详情 */
async function passByApi(page: Page, approvalId: string) {
  const detail = (await api(page, 'GET', `/api/approvals/${approvalId}`)).body;
  const passed = await api(page, 'POST', `/api/approvals/${approvalId}/pass`, {
    requestKey: crypto.randomUUID(),
    fingerprint: detail.fingerprint,
    checkedRows: [],
    comment: '端到端用例：改回原单价',
    params: {}
  });
  trail.note(passed.body);
  expect(passed.body.outcome, JSON.stringify(passed.body)).toBe('approvalProcessed');
}

test('在浏览器中完成审批：改单价提交审批、冻结、通知，管理员在待办中打开详情并通过', async ({ browser }) => {
  const admin = await newPage(browser);
  const adminEvents = realtimeEvents(admin);
  await login(admin);
  const before = (await api(admin, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body;
  const original = before.details.COST_MATERIAL.find((r: Row) => r.rowKey === K30).values.PRICE as string;
  expect(original).toBe('75');

  const user = await newPage(browser);
  const userEvents = realtimeEvents(user);
  await login(user, ACCOUNTANT);
  await openCost(user, DOCID, K30);
  const grid = detailGrid(user, 'COST_MATERIAL');
  let approvalId = '';
  try {
    await typeInto(user, await cell(grid, K30, 'PRICE'), '90');
    await expect(await cell(grid, K30, 'COST_BATCH')).toHaveText('900'); // 预览
    const submitted = await save(user);
    expect(submitted.outcome).toBe('approvalSubmitted');
    approvalId = submitted.approvals[0].approvalId;
    await expect(user.getByText(/已提交审批/).first()).toBeVisible({ timeout: 30_000 });
    await expect(await cell(grid, K30, 'PRICE')).toHaveText('75.00'); // 审批结束前显示正式数据
    await (await cell(grid, K30, 'PRICE')).dblclick();
    const progress = user.locator('.approval-progress');
    await expect(progress.getByText('审批编号')).toBeVisible({ timeout: 15_000 });
    await expect(progress).toContainText(approvalId);
    await progress.getByRole('button', { name: '关闭' }).click();
    expect(await grid.locator('.ag-cell-inline-editing').count()).toBe(0);

    // admin 的页面不刷新，经实时连接收到这条审批的通知，铃铛的消息中心最上面就是它
    const link = `/approval/${approvalId}`;
    await expect
      .poll(() => adminEvents.some(e => e.topic === 'notification' && e.payload.link === link), { timeout: 20_000 })
      .toBe(true);
    await expect(await newestNotice(admin)).toContainText(`业务单据为${DOCID}的审批`);
    await admin.keyboard.press('Escape');
    // 待办中打开详情
    await admin.locator('header button').first().click();
    await admin.locator('.n-menu-item-content', { hasText: '待办' }).click();
    await admin.waitForURL('**/approval');
    await admin.mouse.click(1200, 450);
    const row = admin
      .locator('.approval-todo-page .ag-center-cols-container .ag-row', { hasText: `${DOCID}（` })
      .first();
    await expect(row).toBeVisible({ timeout: 30_000 });
    await row.getByRole('button', { name: '处理' }).click();
    await admin.waitForURL(`**${link}`);
    const detail = admin.locator('.approval-detail-page');
    await expect(detail.getByRole('button', { name: '通过' })).toBeVisible({ timeout: 30_000 });
    await expect(detail).toContainText('75.00');
    await expect(detail).toContainText('90.00');
    await detail.getByRole('button', { name: '通过' }).click();
    await expect(admin.getByText('本级审批已提交').first()).toBeVisible({ timeout: 60_000 });
    await expect(detail.locator('.approval-status')).toContainText('已通过');

    // chengben01 的页面经实时连接收到"已通过"，铃铛的消息中心最上面就是它；数据库中单价为 90
    await expect
      .poll(
        () =>
          userEvents.some(
            e => e.topic === 'notification' && e.payload.link === link && e.payload.title.endsWith('已通过')
          ),
        {
          timeout: 20_000
        }
      )
      .toBe(true);
    await expect(await newestNotice(user)).toContainText(`业务单据为${DOCID}的审批已通过`);
    await user.keyboard.press('Escape');
    const after = (await api(admin, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body;
    const k30 = after.details.COST_MATERIAL.find((r: Row) => r.rowKey === K30).values;
    expect([k30.PRICE, k30.COST_BATCH]).toEqual(['90', '900']);
  } finally {
    // 改回原单价：75 与执行价 90 不同，再走一次审批（经接口）
    const now = (await api(admin, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body;
    if (now.details.COST_MATERIAL.find((r: Row) => r.rowKey === K30).values.PRICE !== original) {
      const back = await api(user, 'POST', '/api/commands', {
        requestKey: crypto.randomUUID(),
        page: 'COST_PINGGU',
        operation: 'COST_PINGGU.save',
        params: {},
        documents: [
          {
            entity: 'COST_PINGGU',
            master: { op: 'none', rowKey: DOCID },
            details: [{ entity: 'COST_MATERIAL', op: 'modify', rowKey: K30, changes: { PRICE: original } }]
          }
        ]
      });
      trail.note(back.body);
      expect(back.body.outcome).toBe('approvalSubmitted');
      await passByApi(admin, back.body.approvals[0].approvalId);
    } else if (approvalId) {
      const state = (await api(admin, 'GET', `/api/approvals/${approvalId}`)).body;
      if (state.status === 'pending') {
        const rejected = await api(admin, 'POST', `/api/approvals/${approvalId}/reject`, {
          requestKey: crypto.randomUUID(),
          comment: '端到端用例中途失败，驳回'
        });
        trail.note(rejected.body);
      }
    }
  }
  expect((await api(admin, 'GET', `/api/pages/COST_PINGGU/records/${DOCID}`)).body).toEqual(before);
});
