/**
 * 第 9 批 A 组：旧系统 cmx 的 7 个业务角色迁成新平台的角色（config 的 CF-21，T-CF-14，业务例子 E44）。
 * 依据用户 2026-10-31："角色你迁移过来"。角色配置是 seed 的 role.001 … role.008（d_cg 已经保存，版本 1），
 * 每一项与 cmx T_COST_ROLE_PAGE 的对照见 `.reports/batch9-20261031/a-roles/迁移对照.md`。
 *
 * 1. 采购（008，cmx T_COST_ROLE 127）：测试账号只有这个角色，从登录页登录。左侧菜单有旧系统授给采购的 6 个页面
 *    （旧 T_COST_ROLE_PAGE 338～343：物料成本核算表、物料成本核算表_液体、产品信息维护、客户信息、物料清单及成本、外币管理），
 *    没有审计追踪、配置、系统管理；物料清单页工具栏有新增、复制，没有删除，主表右键"自定义导出"下有
 *    "产品选择(按物料)导出"（旧"自定义导出:goods-price-pgoods-export"）。
 * 2. 采购在成本核算（旧 338）：主表有新增、复制、由BOM生成明细、保存，没有删除；出厂价(RMB)、每批销售额、每批加工费等列
 *    不显示，每批原料成本照常显示；批量、收率不能改，备注能改；原料/辅料的每片含量不能改、备注能改。
 *    单据是 data 复制 2550 建的测试单据，只看不改，结束时删除。
 * 3. 生产（007，cmx 126）：左侧菜单只有成本核算、液体成本核算、产品信息维护（旧 334～336）。
 * 只读：除测试账号和测试单据外不写数据，角色配置不改。
 */
import {
  type Locator,
  type Page,
  canEdit,
  cell,
  detailGrid,
  expect,
  header,
  login,
  masterGrid,
  menuTitles,
  openDoc,
  openPage,
  showDetail,
  test,
  toolbar
} from './support';

/** 一组按钮中看得到的文字 */
async function visibleTexts(buttons: Locator) {
  return buttons.evaluateAll(bs =>
    bs.filter(b => (b as HTMLElement).offsetParent !== null).map(b => (b.textContent ?? '').trim())
  );
}

/**
 * 菜单中的页面（去掉分组标题"成本""基础信息"）。最前面的"首页""待办"是外壳固定的入口，每个账号都有，不归角色管
 * （旧系统每个角色也都有首页）。
 */
async function menuPages(page: Page) {
  const titles = await menuTitles(page);
  return titles.filter(t => !['成本', '基础信息'].includes(t));
}

const SHELL = ['首页', '待办'];

test('采购（008）登录：菜单是旧系统授给采购的 6 个页面，物料清单右键有"产品选择(按物料)导出"', async ({
  data,
  fresh
}) => {
  const account = await data.account({ roleCodes: ['008'] });
  const user = await fresh();
  await login(user, account);
  const pages = await menuPages(user);
  expect(pages).toEqual([
    ...SHELL,
    '成本核算',
    '液体成本核算',
    '产品信息维护',
    '客户信息',
    '物料清单及成本',
    '外币管理'
  ]);
  for (const other of ['审计追踪', '配置', '系统管理']) expect(pages).not.toContain(other);

  await openPage(user, 'GOODS_PRICE_MANAGE');
  const top = await visibleTexts(toolbar(user).locator('button'));
  expect(top).toEqual(expect.arrayContaining(['新增', '复制', '保存']));
  expect(top).not.toContain('删除');
  const grid = masterGrid(user);
  await grid
    .locator('.ag-center-cols-container .ag-row')
    .first()
    .locator('[col-id="GOODSNAME"]')
    .click({ button: 'right' });
  const menu = user.locator('.ag-menu').filter({ visible: true });
  await menu.locator('.ag-menu-option', { hasText: '自定义导出' }).hover();
  await expect(user.locator('.ag-menu-option', { hasText: '产品选择(按物料)导出 - 导出当前' })).toBeVisible();
  await expect(user.locator('.ag-menu-option', { hasText: '产品选择(按物料)导出 - 导出所有' })).toBeVisible();
  await user.keyboard.press('Escape');
});

test('采购在成本核算：没有删除；出厂价等列不显示；批量、收率、每片含量不能改，备注能改', async ({ data, fresh }) => {
  const doc = await data.copyDoc('2550');
  const account = await data.account({ roleCodes: ['008'] });
  const user = await fresh();
  await login(user, account);
  await openDoc(user, doc.docId);

  const top = await visibleTexts(toolbar(user).locator('button'));
  expect(top).toEqual(expect.arrayContaining(['新增', '复制', '由BOM生成明细', '保存']));
  expect(top).not.toContain('删除');

  const master = masterGrid(user);
  await expect(header(master, 'TOTAL_YL')).toBeAttached();
  const columns = await master
    .locator('.ag-header-row-column .ag-header-cell')
    .evaluateAll(cells => cells.map(c => c.getAttribute('col-id')));
  const hidden = ['OUT_PRICE_RMB', 'SALEMONEY', 'JGF_BATCH', 'OUT_PRICE_F', 'Y_SALE'];
  expect(columns.filter(c => hidden.includes(c ?? ''))).toEqual([]);
  expect(await canEdit(user, await cell(master, doc.docId, 'APEX_PL'))).toBe(false);
  expect(await canEdit(user, await cell(master, doc.docId, 'YIELD'))).toBe(false);
  expect(await canEdit(user, await cell(master, doc.docId, 'MEMO'))).toBe(true);

  await showDetail(user, '原料/辅料');
  const materials = detailGrid(user, 'COST_MATERIAL');
  const first = (await materials.locator('.ag-center-cols-container .ag-row').first().getAttribute('row-id'))!;
  expect(await canEdit(user, await cell(materials, first, 'PER_HL'))).toBe(false);
  expect(await canEdit(user, await cell(materials, first, 'MEMO'))).toBe(true);
});

test('生产（007）登录：菜单只有成本核算、液体成本核算、产品信息维护', async ({ data, fresh }) => {
  const account = await data.account({ roleCodes: ['007'] });
  const user = await fresh();
  await login(user, account);
  expect(await menuPages(user)).toEqual([...SHELL, '成本核算', '液体成本核算', '产品信息维护']);
});
