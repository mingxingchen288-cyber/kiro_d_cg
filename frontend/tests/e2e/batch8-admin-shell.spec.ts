/**
 * 第 8 批 G4（系统管理和外壳）的浏览器用例，依据盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B10–B13：
 *
 * 1. 改已有账号的用户名（FM-05、ID-11）：admin 在人员管理把测试账号的用户名改掉、保存，这个人用新用户名登录成功，
 *    旧用户名登录失败。同旧系统人员管理"用户名"列可编辑（cmx CostUser 的 USERNAME EDITABLE=1）。
 * 2. 人员管理的高级查询（FM-06、ID-12）：按姓名、部门查出测试账号。
 * 3. 部门管理的高级查询：按部门名称查出测试部门。
 * 4. 菜单图标（FS-08，待主代理合并后运行）：d_cg 的 menu.main 补了图标之后（`.reports/batch8-20261031/g4-admin-shell/set_menu_icons.py`），
 *    左侧菜单显示旧系统的图标（cmx `T_COST_RESOURCE.ICON`）。
 * 5. 配置页改菜单图标（FC-16，@shared-config，待主代理合并后运行）：目录信息里给"基础信息"换图标、保存，菜单配置项里是新图标；改回。
 * 6. 默认值"当前部门名称"（B10，@shared-config，待主代理合并后运行）：成本核算主表的包装形式临时配成"当前部门名称"，
 *    测试账号（部门为测试部门）新建一张成本单，保存后包装形式为测试部门的名称；改回。
 *
 * 1–3 只读写本用例建的测试账号和测试部门（support.ts 的 `data`，结束时删除）。4–6 要合并后的代码和 d_cg 的新菜单，
 * 本组没有运行（`共同约定.md` 第 3 节）。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { type Locator, type Page, expect, login, openDoc, openMenu, test, toast } from './support';

const PASSWORD = 'PfTest123..';

/** 系统管理的页签（人员管理、部门管理） */
async function adminTab(page: Page, title: string) {
  if (!page.url().includes('/admin')) {
    await openMenu(page, '系统管理');
    await page.waitForURL('**/admin**');
  }
  await page.locator('.admin-tabs .n-tabs-tab', { hasText: title }).click();
  await expect(page.locator('.admin-tabs__pane').filter({ visible: true })).toHaveCount(1);
  await expect(page.locator('.admin-tabs .n-tabs-tab--active')).toContainText(title);
  return page.locator('.admin-tabs__pane').filter({ visible: true }).first();
}

/** 测试部门：经平台新建，结束时删除 */
async function testDepartment(adminApi: { ok: (m: 'POST', p: string, b: unknown) => Promise<any> }, data: any) {
  const name = `PF_TEST部门${crypto.randomUUID().slice(0, 6)}`;
  const created = await adminApi.ok('POST', '/api/admin/departments', { name, parentId: null });
  data.adoptDepartment(String(created.departmentId));
  return { departmentId: String(created.departmentId), name };
}

/** 打开"高级查询"对话框 */
async function openSearch(page: Page, pane: Locator) {
  await pane.getByRole('button', { name: /^高级查询/ }).click();
  const dialog = page.getByTestId('admin-advanced-search');
  await expect(dialog).toBeVisible();
  return dialog;
}

/** 点"查询"，等列表请求返回 */
async function runSearch(page: Page, dialog: Locator, path: string) {
  await Promise.all([
    page.waitForResponse(
      r => r.url().includes(path) && r.url().includes('advanced=') && r.request().method() === 'GET'
    ),
    dialog.getByRole('button', { name: '查询', exact: true }).click()
  ]);
  await expect(dialog).toBeHidden();
}

test('改已有账号的用户名：admin 在人员管理改名并保存，用新用户名登录成功，旧用户名登录失败', async ({
  page,
  fresh,
  apiOf,
  data
}) => {
  const account = await data.account({ roleCodes: ['COST_ACCOUNTANT'] });
  // 登录页的用户名最长 16 位（同旧系统登录页的格式校验），pf_test_xxxxxxxx 改成 pf_new_xxxxxxxx
  const renamed = account.username.replace('pf_test_', 'pf_new_');
  await page.goto('/home');
  const accounts = await adminTab(page, '人员管理');
  const target = accounts.locator(`.ag-row[row-id="${account.userId}"] [col-id="username"]`).first();
  await expect(target).toHaveText(account.username);

  await target.dblclick();
  await expect(accounts.locator('.ag-cell-inline-editing')).toBeVisible();
  await page.keyboard.press('Control+A');
  await page.keyboard.type(renamed);
  await page.keyboard.press('Enter');
  await expect(accounts.locator(`.ag-row[row-id="${account.userId}"]`)).toHaveClass(/admin-row-changed/);
  const [saved] = await Promise.all([
    page.waitForResponse(
      r => r.url().endsWith(`/api/admin/accounts/${account.userId}`) && r.request().method() === 'PUT'
    ),
    accounts.getByRole('button', { name: '保存', exact: true }).click()
  ]);
  expect(saved.request().postDataJSON()).toMatchObject({ username: renamed });
  await toast(page, '保存成功');
  await expect(target).toHaveText(renamed);

  const user = await fresh();
  await login(user, { username: renamed, password: account.password });
  const me = await apiOf(user).get('/api/me');
  expect([String(me.user.userId), me.user.username]).toEqual([account.userId, renamed]);
  const old = await apiOf(user).send('POST', '/api/auth/login', {
    username: account.username,
    password: account.password
  });
  expect(old.status).toBe(401);
});

test('人员管理高级查询：按姓名、部门查出测试账号', async ({ page, data, adminApi }) => {
  const department = await testDepartment(adminApi, data);
  const displayName = `PF_TEST 高级查询 ${crypto.randomUUID().slice(0, 6)}`;
  const account = await data.account({ displayName, departmentId: department.departmentId });
  await page.goto('/home');
  const accounts = await adminTab(page, '人员管理');

  const dialog = await openSearch(page, accounts);
  await expect(dialog.locator('[data-testid^="condition-"]')).toHaveCount(5);
  await dialog.getByTestId('condition-displayName').locator('input').fill(displayName);
  await dialog.getByTestId('condition-departmentId').locator('.n-base-selection').last().click();
  await page.locator('.n-base-select-option', { hasText: department.name }).first().click();
  await expect(dialog.getByText('已启用 2 项')).toBeVisible();
  await runSearch(page, dialog, '/api/admin/accounts');

  const rows = accounts.locator('.ag-center-cols-container .ag-row');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toHaveAttribute('row-id', account.userId);
  await expect(rows.first().locator('[col-id="departmentId"]')).toHaveText(department.name);
  await expect(accounts.getByRole('button', { name: '高级查询（2）' })).toBeVisible();
});

test('部门管理高级查询：按部门名称查出测试部门', async ({ page, data, adminApi }) => {
  const department = await testDepartment(adminApi, data);
  await page.goto('/home');
  const departments = await adminTab(page, '部门管理');

  const dialog = await openSearch(page, departments);
  await dialog.getByTestId('condition-name').locator('input').fill(department.name);
  await runSearch(page, dialog, '/api/admin/departments');

  const rows = departments.locator('.ag-center-cols-container .ag-row');
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator('[col-id="name"]')).toHaveText(department.name);
});

// ---------------------------------------------------------------- 待主代理合并后运行

/** 离线图标集 @iconify-json/mdi 中一个图标的路径（与外壳渲染的 svg 比较） */
function mdiPath(name: string) {
  const file = fileURLToPath(new URL('../../node_modules/@iconify-json/mdi/icons.json', import.meta.url));
  const icons = JSON.parse(readFileSync(file, 'utf8')) as { icons: Record<string, { body: string }> };
  return /\sd="([^"]+)"/.exec(icons.icons[name].body)![1];
}

async function menuIconPath(page: Page, title: string) {
  const item = page.locator('aside .n-menu-item-content', { hasText: title }).first();
  return item.locator('svg path').first().getAttribute('d');
}

test('菜单图标（待主代理合并后运行）：左侧菜单按旧系统显示图标', async ({ page }) => {
  await page.goto('/home');
  if (!((await page.locator('aside:has(.n-menu)').first().boundingBox())?.width ?? 0))
    await page.locator('header button').first().click();
  await page.locator('aside .n-menu-item-content', { hasText: '成本' }).first().click();
  expect(await menuIconPath(page, '成本核算')).toBe(mdiPath('calculator-variant'));
  expect(await menuIconPath(page, '基础信息')).toBe(mdiPath('currency-usd'));
  expect(await menuIconPath(page, '系统管理')).toBe(mdiPath('cog'));
});

test(
  '配置页改菜单图标（待主代理合并后运行）：目录信息给"基础信息"换成包裹图标，菜单配置项里是新图标',
  { lock: 'menu.main', tag: '@shared-config' },
  async ({ page, adminApi }) => {
    const before = await adminApi.get('/api/config/items/menu/main');
    try {
      await page.goto('/config');
      await page.locator('.unified-config__sider .n-tree-node', { hasText: '基础信息' }).first().click();
      const select = page.getByTestId('menu-icon');
      await select.locator('.n-base-selection').first().click();
      await page.locator('.n-base-select-option', { hasText: '包裹' }).first().click();
      await select.getByRole('button', { name: '保存', exact: true }).click();
      await toast(page, /菜单已保存，版本/);
      const after = await adminApi.get('/api/config/items/menu/main');
      const basic = after.content.items.find((i: { key: string }) => i.key === 'basic');
      expect(basic.icon).toBe('mdi:package-variant');
    } finally {
      await adminApi.ok('PUT', '/api/config/items/menu/main', { name: before.name, content: before.content });
    }
  }
);

test(
  '默认值"当前部门名称"（待主代理合并后运行）：测试账号新建成本单，包装形式为他的部门名称',
  { lock: 'page.COST_PINGGU', tag: '@shared-config' },
  async ({ fresh, apiOf, data, adminApi }) => {
    const department = await testDepartment(adminApi, data);
    const account = await data.account({ roleCodes: ['COST_ACCOUNTANT'], departmentId: department.departmentId });
    const entity = await adminApi.get('/api/config/items/entity/COST_PINGGU');
    const content = structuredClone(entity.content);
    const field = content.fields.find((f: { name: string }) => f.name === 'PACKTYPE');
    field.default = { type: 'builtin', value: 'currentDeptName' };
    try {
      await adminApi.ok('PUT', '/api/config/items/entity/COST_PINGGU', { name: entity.name, content });
      const user = await fresh();
      await login(user, { username: account.username, password: PASSWORD });
      const masterId = `tmp-${crypto.randomUUID()}`;
      const result = await apiOf(user).command([
        {
          entity: 'COST_PINGGU',
          master: {
            op: 'add',
            clientRowId: masterId,
            values: { MEMO: data.marker, APEX_PL: '1000000', P_PERPACK: '112', S_PERBACK: '80', YIELD: '93.94' }
          },
          details: []
        }
      ]);
      expect(result.outcome).toBe('saved');
      const docId = String(result.idMap[masterId]);
      data.adopt(docId);
      expect((await adminApi.record(docId)).master.values.PACKTYPE).toBe(department.name);
      await openDoc(user, docId);
      await expect(
        user.getByTestId('master-grid').locator(`.ag-row[row-id="${docId}"] [col-id="PACKTYPE"]`)
      ).toHaveText(department.name);
    } finally {
      await adminApi.ok('PUT', '/api/config/items/entity/COST_PINGGU', { name: entity.name, content: entity.content });
    }
  }
);
