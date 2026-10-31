/**
 * 物料清单的"产品选择(按物料)导出"（第 8 批 G3；seed `export.goods-price-pgoods-export`，同旧系统导出编码
 * goods-price-pgoods-export，cmx T_COST_EXPORT_CONFIG 21，旧页面 goods-price-manage 主表右键"自定义导出"）：
 * admin 打开物料清单（/page/GOODS_PRICE_MANAGE），按物料ID 筛选 406，主表右键 → 自定义导出 →
 * "产品选择(按物料)导出 - 导出当前"，浏览器下载"产品选择(按物料)导出.xlsx"。
 * backend/tests/e2e/pgoods_export.py 按旧代码 CustomExportService 推出旧系统对同样筛选会写出的文件（只读查 d_cg），逐格比较：
 * 文件名、唯一一张工作表"产品选择(按物料)"、表头（旧配置没写列，取第一行结果 HashMap 的键）、每一行每一格的类型和值。
 * 只读：不改数据。
 */
import { backendScript, cell, expect, filterColumn, masterGrid, openPage, test, toast } from './support';

const PAGE = 'GOODS_PRICE_MANAGE';
const GOODS = '406';

test('admin 按物料ID 筛选 406，右键"产品选择(按物料)导出 - 导出当前"，下载的文件与旧系统逐格一致', async ({
  page
}, testInfo) => {
  await openPage(page, PAGE);
  await filterColumn(page, 'GOODSID', GOODS);
  const grid = masterGrid(page);
  await expect(grid.locator('.ag-center-cols-container .ag-row')).toHaveCount(1);
  await (await cell(grid, GOODS, 'GOODSNAME')).click({ button: 'right' });
  const menu = page.locator('.ag-menu').filter({ visible: true });
  await menu.locator('.ag-menu-option', { hasText: '自定义导出' }).hover();
  const current = page.locator('.ag-menu-option', { hasText: '产品选择(按物料)导出 - 导出当前' });
  await expect(page.locator('.ag-menu-option', { hasText: '产品选择(按物料)导出 - 导出所有' })).toBeVisible();

  const [request, download] = await Promise.all([
    page.waitForRequest(r => r.url().endsWith(`/api/pages/${PAGE}/export`) && r.method() === 'POST'),
    page.waitForEvent('download'),
    current.click()
  ]);
  await toast(page, '导出已开始');
  // 导出当前带主表当前的筛选（物料ID 406）：旧系统接 WHERE EXISTS (页面视图 p.GOODSID = m.GOODSID 且筛选)
  const body = request.postDataJSON();
  expect(body).toMatchObject({ mode: 'config', exportCode: 'goods-price-pgoods-export', scope: 'current' });
  expect(String(body.request.filterModel.GOODSID.filter)).toBe(GOODS);

  const file = testInfo.outputPath(download.suggestedFilename());
  await download.saveAs(file);
  const result = JSON.parse(backendScript('tests.e2e.pgoods_export', [file, GOODS]).at(-1)!);
  expect(download.suggestedFilename()).toBe(result.fileName);
  expect(result.sheets).toEqual(['产品选择(按物料)']);
  // 旧系统的列：SQL 选出的列（GOODSNAME 选了两次，Map 里只有一个）按 HashMap 的顺序，表头就是列名
  expect(result.header).toEqual([
    'PGOODSID',
    'GOODSNAME',
    'GOODSID',
    'PRICE',
    'GOODSNO',
    'BATCH_QTY',
    'PGOODSNO',
    'APEX_PL',
    'DTL_USEFLAG',
    'FACTORYNAME'
  ]);
  expect(result.rows).toBeGreaterThan(0);
  expect(result.mismatches).toEqual([]);
});
