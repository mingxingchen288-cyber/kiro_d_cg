/**
 * T-AZ-2 区域的新增、删除、修改（业务例子 E42）。依据用户 2026-10-30："权限可以按照新增 删除 修改 保存 这样给吗？
 * 控制到明细级别"。
 *
 * admin 经配置接口建一个 PF_TEST 角色：成本核算只给"保存"和原料/辅料的新增、删除、修改；建一个只有这个角色的测试账号。
 * 换这个账号从登录页登录，打开测试成本单（复制 2550）：
 * - 主表：工具栏没有新增、复制、删除，备注不能改；
 * - 原料/辅料：有明细新增、明细删除；改聚维酮K30 的备注、新增一行玉米淀粉（Lookup 选物料、填每片含量）、删除预胶化淀粉，
 *   保存成功，库里与页面一致；
 * - 包材：没有明细新增、明细删除，大纸箱这一行不能改。
 * 只改备注、新增行的单价取物料清单执行价，不触发成本明细改价审批。角色、账号、成本单在用例结束时删除。
 */
import {
  type Locator,
  type Page,
  canEdit,
  cell,
  detailGrid,
  edit,
  expect,
  login,
  masterGrid,
  mustSave,
  openDoc,
  save,
  showDetail,
  test,
  toast,
  toolbar
} from './support';

const K30 = '206323';
const PREGELATINIZED = '206324';
const CARTON = '206320';
const CORN_STARCH = '310';

/** 一组按钮中看得到的文字 */
async function visibleTexts(buttons: Locator) {
  return buttons.evaluateAll(bs =>
    bs.filter(b => (b as HTMLElement).offsetParent !== null).map(b => (b.textContent ?? '').trim())
  );
}

/** 明细的按钮：页签方式在明细栏右侧（只有当前页签的），堆叠方式在各明细的标题旁 */
async function detailButtons(page: Page, title: string, entity: string) {
  await showDetail(page, title);
  return visibleTexts(
    page.locator('.generic-page__detail-bar button').or(detailGrid(page, entity).locator('.flex-y-center button'))
  );
}

test(
  'E42 区域权限：只给保存和原辅料的新增、删除、修改，主表和包材不能改，原辅料能改、能增、能删并保存',
  { lock: 'page.COST_PINGGU', tag: '@shared-config' },
  async ({ data, adminApi, fresh }) => {
    const suffix = crypto.randomUUID().slice(0, 6).toUpperCase();
    const code = `PF_TEST_AZ_${suffix}`;
    const name = `PF_TEST区域权限${suffix}`;
    const buttons = ['system:save', 'COST_MATERIAL:addRow', 'COST_MATERIAL:deleteRow', 'COST_MATERIAL:modify'];
    data.adoptConfig(`role/${code}`);
    await adminApi.ok('PUT', `/api/config/items/role/${code}`, {
      name,
      content: { name, admin: false, pages: { COST_PINGGU: { buttons } } }
    });
    const doc = await data.copyDoc('2550');
    const account = await data.account({ roleCodes: [code] });

    const user = await fresh();
    await login(user, account);
    await openDoc(user, doc.docId);
    const master = masterGrid(user);
    const materials = detailGrid(user, 'COST_MATERIAL');
    const packages = detailGrid(user, 'COST_PACKAGE');

    // 主表：没有新增、复制、删除，已有的单据不能改
    const top = await visibleTexts(toolbar(user).locator('button'));
    expect(top).toContain('保存');
    for (const b of ['新增', '复制', '删除']) expect(top).not.toContain(b);
    expect(await canEdit(user, await cell(master, doc.docId, 'MEMO'))).toBe(false);

    // 包材：没有明细新增、明细删除，已有的行不能改
    const packageButtons = await detailButtons(user, '包材', 'COST_PACKAGE');
    for (const b of ['明细新增', '明细复制', '明细删除']) expect(packageButtons).not.toContain(b);
    const carton = doc.row(CARTON);
    expect(await canEdit(user, await cell(packages, carton, 'MEMO'))).toBe(false);
    expect(await canEdit(user, await cell(packages, carton, 'PER_HL'))).toBe(false);

    // 原料/辅料：有明细新增、明细删除（没有复制），已有的行能改
    const materialButtons = await detailButtons(user, '原料/辅料', 'COST_MATERIAL');
    expect(materialButtons).toEqual(expect.arrayContaining(['明细新增', '明细删除']));
    expect(materialButtons).not.toContain('明细复制');
    const k30 = doc.row(K30);
    await edit(user, await cell(materials, k30, 'MEMO'), '区域权限测试');

    // 删除预胶化淀粉：选中这一行，点明细删除
    const removed = doc.row(PREGELATINIZED);
    await (await cell(materials, removed, 'GOODSNAME')).click();
    await user.getByRole('button', { name: '明细删除', exact: true }).first().click();
    await expect(materials.locator(`.ag-row[row-id="${removed}"]`).first()).toHaveClass(/row-deleted/);

    // 新增一行：明细新增，物料经 Lookup 选玉米淀粉（单价带出物料清单执行价），填每片含量
    await user.getByRole('button', { name: '明细新增', exact: true }).first().click();
    const added = materials.locator('.ag-center-cols-container .ag-row.row-new').first();
    await expect(added).toBeVisible();
    const clientRowId = (await added.getAttribute('row-id'))!;
    await (await cell(materials, clientRowId, 'GOODSID')).dblclick();
    const dialog = user.locator('.lookup-dialog');
    await expect(dialog.locator('.ag-center-cols-container .ag-row').first()).toBeVisible();
    const searched = user.waitForResponse(r => r.url().endsWith('/api/lookups/costMaterialEffective/search'));
    await dialog.getByPlaceholder('输入关键字搜索').fill('玉米淀粉');
    await dialog.getByPlaceholder('输入关键字搜索').press('Enter');
    await searched;
    await dialog
      .locator('.ag-center-cols-container .ag-row')
      .filter({ has: user.locator('[col-id="GOODSID"]', { hasText: new RegExp(`^${CORN_STARCH}$`) }) })
      .first()
      .dblclick();
    await expect(dialog).toHaveCount(0);
    await expect(await cell(materials, clientRowId, 'GOODSNAME')).toHaveText('玉米淀粉');
    await edit(user, await cell(materials, clientRowId, 'PER_HL'), '10');

    const result = mustSave(await save(user));
    expect(result.approvals).toEqual([]);
    await toast(user, '已保存');
    const newRow = String(result.idMap[clientRowId]);
    const saved = (await adminApi.record(doc.docId)).details.COST_MATERIAL;
    const byKey = new Map(saved.map(r => [r.rowKey, r.values]));
    expect(byKey.get(k30)?.MEMO).toBe('区域权限测试');
    expect(byKey.has(removed)).toBe(false);
    expect([byKey.get(newRow)?.GOODSID, byKey.get(newRow)?.PER_HL]).toEqual([CORN_STARCH, '10']);
    await expect(await cell(materials, k30, 'MEMO')).toHaveText('区域权限测试');
  }
);
