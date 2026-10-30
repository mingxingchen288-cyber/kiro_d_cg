/**
 * T-AS-7 样例二：在浏览器中完成 C06 7.9、7.10 两个审批场景（真实联调，浏览器 → 开发服务器 → 后端 → d_cg）。
 * 发起人 jishu01（部门 18 技术中心，角色"技术中心"），审批人 admin。测试数据自己建、自己删：
 * - 成本单由 admin 经接口新建、删除；ERP 物料（模拟 ERP 同步写入）和液体成本单平台写不了，由
 *   `backend/tests/e2e/sample_two.py` 直接写表、删除（见那里的说明）。
 *
 * 1. 7.9：admin 新建一张"评估中"的成本单（硬脂酸镁客户指定、玉米淀粉不是）；jishu01 在成本核算页取消硬脂酸镁的
 *    "客户指定"并保存，提示已提交审批；admin 不刷新就收到通知，在待办中打开详情（客户指定 是 → 否）并通过；
 *    jishu01 收到"已通过"，单据中这一行不再是客户指定。
 * 2. 7.10：ERP 物料（参考价格 10，执行价为空）、含它的两张成本单 D1、D2 和一张液体成本单。jishu01 打开物料清单及成本，
 *    这一行是 ERP 行（绿底，物料名称不能编辑），把单价改成 12 并保存，提示已提交审批；admin 在待办中打开详情，
 *    受影响单据"成本核算（原辅料）"有 D1、D2 两行，取消 D2 后 D2 恢复为 10.00，通过；D1 单价 12、金额 120，D2 不变，
 *    物料清单执行价 12，液体明细单价 12。
 *
 * 运行前：后端（E2E_BACKEND_PORT）的 PLATFORM_ALLOWED_ORIGINS 包含 http://localhost:<E2E_FRONTEND_PORT>。
 * 结束时用 backend/tests/e2e/cleanup.py 删掉本次的命令记录、投递、站内通知和审批记录。
 */
import { spawnSync } from 'node:child_process';
import process from 'node:process';
import { type Browser, type Page, expect, test } from '@playwright/test';
import { ADMIN, Trail, api, cell, detailGrid, login, masterGrid, realtimeEvents, typeInto } from './support';

const TECH = { username: 'jishu01', password: 'Jishu123..' };
const trail = new Trail();
/** 设了 E2E_SHOT_DIR 时把关键画面截图存到这个目录（验收证据） */
const SHOT_DIR = process.env.E2E_SHOT_DIR;

async function shot(page: Page, name: string) {
  if (SHOT_DIR) await page.screenshot({ path: `${SHOT_DIR}/${name}.png` });
}

test.afterAll(() => trail.clean());

type Row = { entity: string; rowKey?: string; values: Record<string, string | boolean | null> };
type Values = Record<string, string | boolean | null>;

/** backend/tests/e2e/sample_two.py：建、删 ERP 物料和液体成本单 */
function sampleData(...args: string[]) {
  const done = spawnSync('uv', ['run', 'python', '-m', 'tests.e2e.sample_two', ...args], {
    cwd: '../backend',
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  });
  expect(done.status, done.stderr).toBe(0);
  const lines = done.stdout.trim().split('\n');
  return JSON.parse(lines[lines.length - 1]);
}

async function newPage(browser: Browser) {
  const context = await browser.newContext();
  const page = await context.newPage();
  trail.watch(page);
  return page;
}

async function command(
  page: Page,
  documents: unknown[],
  target = { page: 'COST_PINGGU', operation: 'COST_PINGGU.save' }
) {
  const result = await api(page, 'POST', '/api/commands', {
    requestKey: crypto.randomUUID(),
    ...target,
    params: {},
    documents
  });
  trail.note(result.body);
  return result.body;
}

/** admin 经接口新建一张成本单（主表取 G5 用过的批量、包装规格等），返回主键和明细主键 */
async function createDocument(page: Page, doc: { memo: string; materials: Values[]; master?: Values }) {
  const { memo, materials, master = {} } = doc;
  const masterId = `tmp-${crypto.randomUUID()}`;
  const detailIds = materials.map(() => `tmp-${crypto.randomUUID()}`);
  const result = await command(page, [
    {
      entity: 'COST_PINGGU',
      master: {
        op: 'add',
        clientRowId: masterId,
        values: { MEMO: memo, APEX_PL: '1000000', P_PERPACK: '112', S_PERBACK: '80', YIELD: '93.94', ...master }
      },
      details: materials.map((values, i) => ({ entity: 'COST_MATERIAL', op: 'add', clientRowId: detailIds[i], values }))
    }
  ]);
  expect(result.outcome, JSON.stringify(result)).toBe('saved');
  return { docId: result.idMap[masterId] as string, rows: detailIds.map(id => result.idMap[id] as string) };
}

async function deleteDocuments(page: Page, docIds: string[]) {
  const result = await command(
    page,
    docIds.map(rowKey => ({ entity: 'COST_PINGGU', master: { op: 'delete', rowKey }, details: [] }))
  );
  expect(result.outcome, JSON.stringify(result)).toBe('saved');
}

async function save(page: Page) {
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/commands') && r.request().method() === 'POST'),
    page.getByRole('button', { name: '保存', exact: true }).click()
  ]);
  return response.json();
}

/** 表格像用户拖动竖向滚动条一样向下滚，直到这一行出现（服务端行模型按块加载） */
async function scrollToRow(page: Page, rowId: string) {
  const grid = masterGrid(page);
  await expect(grid.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 });
  await grid.locator('.ag-body-viewport').evaluate(async (el, id) => {
    const root = el.closest('.ag-root-wrapper') as HTMLElement;
    for (let top = 0; top < 2_000_000 && !root.querySelector(`.ag-row[row-id="${id}"]`); top += 300) {
      el.scrollTop = top;
      // eslint-disable-next-line no-await-in-loop
      await new Promise(resolve => {
        setTimeout(resolve, 120);
      });
    }
  }, rowId);
}

/** 打开成本核算并选中这张成本单（新建的单据排在最后，向下滚到它），明细为页签时切到"原料/辅料" */
async function openDocument(page: Page, docId: string, materialRow: string) {
  await page.goto('/page/COST_PINGGU');
  await scrollToRow(page, docId);
  await masterGrid(page).locator(`.ag-pinned-left-cols-container .ag-row[row-id="${docId}"] [col-id="DOCID"]`).click();
  const tab = page.locator('.n-tabs-tab', { hasText: '原料/辅料' });
  if (await tab.count()) await tab.click();
  await expect(detailGrid(page, 'COST_MATERIAL').locator(`.ag-row[row-id="${materialRow}"]`).first()).toBeVisible({
    timeout: 30_000
  });
}

/** 待办中找到这条审批（来源单据号开头）并打开详情 */
async function openTodo(page: Page, recordKey: string, approvalId: string) {
  await page.locator('header button').first().click();
  await page.locator('.n-menu-item-content', { hasText: '待办' }).click();
  await page.waitForURL('**/approval');
  await page.mouse.click(1200, 450);
  const row = page
    .locator('.approval-todo-page .ag-center-cols-container .ag-row', { hasText: `${recordKey}（` })
    .first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole('button', { name: '处理' }).click();
  await page.waitForURL(`**/approval/${approvalId}`);
  const detail = page.locator('.approval-detail-page');
  await expect(detail.getByRole('button', { name: '通过' })).toBeVisible({ timeout: 30_000 });
  return detail;
}

async function rejectIfPending(page: Page, approvalId: string) {
  if (!approvalId) return;
  const state = (await api(page, 'GET', `/api/approvals/${approvalId}`)).body;
  if (state?.status !== 'pending') return;
  const rejected = await api(page, 'POST', `/api/approvals/${approvalId}/reject`, {
    requestKey: crypto.randomUUID(),
    comment: '端到端用例中途失败，驳回'
  });
  trail.note(rejected.body);
}

const noticed = (events: Array<{ topic: string; payload: Record<string, string> }>, link: string, passed = false) =>
  events.some(
    e => e.topic === 'notification' && e.payload.link === link && (!passed || e.payload.title.endsWith('已通过'))
  );

// ---------------------------------------------------------------- 1：C06 7.9

test('7.9 技术中心取消客户指定：提交审批、管理员在待办中通过、发起人收到已通过', async ({ browser }) => {
  const admin = await newPage(browser);
  const adminEvents = realtimeEvents(admin);
  await login(admin, ADMIN);
  const stearate = (
    await api(admin, 'POST', '/api/lookups/costMaterialEffective/search', {
      keyword: '硬脂酸镁',
      startRow: 0,
      endRow: 50
    })
  ).body.rows.find((r: { values: Values }) => r.values.GOODSID === '115').values.ZX_PRICE as string;
  const starch = (
    await api(admin, 'POST', '/api/lookups/costMaterialEffective/search', {
      keyword: '玉米淀粉',
      startRow: 0,
      endRow: 50
    })
  ).body.rows.find((r: { values: Values }) => r.values.GOODSID === '310').values.ZX_PRICE as string;
  const { docId, rows } = await createDocument(admin, {
    memo: 'H5 浏览器样例二',
    materials: [
      { GOODSID: '115', PER_HL: '2.5', PRICE: stearate, CUSTOMER_SPECIFIED: true },
      { GOODSID: '310', PER_HL: '42.5', PRICE: starch }
    ],
    master: { USESTATUS: '评估中' }
  });
  const [specified] = rows;
  let approvalId = '';
  try {
    const tech = await newPage(browser);
    const techEvents = realtimeEvents(tech);
    await login(tech, TECH);
    await openDocument(tech, docId, specified);
    const grid = detailGrid(tech, 'COST_MATERIAL');
    const box = (await cell(grid, specified, 'CUSTOMER_SPECIFIED')).locator('input[type="checkbox"]');
    await expect(box).toBeChecked();
    await box.click();
    await expect(box).not.toBeChecked();
    const submitted = await save(tech);
    expect(submitted.outcome, JSON.stringify(submitted)).toBe('approvalSubmitted');
    expect(submitted.approvals[0].flows).toEqual(['TECH_CUSTOMER_MATERIAL']);
    approvalId = submitted.approvals[0].approvalId;
    await expect(tech.getByText(/已提交审批/).first()).toBeVisible({ timeout: 30_000 });
    await expect((await cell(grid, specified, 'CUSTOMER_SPECIFIED')).locator('input[type="checkbox"]')).toBeChecked();

    const link = `/approval/${approvalId}`;
    await expect.poll(() => noticed(adminEvents, link), { timeout: 20_000 }).toBe(true);
    const detail = await openTodo(admin, docId, approvalId);
    await expect(detail).toContainText('技术中心客指物料变更审批');
    await expect(detail).toContainText('是 → 否');
    await shot(admin, 'as7-79-detail');
    await detail.getByRole('button', { name: '通过' }).click();
    await expect(admin.getByText('本级审批已提交').first()).toBeVisible({ timeout: 60_000 });
    await expect(detail.locator('.approval-status')).toContainText('已通过');

    await expect.poll(() => noticed(techEvents, link, true), { timeout: 20_000 }).toBe(true);
    const after = (await api(admin, 'GET', `/api/pages/COST_PINGGU/records/${docId}`)).body;
    const values = after.details.COST_MATERIAL.map((r: Row) => [r.rowKey, r.values.CUSTOMER_SPECIFIED]);
    expect(values).toEqual([
      [specified, false],
      [rows[1], false]
    ]);
  } finally {
    await rejectIfPending(admin, approvalId);
    await deleteDocuments(admin, [docId]);
  }
  expect((await api(admin, 'GET', `/api/pages/COST_PINGGU/records/${docId}`)).status).toBe(404);
});

// ---------------------------------------------------------------- 2：C06 7.10

test('7.10 物料清单改价：ERP 行只能改单价，审批人取消一张成本单，通过后只更新勾选的成本单', async ({ browser }) => {
  const { goodsid } = sampleData('goods', '--price', '10');
  const admin = await newPage(browser);
  await login(admin, ADMIN);
  const created: string[] = [];
  let lq = { docid: '', dtlid: '' };
  let approvalId = '';
  try {
    const material = { GOODSID: goodsid, PER_HL: '10', PRICE: '10' };
    const d1 = await createDocument(admin, { memo: 'H5 浏览器样例三 D1', materials: [material] });
    created.push(d1.docId);
    const d2 = await createDocument(admin, { memo: 'H5 浏览器样例三 D2', materials: [material] });
    created.push(d2.docId);
    lq = sampleData('liquid', '--goods', goodsid, '--price', '10');

    const tech = await newPage(browser);
    await login(tech, TECH);
    await tech.goto('/page/GOODS_PRICE_MANAGE');
    const grid = masterGrid(tech);
    await expect(grid.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 });
    // 物料ID 列表头点两次（升序、降序），新增的物料主键最大，排在最前
    const target = grid.locator(`.ag-center-cols-container .ag-row[row-id="${goodsid}"]`);
    const header = grid.locator('.ag-header-cell[col-id="GOODSID"] .ag-header-cell-label');
    await header.click();
    await tech.waitForTimeout(1500);
    await header.click();
    await expect(target).toBeVisible({ timeout: 30_000 });
    await expect(target).toHaveCSS('background-color', 'rgb(230, 255, 237)'); // ERP 行绿底（旧 GRID_STYLE）
    await shot(tech, 'as7-710-goods-page');
    const name = await cell(grid, goodsid, 'GOODSNAME');
    await expect(name).toHaveText('H5联调辅料');
    await name.dblclick();
    expect(await grid.locator('.ag-cell-inline-editing').count()).toBe(0); // ERP 行的 ERP 列只读
    await tech.keyboard.press('Escape');
    await expect(await cell(grid, goodsid, 'ZX_PRICE')).toHaveText('10');
    await typeInto(tech, await cell(grid, goodsid, 'ZX_PRICE'), '12');
    const submitted = await save(tech);
    expect(submitted.outcome, JSON.stringify(submitted)).toBe('approvalSubmitted');
    expect(submitted.approvals[0].flows).toEqual(['GOODS_TO_COST']);
    approvalId = submitted.approvals[0].approvalId;
    await expect(tech.getByText(/已提交审批/).first()).toBeVisible({ timeout: 30_000 });
    await expect(await cell(grid, goodsid, 'ZX_PRICE')).toHaveText('10'); // 审批结束前显示正式数据

    const detail = await openTodo(admin, goodsid, approvalId);
    await expect(detail).toContainText('物料清单改价审批');
    await expect(detail.locator('.n-tabs-tab[data-name="GOODS_TO_COST:costMaterial"]')).toHaveText(
      '成本核算（原辅料）（2 条）'
    );
    await expect(detail.locator('.n-tabs-tab[data-name="GOODS_TO_COST:lqMaterial"]')).toHaveText(
      '液体成本核算（原辅料）（1 条）'
    );
    const affected = detail
      .locator('.approval-presentation-grid')
      .filter({ has: admin.getByLabel(`勾选 ${d2.rows[0]}`) });
    await expect(affected).toContainText('10.00 → 12.00');
    await admin.getByLabel(`勾选 ${d2.rows[0]}`).uncheck();
    await expect(detail.getByText('正在按勾选重新计算')).toHaveCount(0, { timeout: 30_000 });
    const d2Row = affected.locator('.ag-center-cols-container .ag-row', { hasText: d2.docId });
    await expect(d2Row).not.toContainText('→');
    await shot(admin, 'as7-710-detail-unchecked');
    await expect(affected.locator('.ag-center-cols-container .ag-row', { hasText: d1.docId })).toContainText(
      '10.00 → 12.00'
    );
    await detail.getByRole('button', { name: '通过' }).click();
    await expect(admin.getByText('本级审批已提交').first()).toBeVisible({ timeout: 60_000 });
    await expect(detail.locator('.approval-status')).toContainText('已通过');

    const price = async (docId: string) => {
      const record = (await api(admin, 'GET', `/api/pages/COST_PINGGU/records/${docId}`)).body;
      const values = record.details.COST_MATERIAL[0].values;
      return [values.PRICE, values.COST_BATCH];
    };
    expect(await price(d1.docId)).toEqual(['12', '120']);
    expect(await price(d2.docId)).toEqual(['10', '100']);
    expect(sampleData('show', '--goods', goodsid, '--lq-dtl', lq.dtlid)).toEqual({
      zxPrice: '12',
      lqPrice: '12',
      lqCostBatch: '50'
    });
  } finally {
    await rejectIfPending(admin, approvalId);
    if (created.length) await deleteDocuments(admin, created);
    sampleData('drop', '--goods', goodsid, '--lq', lq.docid, '--docs', created.join(','));
  }
});
