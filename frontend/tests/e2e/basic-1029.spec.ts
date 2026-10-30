/**
 * 2026-10-29 基础功能核对的 5 个场景（.reports/basic-functions-20261029/progress.md 阶段 3 的 3.1–3.5）改成的正式用例。
 * 场景 5"回归"就是已有的 admin、cost-detail、e01 三个用例文件，这里不重复。
 *
 * 1. 配置生效（@shared-config）：配置 → 一体化配置 → 成本核算 → 表与列，取消主表"包装形式"的"编辑"、保存列；
 *    成本核算里包装形式不能编辑，保存操作 COST_PINGGU.save 的可写字段没有 PACKTYPE；勾回后又能编辑。
 *    （10-29 改的是备注，现在备注随产品 Lookup 回填写库、一直可写，见 FIELD 的说明。）
 * 2. 部门和账号：系统管理 → 部门管理新增部门，人员管理新增账号（部门选新部门，初始密码用界面预填的值）。
 * 3. 角色权限（@shared-config，新建角色会重新生成成本核算的页面视图并发 config.changed）：配置 → 角色权限新建角色，
 *    成本核算只给"保存"按钮、原辅料"额外投料量"不可编辑；系统管理 → 角色人员把测试账号加进去；
 *    从登录页退出 admin、换测试账号登录，核对菜单、按钮、可编辑，改主表备注再改回。
 * 4a. 审批流配置（@shared-config）：配置 → 成本核算 → 审批流新建 C06 7.8 的成本明细改价审批（只配第 1 级），
 *    保存后读回的配置与 7.8 逐项相同。用自己的流程编码、保存为不启用，不影响别的保存。
 * 4b. 审批：chengben01 改测试物料的单价提交审批、单据冻结；admin 在待办中通过；chengben01 收到"已通过"，
 *    我的发起里是"已通过"，单据解冻、单价能编辑。
 * 当时写死的部门"成本部"、账号 chengben01、角色 COST_ACCOUNTANT、流程 COST_TO_GOODS 在 d_cg 里已经有了，
 * 这里都用带 PF_TEST 的新名字，用例结束时删除。
 */
import type { Locator } from '@playwright/test';
import {
  type Page,
  canEdit,
  cell,
  closeMenu,
  detailGrid,
  edit,
  expect,
  filterColumn,
  login,
  logout,
  masterGrid,
  menuTitles,
  mustSave,
  nextFrame,
  notice,
  noticed,
  openDoc,
  openMenu,
  openTodo,
  passInDetail,
  realtimeEvents,
  save,
  selectRow,
  showDetail,
  test,
  toast
} from './support';

const K30 = '206323';

/** 配置页的表格（ConfigGrid）里，纵向滚到某一列文字等于 `text` 的行，返回这一行（按 row-id 定位） */
async function rowWith(grid: Locator, column: string, text: string) {
  const rowId = await grid
    .locator('.ag-body-viewport')
    .first()
    .evaluate(
      async (el, [col, wanted]) => {
        const frame = () =>
          new Promise(resolve => {
            requestAnimationFrame(() => requestAnimationFrame(resolve));
          });
        const find = () =>
          Array.from(el.querySelectorAll(`.ag-center-cols-container [col-id="${col}"]`)).find(
            c => (c.textContent ?? '').trim() === wanted
          );
        el.scrollTop = 0;
        await frame();
        for (let top = 0; !find() && top <= el.scrollHeight; top += el.clientHeight / 2) {
          el.scrollTop = top;
          // 逐段滚，每段等表格画完再看（机器忙时一帧画不完，最多等 5 次两帧）
          for (let i = 0; i < 5 && !find(); i += 1)
            // eslint-disable-next-line no-await-in-loop
            await frame();
        }
        return find()?.closest('.ag-row')?.getAttribute('row-id') ?? null;
      },
      [column, text]
    );
  expect(rowId, `表格里没有 ${column} = ${text} 的行`).toBeTruthy();
  return grid.locator(`.ag-center-cols-container .ag-row[row-id="${rowId}"]`);
}

/** 配置 → 一体化配置 → 成本核算，返回"表与列"里主表的字段表 */
async function openFieldGrid(page: Page) {
  await page.goto('/config');
  await page.locator('.unified-config').getByText('成本核算', { exact: true }).first().click();
  const grid = page
    .locator('.ag-root-wrapper')
    .filter({ has: page.locator('[col-id="locks"]') })
    .first();
  await expect(grid).toBeVisible();
  return grid;
}

// ---------------------------------------------------------------- 1 配置生效

/**
 * 10-29 改的是备注（MEMO）。现在备注是产品 Lookup（costGoods）的回填字段（页面视图 fillWritable），取消"编辑"后
 * 仍在保存操作的可写字段里（随 Lookup 回填写库），看不出"可写字段跟着变"，所以改用不随 Lookup 回填的包装形式。
 */
const FIELD = 'PACKTYPE';

test(
  '场景 1 配置生效：表与列取消主表包装形式的"编辑"，成本核算里不能编辑、可写字段没有它；勾回后又能编辑',
  { lock: 'page.COST_PINGGU', tag: '@shared-config' },
  async ({ page, data, api, adminApi }) => {
    const doc = await data.copyDoc('2550');
    const items = ['page/COST_PINGGU', 'entity/COST_PINGGU', 'operation/COST_PINGGU.save'];
    const before = await Promise.all(items.map(item => adminApi.get(`/api/config/items/${item}`)));
    const writable = async () =>
      (await adminApi.get('/api/config/items/operation/COST_PINGGU.save')).content.writableFields
        .COST_PINGGU as string[];
    const setEditable = async (wanted: boolean) => {
      const grid = await openFieldGrid(page);
      const box = (await rowWith(grid, 'name', FIELD)).locator('[col-id="editable"] input[type="checkbox"]');
      await expect(box).toBeEnabled();
      await expect(box).toBeChecked({ checked: !wanted });
      await box.click();
      await expect(box).toBeChecked({ checked: wanted });
      await page.getByRole('button', { name: '保存列', exact: true }).click();
      await toast(page, /已保存，版本/);
    };
    const state = async () => {
      await openDoc(page, doc.docId);
      await showDetail(page, '原料/辅料');
      const view = await api.get('/api/pages/COST_PINGGU/view');
      return {
        field: await canEdit(page, await cell(masterGrid(page), doc.docId, FIELD)),
        materialPrice: await canEdit(page, await cell(detailGrid(page, 'COST_MATERIAL'), doc.row(K30), 'PRICE')),
        view: view.master.fields.find((f: { name: string }) => f.name === FIELD).editable
      };
    };
    try {
      expect(await writable()).toContain(FIELD);
      await setEditable(false);
      // 保存列依次保存实体、页面、保存操作，各有一条"已保存"提示；等保存操作也保存完
      await expect.poll(writable).not.toContain(FIELD);
      expect(await state()).toEqual({ field: false, materialPrice: true, view: false });

      await setEditable(true);
      await expect.poll(writable).toContain(FIELD);
      expect(await state()).toEqual({ field: true, materialPrice: true, view: true });
      expect((await adminApi.get('/api/config/items/operation/COST_PINGGU.save')).content).toEqual(before[2].content);
    } finally {
      // 改回：先关掉页面（中途失败时"保存列"后面的几步不再发出），再把内容与改前不同的配置项按改前的内容保存；
      // 已经发出的保存可能晚到，所以连续两次核对都与改前相同才算改回
      await page.close();
      let same = 0;
      await expect
        .poll(async () => {
          let changed = false;
          for (const [i, item] of items.entries()) {
            // eslint-disable-next-line no-await-in-loop
            const now = await adminApi.get(`/api/config/items/${item}`);
            if (JSON.stringify(now.content) !== JSON.stringify(before[i].content)) {
              changed = true;
              // eslint-disable-next-line no-await-in-loop
              await adminApi.ok('PUT', `/api/config/items/${item}`, {
                name: before[i].name,
                content: before[i].content
              });
            }
          }
          same = changed ? 0 : same + 1;
          return same;
        })
        .toBeGreaterThanOrEqual(2);
    }
  }
);

// ---------------------------------------------------------------- 2 部门和账号

/** 系统管理的某个页签，返回页签内容区 */
async function adminTab(page: Page, title: string) {
  if (!page.url().includes('/admin')) {
    await openMenu(page, '系统管理');
    await page.waitForURL('**/admin**');
  }
  await page.locator('.admin-tabs .n-tabs-tab', { hasText: title }).click();
  // 页签切换有动画：动画期间新旧两个页签都可见，等只剩一个
  await expect(page.locator('.admin-tabs__pane').filter({ visible: true })).toHaveCount(1);
  await expect(page.locator('.admin-tabs .n-tabs-tab--active')).toContainText(title);
  return page.locator('.admin-tabs__pane').filter({ visible: true }).first();
}

/** 新增行（row-id 以 new- 开头）的某一格：双击后输入文字 */
// eslint-disable-next-line max-params -- 页面、表格、行、列、值，与一次界面操作一一对应
async function typeNew(page: Page, pane: Locator, column: string, value: string) {
  const target = pane.locator(`.ag-row[row-id^="new-"] [col-id="${column}"]`).first();
  if (!(await pane.locator('.ag-cell-inline-editing').count())) await target.dblclick();
  await expect(pane.locator('.ag-cell-inline-editing')).toBeVisible();
  await page.keyboard.press('Control+A');
  await page.keyboard.type(value);
  await page.keyboard.press('Enter');
  await expect(pane.locator('.ag-cell-inline-editing')).toHaveCount(0);
}

test('场景 2 部门和账号：系统管理新增部门、新增账号（部门选新部门，初始密码用界面预填的值）', async ({
  page,
  data,
  adminApi
}) => {
  const suffix = crypto.randomUUID().slice(0, 6);
  const departmentName = `PF_TEST部门${suffix}`;
  const username = `pf_test_${suffix}`;
  await page.goto('/home');

  const departments = await adminTab(page, '部门管理');
  await departments.getByRole('button', { name: '新增', exact: true }).click();
  await typeNew(page, departments, 'name', departmentName);
  // 等保存的请求返回（页面上前一次的"保存成功"提示可能还在，不能只看提示）
  const [created] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/admin/departments') && r.request().method() === 'POST'),
    departments.getByRole('button', { name: '保存', exact: true }).click()
  ]);
  const departmentId = String((await created.json()).departmentId);
  data.adoptDepartment(departmentId);
  await toast(page, '保存成功');
  await expect(departments.locator('.ag-row', { hasText: departmentName }).first()).toBeVisible();
  const saved = (await adminApi.get('/api/admin/departments')).items.find(
    (d: { name: string }) => d.name === departmentName
  );
  expect(String(saved.departmentId)).toBe(departmentId);

  const accounts = await adminTab(page, '人员管理');
  await accounts.getByRole('button', { name: '新增', exact: true }).click();
  await typeNew(page, accounts, 'username', username);
  await typeNew(page, accounts, 'displayName', `PF_TEST 成本会计 ${suffix}`);
  // 部门：下拉选择（切回人员管理时重新读了部门，刚建的部门能选）
  await accounts.locator('.ag-row[row-id^="new-"] [col-id="departmentId"]').first().dblclick();
  const items = page.locator('.ag-select-list .ag-list-item');
  if (!(await items.count()))
    await accounts.locator('.ag-cell-inline-editing .ag-picker-field-wrapper').first().click();
  await items.filter({ hasText: departmentName }).first().click();
  await expect(accounts.locator('.ag-row[row-id^="new-"] [col-id="departmentId"]').first()).toHaveText(departmentName);
  const password = (
    (await accounts.locator('.ag-row[row-id^="new-"] [col-id="password"]').first().textContent()) ?? ''
  ).trim();
  expect(password).toBeTruthy();
  const [createdAccount] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/admin/accounts') && r.request().method() === 'POST'),
    accounts.getByRole('button', { name: '保存', exact: true }).click()
  ]);
  const userId = String((await createdAccount.json()).userId);
  data.adoptUser(userId);
  await toast(page, '保存成功');
  const accountRow = accounts.locator('.ag-row:not([row-id^="new-"])', { hasText: username }).first();
  await expect(accountRow.locator('[col-id="departmentId"]')).toHaveText(departmentName);
  await expect(accountRow.locator('[col-id="roles"]')).toHaveText('');

  const account = (await adminApi.get(`/api/admin/accounts?keyword=${username}`)).rows.find(
    (r: { username: string }) => r.username === username
  );
  expect([String(account.userId), account.departmentId, account.enabled, account.roleCodes]).toEqual([
    userId,
    departmentId,
    true,
    []
  ]);
});

// ---------------------------------------------------------------- 3 角色权限

/** 配置 → 角色权限：新增角色、勾选成本核算、按钮只给"保存"、原辅料额外投料量不可编辑、保存角色 */
async function createRole(page: Page, code: string, name: string) {
  await openMenu(page, '配置');
  await page.waitForURL('**/config**');
  await page.locator('.n-tabs-tab', { hasText: '角色权限' }).first().click();
  await page.locator('.permission-page').getByRole('button', { name: '新增', exact: true }).click();
  const form = page.getByRole('dialog').filter({ hasText: '新增角色' });
  await form.getByPlaceholder('角色编码').fill(code);
  await form.getByPlaceholder('角色名称').fill(name);
  await form.getByRole('button', { name: '确定' }).click();
  const detail = page.locator('.permission-page .detail-panel');
  await expect(detail.getByText(code)).toBeVisible();
  await expect(detail.locator('.n-switch')).toHaveAttribute('aria-checked', 'false'); // 管理员开关默认关

  const node = detail.locator('.n-tree-node', { hasText: '成本核算' }).first();
  await node.locator('.n-tree-node-checkbox').click();
  await node.getByRole('button', { name: '配置按钮' }).click();
  const buttons = page.getByRole('dialog').filter({ hasText: '配置按钮权限' });
  await buttons.getByText('全部按钮', { exact: true }).click();
  const saveBox = buttons.getByRole('checkbox', { name: '保存', exact: true }).first();
  await saveBox.click();
  await expect(saveBox).toBeChecked();
  await buttons.getByRole('button', { name: '确定' }).click();
  await expect(buttons).toHaveCount(0);

  await node.getByRole('button', { name: '配置列' }).click();
  const columns = page.getByRole('dialog').filter({ hasText: '配置列权限' });
  await columns.locator('.n-tabs-tab', { hasText: '原料/辅料' }).click();
  const row = columns
    .locator('.n-tab-pane')
    .filter({ visible: true })
    .locator('tr', { hasText: 'EXADD_MATER' })
    .first();
  const editable = row.locator('td').nth(3).locator('.n-checkbox');
  await expect(editable).toHaveAttribute('aria-checked', 'true');
  await editable.click();
  await expect(editable).toHaveAttribute('aria-checked', 'false');
  await columns.getByRole('button', { name: '确定' }).click();
  await expect(columns).toHaveCount(0);

  await detail.getByRole('button', { name: '保存角色' }).click();
  await toast(page, new RegExp(`${name} 已保存，版本`));
}

/** 页面内容区里看得到的按钮文字 */
async function pageButtons(page: Page) {
  return page.locator('main button').evaluateAll(bs => [
    ...new Set(
      bs
        .filter(b => (b as HTMLElement).offsetParent !== null)
        .map(b => (b.textContent ?? '').trim())
        .filter(t => t && t !== '⊞')
    )
  ]);
}

test(
  '场景 3 角色权限：新建角色只给保存、额外投料量不可编辑，分配给测试账号；换账号登录后菜单、按钮、可编辑按角色',
  { lock: 'page.COST_PINGGU', tag: '@shared-config' },
  async ({ page, fresh, data, adminApi }) => {
    const suffix = crypto.randomUUID().slice(0, 6).toUpperCase();
    const code = `PF_TEST_ROLE_${suffix}`;
    const name = `PF_TEST成本会计${suffix}`;
    const doc = await data.copyDoc('2550');
    const account = await data.account();
    await page.goto('/home');
    data.adoptConfig(`role/${code}`);
    await createRole(page, code, name);
    const role = (await adminApi.get(`/api/config/items/role/${code}`)).content;
    expect(role.admin).toBeFalsy();
    expect(role.pages.COST_PINGGU.buttons).toEqual(['system:save']);
    expect(role.pages.COST_PINGGU.columns.COST_MATERIAL.EXADD_MATER.editable).toBe(false);

    // 系统管理 → 角色人员：把测试账号加进这个角色
    await adminTab(page, '角色人员');
    await page.locator('.role-members .role-card', { hasText: code }).click();
    await expect(page.locator('.role-members .role-title')).toHaveText(name);
    await page.getByRole('button', { name: '分配人员' }).click();
    const assign = page.getByRole('dialog').filter({ hasText: '分配人员' });
    await assign.locator('.n-select').click();
    await page.keyboard.type(account.username);
    await page
      .locator('.n-base-select-option', { hasText: `(${account.username})` })
      .first()
      .click();
    await assign.getByRole('button', { name: '确定' }).click();
    await toast(page, '添加成功');
    await expect(page.locator('.role-members .n-data-table-tr', { hasText: account.username })).toBeVisible();
    const assigned = (await adminApi.get(`/api/admin/accounts?keyword=${account.username}`)).rows[0];
    expect(assigned.roleCodes).toEqual([code]);

    // 从登录页登录 admin、右上角退出，换测试账号登录
    const user = await fresh();
    await login(user, { username: 'admin', password: 'admin123..' });
    await logout(user);
    await login(user, account);
    const menus = await menuTitles(user);
    expect(menus).toContain('成本核算');
    expect(menus).not.toContain('配置');
    expect(menus).not.toContain('系统管理');

    await openMenu(user, '成本核算', '成本');
    await user.waitForURL('**/page/COST_PINGGU');
    await expect(masterGrid(user).locator('.ag-row').first()).toBeVisible();
    await filterColumn(user, 'DOCID', doc.docId);
    await selectRow(user, doc.docId);
    await showDetail(user, '原料/辅料');
    const materials = detailGrid(user, 'COST_MATERIAL');
    const line = doc.row(K30);
    await expect(materials.locator(`.ag-row[row-id="${line}"]`).first()).toBeVisible();
    const buttons = await pageButtons(user);
    expect(buttons).toContain('保存');
    for (const b of ['新增', '复制', '删除', '明细新增', '明细复制', '明细删除']) expect(buttons).not.toContain(b);
    expect({
      EXADD_MATER: await canEdit(user, await cell(materials, line, 'EXADD_MATER')),
      PRICE: await canEdit(user, await cell(materials, line, 'PRICE')),
      MEMO: await canEdit(user, await cell(materials, line, 'MEMO')),
      masterMEMO: await canEdit(user, await cell(masterGrid(user), doc.docId, 'MEMO'))
    }).toEqual({ EXADD_MATER: false, PRICE: true, MEMO: true, masterMEMO: true });
    // 右键菜单没有明细新增、复制、删除
    await (await cell(materials, line, 'MEMO')).click({ button: 'right' });
    await nextFrame(user);
    const contextMenu = await user.locator('.ag-menu-option').allTextContents();
    for (const b of ['明细新增', '明细复制', '明细删除']) expect(contextMenu.join()).not.toContain(b);
    await user.keyboard.press('Escape');

    // 主表备注改为"成本会计测试"保存，再改回原值
    const memo = () => cell(masterGrid(user), doc.docId, 'MEMO');
    await edit(user, await memo(), '成本会计测试');
    mustSave(await save(user));
    await toast(user, '已保存');
    await expect(await memo()).toHaveText('成本会计测试');
    await edit(user, await memo(), data.marker);
    mustSave(await save(user));
    await expect(await memo()).toHaveText(data.marker);
    expect((await adminApi.record(doc.docId)).master.values.MEMO).toBe(data.marker);
    await closeMenu(user);
  }
);

// ---------------------------------------------------------------- 4a 审批流配置

const CONDITION =
  '(DECODE(:new_GOODSID, :old_GOODSID, 0, 1) = 1 OR DECODE(:new_PRICE, :old_PRICE, 0, 1) = 1) AND DECODE(:new_PRICE, (SELECT NVL(ZX_PRICE, PRICE) FROM T_COST_GOODS WHERE GOODSID = :new_GOODSID), 0, 1) = 1';
type DisplayColumn = { field: string; label: string; precision?: number };
const DETAIL_COLUMNS: DisplayColumn[] = [
  { field: 'GOODSID', label: '物料' },
  { field: 'GOODSNAME', label: '物料名称' },
  { field: 'PRICE', label: '单价', precision: 2 },
  { field: 'COST_BATCH', label: '金额', precision: 2 }
];
const COST_BLOCK = {
  key: 'cost',
  title: '成本单及成本变化',
  region: 'master',
  source: 'COST_PINGGU',
  columns: [
    { field: 'DOCID', label: '单据号' },
    { field: 'GOODSNAME', label: '产品' },
    { field: 'COST_PERBOX', label: '每盒成本', precision: 4 },
    { field: 'JGF_PERQP', label: '千片加工费', precision: 2 }
  ]
};
const MATERIAL_BLOCK = {
  key: 'material',
  title: '原辅料',
  region: 'detail',
  source: 'COST_MATERIAL',
  columns: DETAIL_COLUMNS
};
const PACKAGE_BLOCK = {
  key: 'package',
  title: '包材',
  region: 'detail',
  source: 'COST_PACKAGE',
  columns: DETAIL_COLUMNS
};
const GOODS_BLOCK = {
  key: 'goods',
  title: '物料清单',
  region: 'affected',
  source: 'T_COST_GOODS_PRICE_V',
  condition: 'GOODSID = :new_GOODSID',
  targetTable: 'T_COST_GOODS',
  keyColumn: 'GOODSID',
  columns: [
    { field: 'GOODSID', label: '物料ID' },
    { field: 'GOODSNAME', label: '物料名称' },
    { field: 'ZX_PRICE', label: '单价', precision: 2 }
  ],
  selection: 'all',
  actions: [{ action: 'updateFields', fields: [{ column: 'ZX_PRICE', value: ':new_PRICE' }] }]
};
/** C06 7.8 去掉第 2 级（d_cg 没有 008、007 两个角色）；保存为不启用，`order` 由页面按已有流程排 */
const FLOW = {
  page: 'COST_PINGGU',
  enabled: false,
  operations: { COST_MATERIAL: ['add', 'modify'], COST_PACKAGE: ['add', 'modify'] },
  levels: [
    {
      level: 1,
      nodes: [
        {
          name: '管理员审批',
          conditionType: 'sql',
          condition: CONDITION,
          department: null,
          approvers: [{ type: 'role', role: 'ADMIN' }],
          mode: 'or',
          enabled: true
        }
      ]
    }
  ],
  freeze: [{ table: 'T_COST_GOODS', condition: 'GOODSID = :new_GOODSID', enabled: true }],
  display: [COST_BLOCK, MATERIAL_BLOCK, PACKAGE_BLOCK, GOODS_BLOCK],
  propagation: 'end',
  notify: [
    { event: 'submitted', to: 'levelApprovers' },
    { event: 'passed', to: 'applicant' },
    { event: 'rejected', to: 'applicant' }
  ]
};

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const dialog = (page: Page) => page.getByRole('dialog').last();

/** 配置表格第 rowIndex 行的某一格（表格先滚到视野中间，双击时格子不在页面边缘） */
async function cellAt(grid: Locator, rowIndex: number, colId: string) {
  await grid.evaluate(el => el.scrollIntoView({ block: 'center' }));
  const row = grid.locator(`.ag-center-cols-container .ag-row[row-index="${rowIndex}"]`);
  await expect(row).toBeVisible();
  return cell(grid, (await row.getAttribute('row-id'))!, colId);
}

// eslint-disable-next-line max-params -- 页面、表格、行、列、值，与一次界面操作一一对应
async function typeCell(page: Page, grid: Locator, rowIndex: number, colId: string, text: string | number) {
  await edit(page, await cellAt(grid, rowIndex, colId), String(text));
}

/** 下拉格（agSelectCellEditor）：双击，列表没打开就点一下，选文字完全相同的一项 */
// eslint-disable-next-line max-params -- 页面、表格、行、列、值，与一次界面操作一一对应
async function selectCell(page: Page, grid: Locator, rowIndex: number, colId: string, label: string) {
  const target = await cellAt(grid, rowIndex, colId);
  await target.dblclick();
  await expect(grid.locator('.ag-cell-inline-editing')).toBeVisible();
  const items = page.locator('.ag-select-list .ag-list-item');
  if (!(await items.count())) await grid.locator('.ag-cell-inline-editing .ag-picker-field-wrapper').first().click();
  await items
    .filter({ hasText: new RegExp(`^\\s*${escape(label)}\\s*$`) })
    .first()
    .click();
  await expect(grid.locator('.ag-cell-inline-editing')).toHaveCount(0);
  await expect(target).toHaveText(label);
}

/** 可输入的下拉格（agRichSelectCellEditor）：双击，输入字段名，点名称以" · 字段名"结尾或等于字段名的一项 */
// eslint-disable-next-line max-params -- 页面、表格、行、列、值，与一次界面操作一一对应
async function richSelectCell(page: Page, grid: Locator, rowIndex: number, colId: string, field: string) {
  await (await cellAt(grid, rowIndex, colId)).dblclick();
  const input = grid.locator('.ag-cell-inline-editing input').first();
  await expect(input).toBeVisible();
  await input.pressSequentially(field);
  const option = page
    .locator('.ag-rich-select-row')
    .filter({ hasText: new RegExp(`(^|· )${escape(field)}$`) })
    .first();
  await option.click();
  await expect(grid.locator('.ag-cell-inline-editing')).toHaveCount(0);
}

async function apply(page: Page) {
  const d = dialog(page);
  await d.getByRole('button', { name: '应用到当前草稿' }).click();
  await expect(d).toBeHidden();
}

/** 显示列弹窗：逐列新增，选字段，写显示名称和小数位 */
async function setColumns(page: Page, columns: DisplayColumn[]) {
  const grid = dialog(page).locator('.ag-root-wrapper');
  for (const [i, { field, label, precision }] of columns.entries()) {
    // 逐列填写，按顺序进行
    /* eslint-disable no-await-in-loop */
    await dialog(page).getByRole('button', { name: '新增列' }).click();
    await richSelectCell(page, grid, i, 'field', field);
    await typeCell(page, grid, i, 'label', label);
    if (precision !== undefined) await typeCell(page, grid, i, 'precision', precision);
    /* eslint-enable no-await-in-loop */
  }
  await apply(page);
}

// eslint-disable-next-line max-params -- 页面、表格、行、列、值，与一次界面操作一一对应
async function editCondition(page: Page, grid: Locator, rowIndex: number, text: string, withType: boolean) {
  await (await cellAt(grid, rowIndex, 'condition')).dblclick();
  const d = dialog(page);
  await expect(d).toBeVisible();
  if (withType) {
    await d.locator('.n-select').first().click();
    await page.locator('.n-base-select-option', { hasText: 'SQL 条件' }).click();
  }
  await d.locator('textarea').fill(text);
  await apply(page);
}

test(
  '场景 4a 审批流配置：在配置页新建 C06 7.8 的成本明细改价审批，保存后读回与 7.8 相同',
  { lock: 'page.COST_PINGGU', tag: '@shared-config' },
  async ({ page, data, adminApi }) => {
    test.slow(); // 界面上逐格填一个完整的审批流，约 50 秒
    const code = `PF_TEST_FLOW_${crypto.randomUUID().slice(0, 6).toUpperCase()}`;
    const name = `PF_TEST成本明细改价审批`;
    await page.goto('/config');
    await page.locator('.unified-config').getByText('成本核算', { exact: true }).first().click();
    await page.locator('.n-collapse-item__header-main', { hasText: /^审批流$/ }).click();
    const section = page.locator('.section-approval');
    await expect(section.getByRole('button', { name: '新增流程' })).toBeEnabled();
    await section.getByRole('button', { name: '新增流程' }).click();
    const flows = section.locator('.config-grid').nth(0);
    const details = section.locator('.config-grid').nth(1);
    const flowRow = (await flows.locator('.ag-center-cols-container .ag-row').count()) - 1;

    // 流程：名称、编码、审核操作、不启用
    await typeCell(page, flows, flowRow, 'name', name);
    await section.locator('.heading-extra input').fill(code);
    data.adoptConfig(`approvalFlow/${code}`);
    await (await cellAt(flows, flowRow, 'operations')).dblclick();
    for (const table of ['原料/辅料', '包材']) {
      const row = dialog(page).locator('.op-row', { hasText: table });
      // eslint-disable-next-line no-await-in-loop
      await row.getByRole('checkbox', { name: '新增' }).click();
      // eslint-disable-next-line no-await-in-loop
      await row.getByRole('checkbox', { name: '修改' }).click();
    }
    await apply(page);
    const enabled = (await cellAt(flows, flowRow, 'enabled')).locator('input[type="checkbox"]');
    await enabled.uncheck();
    await expect(enabled).not.toBeChecked();

    // 审批节点：第 1 级"管理员审批"
    await section.getByRole('button', { name: '新增明细' }).click();
    await typeCell(page, details, 0, 'name', '管理员审批');
    await editCondition(page, details, 0, CONDITION, true);
    await (await cellAt(details, 0, 'approvers')).dblclick();
    await dialog(page).getByRole('button', { name: '新增审批对象' }).click();
    await selectCell(page, dialog(page).locator('.ag-root-wrapper'), 0, 'role', '系统管理员 (ADMIN)');
    await apply(page);

    // 冻结节点：物料清单
    await section.locator('.n-tabs-tab', { hasText: '冻结节点' }).click();
    await section.getByRole('button', { name: '新增明细' }).click();
    await typeCell(page, details, 0, 'table', 'T_COST_GOODS');
    await editCondition(page, details, 0, 'GOODSID = :new_GOODSID', false);

    // 展示数据：成本单主表、原辅料、包材、物料清单
    await section.locator('.n-tabs-tab', { hasText: '展示数据' }).click();
    const add = section.getByRole('button', { name: '新增明细' });
    await add.click();
    await add.click();
    await add.click();
    await add.click();
    const [cost, material, pkg, goods] = [COST_BLOCK, MATERIAL_BLOCK, PACKAGE_BLOCK, GOODS_BLOCK];
    await typeCell(page, details, 0, 'key', cost.key);
    await typeCell(page, details, 0, 'title', cost.title);
    await selectCell(page, details, 0, 'region', '修改内容 · 主表');
    await (await cellAt(details, 0, 'columns')).dblclick();
    await setColumns(page, cost.columns);

    await typeCell(page, details, 1, 'key', material.key);
    await typeCell(page, details, 1, 'title', material.title);
    await (await cellAt(details, 1, 'columns')).dblclick();
    await setColumns(page, material.columns);

    await typeCell(page, details, 2, 'key', pkg.key);
    await typeCell(page, details, 2, 'title', pkg.title);
    await selectCell(page, details, 2, 'source', '包材（COST_PACKAGE）');
    await (await cellAt(details, 2, 'columns')).dblclick();
    await setColumns(page, pkg.columns);

    await typeCell(page, details, 3, 'key', goods.key);
    await typeCell(page, details, 3, 'title', goods.title);
    await selectCell(page, details, 3, 'region', '受影响单据');
    await typeCell(page, details, 3, 'source', goods.source);
    await editCondition(page, details, 3, goods.condition, false);
    await typeCell(page, details, 3, 'targetTable', goods.targetTable);
    // 主键列：读到视图的列后是下拉，还没读到时先按文本编辑（section-columns.ts displayColumns），两种都填 GOODSID
    const keyCell = await cellAt(details, 3, 'keyColumn');
    await keyCell.dblclick();
    const editing = details.locator('.ag-cell-inline-editing');
    await expect(editing).toBeVisible();
    const picker = editing.locator('.ag-picker-field-wrapper');
    if (await picker.count()) {
      const items = page.locator('.ag-select-list .ag-list-item');
      if (!(await items.count())) await picker.first().click();
      await items
        .filter({ hasText: /^\s*GOODSID\s*$/ })
        .first()
        .click();
    } else {
      await page.keyboard.press('Control+A');
      await page.keyboard.type('GOODSID');
      await page.keyboard.press('Enter');
    }
    await expect(keyCell).toHaveText('GOODSID');
    await (await cellAt(details, 3, 'columns')).dblclick();
    await setColumns(page, goods.columns);
    await selectCell(page, details, 3, 'selection', '全部执行，不能取消');
    await (await cellAt(details, 3, 'actions')).dblclick();
    const actions = dialog(page);
    await expect(actions).toContainText('审批通过后写入的字段');
    await actions.getByRole('button', { name: '新增写入字段' }).click();
    await actions.locator('.write-row .n-select').first().click();
    await page.keyboard.type('ZX_PRICE');
    await page
      .locator('.n-base-select-option', { hasText: /^ZX_PRICE$/ })
      .first()
      .click();
    await actions.getByLabel('第 1 个写入字段的取值').fill(':new_PRICE');
    await apply(page);

    // 通知：提交审批 → 本级审批人；审批通过、审批驳回 → 申请人
    await section.getByRole('button', { name: /^通知/ }).click();
    const notifyGrid = dialog(page).locator('.ag-root-wrapper');
    const addNotice = dialog(page).getByRole('button', { name: '新增通知' });
    await addNotice.click();
    await addNotice.click();
    await addNotice.click();
    await selectCell(page, notifyGrid, 1, 'event', '审批通过');
    await selectCell(page, notifyGrid, 1, 'to', '申请人');
    await selectCell(page, notifyGrid, 2, 'event', '审批驳回');
    await selectCell(page, notifyGrid, 2, 'to', '申请人');
    await apply(page);

    // 校验、保存
    await section.getByRole('button', { name: '校验配置' }).click();
    await expect(page.getByText(/配置校验通过/).first()).toBeVisible();
    await section.getByRole('button', { name: '保存并发布当前流程' }).click();
    await toast(page, '流程已整体保存，并已回读确认');
    const saved = await adminApi.get(`/api/config/items/approvalFlow/${code}`);
    expect(saved.name).toBe(name);
    const { order, ...content } = saved.content;
    expect(typeof order).toBe('number');
    expect(content).toEqual(FLOW);
  }
);

// ---------------------------------------------------------------- 4b 审批

test('场景 4b 审批：成本会计改单价提交审批并冻结，管理员在待办中通过，申请人收到已通过、单据解冻', async ({
  page: admin,
  as,
  data,
  api
}) => {
  const goods = data.goods('75');
  const { docId, rows } = await data.newDoc([{ GOODSID: goods, PER_HL: '10', PRICE: '75' }]);
  const [line] = rows;
  const adminEvents = realtimeEvents(admin);
  await admin.goto('/home');

  const user = await as('chengben01');
  const userEvents = realtimeEvents(user);
  const open = async () => {
    await openDoc(user, docId);
    await showDetail(user, '原料/辅料');
    return detailGrid(user, 'COST_MATERIAL');
  };
  let grid = await open();
  const totalFl = await (await cell(masterGrid(user), docId, 'TOTAL_FL')).textContent();
  await edit(user, await cell(grid, line, 'PRICE'), '90');
  await expect(await cell(grid, line, 'COST_BATCH')).toHaveText('900'); // 预览
  await expect(await cell(masterGrid(user), docId, 'TOTAL_FL')).not.toHaveText(totalFl!);
  await expect(user.getByText(/行未保存/)).toBeVisible();
  const submitted = await save(user);
  expect(submitted.outcome).toBe('approvalSubmitted');
  const approvalId = submitted.approvals[0].approvalId;
  await toast(user, new RegExp(`单据 ${docId} 已提交审批`));
  await expect(await cell(grid, line, 'PRICE')).toHaveText('75.00'); // 审批结束前显示正式数据
  // 再改这张单据：弹出审批进度，不进入编辑
  await (await cell(grid, line, 'PRICE')).dblclick();
  const progress = user.locator('.approval-progress');
  await expect(progress.getByText('审批编号')).toBeVisible();
  await expect(progress).toContainText(approvalId);
  await expect(progress).toContainText('待处理');
  await progress.getByRole('button', { name: '关闭' }).click();
  expect(await grid.locator('.ag-cell-inline-editing').count()).toBe(0);

  // admin：铃铛里有这条审批的通知；待办中打开详情并通过
  const link = `/approval/${approvalId}`;
  await expect.poll(() => noticed(adminEvents, link)).toBe(true);
  await expect(await notice(admin, `业务单据为${docId}的审批`)).toBeVisible();
  await admin.keyboard.press('Escape');
  const detail = await openTodo(admin, docId, approvalId);
  await expect(detail).toContainText('原辅料（1）');
  await expect(detail).toContainText('75.00');
  await expect(detail).toContainText('90.00');
  await passInDetail(admin, detail);

  // 申请人：收到"已通过"；我的发起里是已通过；单据解冻，单价 90.00、能编辑
  await expect.poll(() => noticed(userEvents, link, true)).toBe(true);
  await expect(await notice(user, `业务单据为${docId}的审批已通过`)).toBeVisible();
  await user.keyboard.press('Escape');
  await openMenu(user, '待办');
  await user.waitForURL('**/approval');
  const todo = user.locator('.approval-todo-page');
  await todo.locator('.n-tabs-tab', { hasText: '我的发起' }).click();
  await expect(todo.locator('.ag-center-cols-container .ag-row', { hasText: `${docId}（` }).first()).toContainText(
    '已通过'
  );
  grid = await open();
  await expect(await cell(grid, line, 'PRICE')).toHaveText('90.00');
  expect(await canEdit(user, await cell(grid, line, 'PRICE'))).toBe(true);
  await expect(user.getByText(/行未保存/)).toHaveCount(0);
  const after = (await api.record(docId)).details.COST_MATERIAL[0].values;
  expect([after.PRICE, after.COST_BATCH]).toEqual(['90', '900']);
  expect(data.showGoods(goods).zxPrice).toBe('90');
});
