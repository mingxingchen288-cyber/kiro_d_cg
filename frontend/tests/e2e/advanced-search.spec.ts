/**
 * 高级查询（frontend-page FP-22，C05 v7 `searchable`，只读）：admin 打开成本核算点"高级查询"，对话框一打开就列出预置条件
 * （d_cg 页面视图中 `searchable` 的可见字段，seed 按旧系统 cost-pinggu 列配置的"查询"补上），填值、勾上即可查；
 * 客户ID 用客户 Lookup 选两个客户（运算符 IN），查出的单据只属于这两个客户。
 * 前提：seed 的 `searchable`（第 7 批 QS 组）已经主代理经配置接口写进 d_cg；没写时页面视图里没有预置条件，第一条用例失败。
 */
import type { Page } from './support';
import { expect, filterColumn, openPage, test, toolbar } from './support';

type ListBody = { rows: Array<{ rowKey: string; values: Record<string, string | null> }>; total: number };
type LookupBody = { rows: Array<{ values: Record<string, string | null> }>; total: number };

const dialog = (page: Page) => page.locator('.advanced-search');
const condition = (page: Page, key: string) => dialog(page).getByTestId(`condition-${key}`);
const listed = (page: Page) =>
  page.waitForResponse(r => r.url().endsWith('/api/pages/COST_PINGGU/rows') && r.request().method() === 'POST');

async function openSearch(page: Page) {
  await toolbar(page).getByRole('button', { name: '高级查询', exact: true }).click();
  await expect(dialog(page)).toBeVisible();
}

/** 点对话框的"查询"，返回这次列表请求和响应 */
async function runSearch(page: Page) {
  const response = listed(page);
  await dialog(page).getByRole('button', { name: '查询', exact: true }).click();
  const done = await response;
  return { request: done.request().postDataJSON(), body: (await done.json()) as ListBody };
}

test('高级查询一打开就列出预置条件；产品名称填"片"后查出的单据与列头筛选"产品名称含片"相同', async ({ page, api }) => {
  const view = await api.view();
  const personal = await api.get<{ grids?: Record<string, { columns: Array<{ field: string; hide: boolean }> }> }>(
    '/api/pages/COST_PINGGU/personal'
  );
  const hidden = (key: string) => new Set((personal.grids?.[key]?.columns ?? []).filter(c => c.hide).map(c => c.field));
  // 预置条件：先主表再按明细的顺序，勾了"查询"的可见字段，个人列配置中隐藏的列不列
  const expected = [
    ...view.master.fields
      .filter(f => f.visible && f.searchable && !hidden('master').has(f.name))
      .map(f => ['主表', f.label]),
    ...view.details.flatMap(d =>
      d.fields.filter(f => f.visible && f.searchable && !hidden(d.entity).has(f.name)).map(f => [d.title, f.label])
    )
  ];
  expect(expected).toContainEqual(['主表', '产品名称']);
  expect(expected).toContainEqual(['主表', '客户ID']);

  await openPage(page, 'COST_PINGGU');
  await openSearch(page);
  const rows = dialog(page).locator('.advanced-search__row');
  await expect(rows).toHaveCount(expected.length);
  const shown = await rows.evaluateAll(els =>
    els.map(e => [
      e.querySelector('.advanced-search__table')?.textContent?.trim() ?? '',
      e.querySelector('.n-checkbox__label')?.textContent?.trim() ?? ''
    ])
  );
  expect(shown).toEqual(expected);

  // 产品名称默认"包含"，填"片"即勾上
  const name = condition(page, 'master:GOODSNAME');
  await expect(name.locator('.n-base-selection')).toContainText('包含');
  await name.locator('.advanced-search__value input').fill('片');
  await expect(name.getByRole('checkbox')).toHaveAttribute('aria-checked', 'true');
  await expect(dialog(page)).toContainText('已启用 1 项');
  const searched = await runSearch(page);
  expect(searched.request.advanced).toEqual({
    op: 'and',
    conditions: [{ field: 'GOODSNAME', operator: 'like', value: '片' }]
  });
  await expect(dialog(page)).toBeHidden();
  await expect(page.getByText('已按高级查询筛选')).toBeVisible();
  expect(searched.body.total).toBeGreaterThan(0);

  // 重置高级查询，改用列头筛选"产品名称含片"：单据相同
  await openSearch(page);
  const cleared = listed(page);
  await dialog(page).getByRole('button', { name: '重置', exact: true }).click();
  expect((await cleared).request().postDataJSON().advanced).toBeUndefined();
  await dialog(page).getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog(page)).toBeHidden();
  const filtered = await filterColumn(page, 'GOODSNAME', '片');
  expect(filtered.request.advanced).toBeUndefined();
  expect(filtered.body.total).toBe(searched.body.total);
  expect(filtered.body.rows.map((r: { rowKey: string }) => r.rowKey)).toEqual(searched.body.rows.map(r => r.rowKey));
});

test('客户ID 用客户 Lookup 选两个客户（IN）：查出的单据只属于这两个客户', async ({ page, api }) => {
  // 两个有成本单、按客户名称在客户 Lookup 中能搜到（前 10 行内，不用滚动）的客户
  const list = await api.ok<ListBody>('POST', '/api/pages/COST_PINGGU/rows', {
    startRow: 0,
    endRow: 200,
    sortModel: [],
    filterModel: {}
  });
  const candidates = new Map<string, string>();
  for (const row of list.rows)
    if (row.values.CUSTOMID && !candidates.has(row.values.CUSTOMID))
      candidates.set(row.values.CUSTOMID, row.values.CUSTOMNAME || row.values.CUSTOMID);
  const customers: Array<{ id: string; keyword: string }> = [];
  for (const [id, keyword] of candidates) {
    if (customers.length === 2) break;
    // eslint-disable-next-line no-await-in-loop -- 逐个客户确认，够两个就停
    const found = await api.ok<LookupBody>('POST', '/api/lookups/costCustomer/search', {
      keyword,
      startRow: 0,
      endRow: 50
    });
    const index = found.rows.findIndex(r => r.values.CUSTOMID === id);
    if (index >= 0 && index < 10) customers.push({ id, keyword });
  }
  expect(customers).toHaveLength(2);

  await openPage(page, 'COST_PINGGU');
  await openSearch(page);
  const customer = condition(page, 'master:CUSTOMID');
  await customer.locator('.n-select').first().click();
  await page.locator('.n-base-select-option', { hasText: /^IN$/ }).click();
  await expect(customer.locator('.n-base-selection').first()).toContainText('IN');

  // 先后两次用 Lookup 选，选中的值追加在后面（同旧系统 appendLookupValues）
  const lookup = page.locator('.lookup-dialog');
  for (const { id, keyword } of customers) {
    // eslint-disable-next-line no-await-in-loop -- 一次选一个客户
    await customer.getByRole('button', { name: '选择', exact: true }).click();
    // eslint-disable-next-line no-await-in-loop
    await expect(lookup.locator('.ag-center-cols-container .ag-row').first()).toBeVisible();
    const searched = page.waitForResponse(r => r.url().endsWith('/api/lookups/costCustomer/search'));
    // eslint-disable-next-line no-await-in-loop
    await lookup.getByPlaceholder('输入关键字搜索').fill(keyword);
    // eslint-disable-next-line no-await-in-loop
    await lookup.getByPlaceholder('输入关键字搜索').press('Enter');
    // eslint-disable-next-line no-await-in-loop
    await searched;
    const target = lookup
      .locator('.ag-center-cols-container .ag-row')
      .filter({ has: page.locator('[col-id="CUSTOMID"]', { hasText: new RegExp(`^${id}$`) }) })
      .first();
    // eslint-disable-next-line no-await-in-loop
    await target.locator('[col-id="CUSTOMID"]').click();
    // eslint-disable-next-line no-await-in-loop
    await lookup.getByRole('button', { name: '确定', exact: true }).click();
    // eslint-disable-next-line no-await-in-loop
    await expect(lookup).toHaveCount(0);
  }
  const ids = customers.map(c => c.id);
  await expect(customer.locator('.advanced-search__value input')).toHaveValue(ids.join(', '));
  await expect(customer.getByRole('checkbox')).toHaveAttribute('aria-checked', 'true');

  const result = await runSearch(page);
  expect(result.request.advanced).toEqual({
    op: 'and',
    conditions: [{ field: 'CUSTOMID', operator: 'in', value: ids }]
  });
  expect(result.body.total).toBeGreaterThan(0);
  // 全部满足条件的单据（不只第一块）都属于这两个客户。整套并行运行时别的用例在复制 2550（同一个客户）建测试成本单，
  // 两次查询之间总数可能多几张，所以不比总数，只核对查到的每一张
  const all = await api.ok<ListBody>('POST', '/api/pages/COST_PINGGU/rows', {
    startRow: 0,
    endRow: result.body.total + 100,
    sortModel: [],
    filterModel: {},
    advanced: result.request.advanced
  });
  expect(all.rows.length).toBe(all.total);
  expect([...new Set(all.rows.map(r => r.values.CUSTOMID))].sort()).toEqual([...new Set(ids)].sort());
});
