/**
 * 自定义导出（FP-19，同旧系统成本核算页主表右键的"自定义导出"）：admin 打开成本核算（/page/COST_PINGGU），按单据号筛选 2550，
 * 主表右键 → 自定义导出 → "物料成本核算表导出 - 导出当前"，浏览器下载到"物料成本核算表导出.xlsx"，
 * 文件里是"物料成本核算""明细_2550"两张工作表（d_cg 的导出配置 cost-pinggu-export，明细每张主单一张工作表）。
 * 只读：不改数据；工作表名称由 backend/tests/e2e/xlsx_sheets.py 读下载文件的 xl/workbook.xml。
 */
import { backendScript, cell, expect, masterGrid, openDoc, test, toast } from './support';

test('admin 按单据号筛选 2550，主表右键"自定义导出"导出当前，下载物料成本核算表导出.xlsx', async ({
  page
}, testInfo) => {
  await openDoc(page, '2550');
  await (await cell(masterGrid(page), '2550', 'DOCID')).click({ button: 'right' });
  const menu = page.locator('.ag-menu').filter({ visible: true });
  await menu.locator('.ag-menu-option', { hasText: '自定义导出' }).hover();
  const current = page.locator('.ag-menu-option', { hasText: '物料成本核算表导出 - 导出当前' });
  await expect(page.locator('.ag-menu-option', { hasText: '物料成本核算表导出 - 导出所有' })).toBeVisible();

  const [request, download] = await Promise.all([
    page.waitForRequest(r => r.url().endsWith('/api/pages/COST_PINGGU/export') && r.method() === 'POST'),
    page.waitForEvent('download'),
    current.click()
  ]);
  await toast(page, '导出已开始');
  // 导出当前带主表当前的筛选（单据号 2550）
  const body = request.postDataJSON();
  expect(body).toMatchObject({ mode: 'config', exportCode: 'cost-pinggu-export', scope: 'current' });
  expect(String(body.request.filterModel.DOCID.filter)).toBe('2550');

  expect(download.suggestedFilename()).toBe('物料成本核算表导出.xlsx');
  const file = testInfo.outputPath('物料成本核算表导出.xlsx');
  await download.saveAs(file);
  const { sheets } = JSON.parse(backendScript('tests.e2e.xlsx_sheets', [file]).at(-1)!);
  expect(sheets).toEqual(['物料成本核算', '明细_2550']);
});
