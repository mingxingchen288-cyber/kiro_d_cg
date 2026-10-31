/**
 * 第 8 批 G1（2026-10-31）：三个基础资料页，对照旧系统 cmx 的页面配置（goods-manage、customer-manage、formoney-manage，
 * T_COST_PAGE_COMPONENT 第 61、62 行等，.reports/batch8-20261031/g1-basic-pages/q01、q02）。页面由通用页面按页面编码打开，
 * 配置在 backend/seed/config 的 page/entity/operation/rule 的 GOODS_MANAGE、CUSTOMER_MANAGE、FORMONEY_MANAGE。
 *
 * 1. 客户信息 → 产品信息维护 → 成本核算的两个 Lookup：在客户信息新增客户和它的分销商；在产品信息维护新增产品，客户 ID 经
 *    客户 Lookup 选这个客户（回填客户名称、国家、分销商）；保存后华益代码为 'OV' || 产品ID、创建人为 admin（旧系统新增写
 *    CREATE_BY = 登录名）。成本核算的客户选择、产品选择（V_COST_CUSTOMER_LOOKUP、V_COST_GOODS_LOOKUP，改读 d_cg 的表）
 *    里能选到它们。ERP 产品 392、ERP 客户 86 和它的分销商整行绿底、不能改（旧 GRID_STYLE、EDITABLE 规则）。
 * 2. 外币管理"同步ERP汇率"：两行测试外币（system 建的本地汇率 9.99、PF_TEST 建的 2.5）；点按钮后 system 的那行本地汇率清空，
 *    PF_TEST 的不变，人民币、欧元、英镑、美元显示 ERP 的汇率（旧按钮 SQL：UPDATE T_COST_FORMONEY SET FMRATE = NULL …
 *    WHERE CREATE_BY = 'system'）。
 *
 * 测试数据自己建、结束时删（backend/tests/e2e/basic_pages.py）：客户（连同分销商）、产品经页面建，外币直接写表（页面上外币的
 * 各列都不能填，同旧列配置）。
 *
 * 待主代理合并后运行：要合并后的后端（entity 的 createdByColumn、有 readView 时只锁表）和 d_cg 中外币管理的配置
 * （.reports/batch8-20261031/g1-basic-pages/save_g1_config.py after-merge）。
 */
import { formatScale } from '../../src/modules/page/fields';
import type { Row } from './data';
import {
  type Locator,
  type Page,
  backendScript,
  test as base,
  canEdit,
  cell,
  detailGrid,
  edit,
  expect,
  filterColumn,
  masterGrid,
  mustSave,
  openPage,
  runButton,
  save,
  showDetail,
  toast,
  toolbar
} from './support';

const ERP_GREEN = 'rgb(230, 255, 237)';
/** ERP 产品（d_cg 的 T_COST_GOODS：ISERP = 1、产成品，500mg对乙酰氨基酚片） */
const ERP_GOODS = '392';
/** ERP 客户（ISERP = 1，有 1 个 ERP 分销商） */
const ERP_CUSTOMER = '86';

type Made = { currencies: string[]; goods: string[]; customers: string[] };

const test = base.extend<{ made: Made }>({
  // eslint-disable-next-line no-empty-pattern
  made: async ({}, use) => {
    const made: Made = { currencies: [], goods: [], customers: [] };
    await use(made);
    backendScript('tests.e2e.basic_pages', [
      'drop',
      '--currencies',
      made.currencies.join(','),
      '--goods',
      made.goods.join(','),
      '--customers',
      made.customers.join(',')
    ]);
  }
});

type LookupBody = { rows: Array<{ values: Record<string, string | null> }> };

/** 点一格选中这一行（这三个页面没有固定在左侧的列） */
async function pick(grid: Locator, rowId: string, column: string) {
  await (await cell(grid, rowId, column)).click();
  await expect(grid.locator(`.ag-row-selected[row-id="${rowId}"]`).first()).toBeVisible();
}

/** 保存后新行的 row-id 可能还是临时编号，也可能已换成主键 */
async function savedRowId(grid: Locator, key: string, clientRowId: string) {
  const either = grid.locator(`.ag-row[row-id="${key}"], .ag-row[row-id="${clientRowId}"]`);
  await expect(either.first()).toBeVisible();
  return (await either.first().getAttribute('row-id'))!;
}

/** 明细区的按钮：页签方式在明细栏右侧，堆叠方式在明细标题旁 */
function detailButton(page: Page, entity: string, label: string) {
  return page
    .locator('.generic-page__detail-bar')
    .getByRole('button', { name: label, exact: true })
    .or(detailGrid(page, entity).locator('.flex-y-center').getByRole('button', { name: label, exact: true }))
    .first();
}

async function newMasterRow(page: Page) {
  await toolbar(page).getByRole('button', { name: '新增', exact: true }).click();
  const row = masterGrid(page).locator('.ag-center-cols-container .ag-row.row-new').first();
  await expect(row).toBeVisible();
  return (await row.getAttribute('row-id'))!;
}

test('客户信息新增客户和分销商，产品信息维护经客户 Lookup 选它新增产品；成本核算的客户、产品选择能选到；ERP 行绿底不能改', async ({
  page,
  api,
  made
}) => {
  const suffix = crypto.randomUUID().slice(0, 6).toUpperCase();
  const customerName = `PF_TEST 客户${suffix}`;
  const distributorName = `PF_TEST 分销商${suffix}`;
  const productName = `PF_TEST 产品${suffix}`;

  // ---------------- 客户信息：新增客户
  await openPage(page, 'CUSTOMER_MANAGE');
  const customers = masterGrid(page);
  const customerRow = await newMasterRow(page);
  await edit(page, await cell(customers, customerRow, 'CUSTOMNAME'), customerName);
  await edit(page, await cell(customers, customerRow, 'ZONE'), 'PF_TEST 国家');
  const customerSaved = mustSave(await save(page));
  const customerId = String(customerSaved.idMap[customerRow]);
  made.customers.push(customerId);
  await toast(page, '已保存');

  // 选中新客户，在明细"分销商"新增一行
  await pick(customers, await savedRowId(customers, customerId, customerRow), 'CUSTOMNAME');
  await showDetail(page, '分销商');
  await detailButton(page, 'COST_TRANPOSER', '新增').click();
  const distributors = detailGrid(page, 'COST_TRANPOSER');
  const added = distributors.locator('.ag-center-cols-container .ag-row.row-new').first();
  await expect(added).toBeVisible();
  const distributorRow = (await added.getAttribute('row-id'))!;
  await edit(page, await cell(distributors, distributorRow, 'TRANPOSNAME'), distributorName);
  const distributorSaved = mustSave(await save(page));
  const distributorId = String(distributorSaved.idMap[distributorRow]);
  const customer = await api.record(customerId, 'CUSTOMER_MANAGE');
  expect([customer.master.values.CUSTOMNAME, customer.master.values.ZONE, customer.master.values.ISERP]).toEqual([
    customerName,
    'PF_TEST 国家',
    '0'
  ]);
  expect(customer.details.COST_TRANPOSER.map(r => [r.rowKey, r.values.TRANPOSNAME, r.values.CUSTOMID])).toEqual([
    [distributorId, distributorName, customerId]
  ]);

  // ERP 客户 86：整行绿底、不能改；它的 ERP 分销商同样
  await filterColumn(page, 'CUSTOMID', ERP_CUSTOMER);
  const erpCustomer = customers.locator(`.ag-center-cols-container .ag-row[row-id="${ERP_CUSTOMER}"]`);
  await expect(erpCustomer).toHaveCSS('background-color', ERP_GREEN);
  expect(await canEdit(page, await cell(customers, ERP_CUSTOMER, 'CUSTOMNAME'))).toBe(false);
  await pick(customers, ERP_CUSTOMER, 'ZONE');
  await showDetail(page, '分销商');
  const erpDistributor = distributors.locator('.ag-center-cols-container .ag-row').first();
  await expect(erpDistributor).toHaveCSS('background-color', ERP_GREEN);
  const erpDistributorId = (await erpDistributor.getAttribute('row-id'))!;
  expect(await canEdit(page, await cell(distributors, erpDistributorId, 'TRANPOSNAME'))).toBe(false);

  // ---------------- 产品信息维护：新增产品，客户 ID 经客户 Lookup 选上面的客户
  await openPage(page, 'GOODS_MANAGE');
  const products = masterGrid(page);
  const productRow = await newMasterRow(page);
  await (await cell(products, productRow, 'ZX_CUSTOMERID')).dblclick();
  const dialog = page.locator('.lookup-dialog');
  await expect(dialog.locator('.ag-center-cols-container .ag-row').first()).toBeVisible();
  const searched = page.waitForResponse(r => r.url().endsWith('/api/lookups/costCustomer/search'));
  await dialog.getByPlaceholder('输入关键字搜索').fill(customerName);
  await dialog.getByPlaceholder('输入关键字搜索').press('Enter');
  await searched;
  await dialog
    .locator('.ag-center-cols-container .ag-row')
    .filter({ has: page.locator('[col-id="CUSTOMID"]', { hasText: new RegExp(`^${customerId}$`) }) })
    .first()
    .dblclick();
  await expect(dialog).toHaveCount(0);
  await expect(await cell(products, productRow, 'ZX_CUSTOMERID')).toHaveText(customerId);
  await expect(await cell(products, productRow, 'CUSTOMNAME')).toHaveText(customerName);
  await expect(await cell(products, productRow, 'ZONE')).toHaveText('PF_TEST 国家');
  await expect(await cell(products, productRow, 'TRANPOSNAME')).toHaveText(distributorName);
  await expect(await cell(products, productRow, 'TRANPOSID')).toHaveText(distributorId);
  await edit(page, await cell(products, productRow, 'GOODSNAME'), productName);
  await edit(page, await cell(products, productRow, 'GOODSTYPE'), '10mg');
  const productSaved = mustSave(await save(page));
  const productId = String(productSaved.idMap[productRow]);
  made.goods.push(productId);
  await toast(page, '已保存');

  const [product] = (
    await api.ok<{ rows: Row[] }>('POST', '/api/pages/GOODS_MANAGE/rows/by-keys', {
      entity: 'COST_GOODS',
      rowKeys: [productId]
    })
  ).rows;
  const shown = product.values;
  expect([shown.GOODSNO, shown.GOODSNAME, shown.CUSTOMNAME, shown.ZONE, shown.TRANPOSNAME, shown.CREATE_BY]).toEqual([
    `OV${productId}`,
    productName,
    customerName,
    'PF_TEST 国家',
    distributorName,
    'admin'
  ]);

  // 重新打开、按产品ID 筛选：页面显示视图带出的华益代码、创建人
  await openPage(page, 'GOODS_MANAGE');
  await filterColumn(page, 'GOODSID', productId);
  await expect(await cell(products, productId, 'GOODSNO')).toHaveText(`OV${productId}`);
  await expect(await cell(products, productId, 'CREATE_BY')).toHaveText('admin');

  // ERP 产品 392：整行绿底、不能改
  await filterColumn(page, 'GOODSID', ERP_GOODS);
  await expect(products.locator(`.ag-center-cols-container .ag-row[row-id="${ERP_GOODS}"]`)).toHaveCSS(
    'background-color',
    ERP_GREEN
  );
  expect(await canEdit(page, await cell(products, ERP_GOODS, 'GOODSNAME'))).toBe(false);

  // ---------------- 成本核算的客户选择、产品选择（数据源改读 d_cg 的表）
  const customerLookup = await api.ok<LookupBody>('POST', '/api/lookups/costCustomer/search', {
    keyword: customerName,
    startRow: 0,
    endRow: 50
  });
  expect(
    customerLookup.rows
      .filter(r => r.values.CUSTOMID === customerId)
      .map(r => [r.values.CUSTOMNAME, r.values.COUNTRY, r.values.LIVERY, r.values.TRANPOSID])
  ).toEqual([[customerName, 'PF_TEST 国家', distributorName, distributorId]]);
  const goodsLookup = await api.ok<LookupBody>('POST', '/api/lookups/costGoods/search', {
    keyword: productName,
    startRow: 0,
    endRow: 50
  });
  expect(
    goodsLookup.rows
      .filter(r => r.values.GOODSID === productId)
      .map(r => [r.values.GOODSNAME, r.values.CUSTOMNAME, r.values.LIVERY, r.values.STRENGTH, r.values.MEMO])
  ).toEqual([[productName, customerName, distributorName, '10mg', 'ERP未搭建BOM']]);
});

test('外币管理：同步ERP汇率清空 system 建的外币的本地汇率，其余不动；人民币、欧元、英镑、美元显示 ERP 的汇率', async ({
  page,
  api,
  made
}) => {
  const currency = (name: string, by: string, rate: string) => {
    const { fmid } = JSON.parse(
      backendScript('tests.e2e.basic_pages', ['currency', '--name', name, '--by', by, '--rate', rate]).at(-1)!
    ) as { fmid: string };
    made.currencies.push(fmid);
    return fmid;
  };
  const bySystem = currency('PF_TEST 外币甲', 'system', '9.99');
  const byOther = currency('PF_TEST 外币乙', 'PF_TEST', '2.5');
  // ERP 的汇率在用例运行时只读查询（经 ERP 数据库链接取出，会变），不写死
  const erp = JSON.parse(backendScript('tests.e2e.basic_pages', ['erp-rates']).at(-1)!) as Record<
    string,
    string | null
  >;
  expect(Object.keys(erp).sort()).toEqual(['0', '1', '21', '22']);
  const { scale } = (await api.view('FORMONEY_MANAGE')).master.fields.find(f => f.name === 'FMRATE')!;
  const shown = (rate: string | null) => (rate === null ? '' : formatScale(rate, scale));

  await openPage(page, 'FORMONEY_MANAGE');
  const grid = masterGrid(page);
  await expect(await cell(grid, bySystem, 'FMRATE')).toHaveText(shown('9.99'));
  await expect(await cell(grid, byOther, 'FMRATE')).toHaveText(shown('2.5'));
  for (const [fmid, rate] of Object.entries(erp))
    // eslint-disable-next-line no-await-in-loop
    await expect(await cell(grid, fmid, 'FMRATE'), `外币 ${fmid}`).toHaveText(shown(rate));

  mustSave(await runButton(page, '同步ERP汇率'));
  await toast(page, '同步ERP汇率已完成');
  await expect(await cell(grid, bySystem, 'FMRATE')).toHaveText('');
  await expect(await cell(grid, byOther, 'FMRATE')).toHaveText(shown('2.5'));
  for (const [fmid, rate] of Object.entries(erp))
    // eslint-disable-next-line no-await-in-loop
    await expect(await cell(grid, fmid, 'FMRATE'), `外币 ${fmid}`).toHaveText(shown(rate));

  const read = await api.ok<{ rows: Row[] }>('POST', '/api/pages/FORMONEY_MANAGE/rows/by-keys', {
    entity: 'COST_FORMONEY',
    rowKeys: [bySystem, byOther]
  });
  expect(new Map(read.rows.map(r => [r.rowKey, r.values.FMRATE ?? null]))).toEqual(
    new Map([
      [bySystem, null],
      [byOther, '2.5']
    ])
  );
});
