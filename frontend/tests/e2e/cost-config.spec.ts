/**
 * 第 7 批 CF 组（2026-10-31）：成本核算主表的币种 Lookup 和状态下拉，对照旧系统 cost-pinggu 的列配置
 * （cmx T_COST_COLUMN_METADATA：FMNAME 的 Lookup formoney 回填 FMNAME、FMRATE；USESTATUS 的 agSelectCellEditor 5 个值）。
 * 配置在 backend/seed/config 的 lookup.formoney、dict.COST_PINGGU.USESTATUS、page/entity/operation 的 COST_PINGGU；
 * 币种的数据源 T_COST_FORMONEY_V 由 `platform db copy-business-tables` 建（2026-10-31 起读 d_cg 的外币表，本地汇率为空时
 * 取 cmx 经 ERP 数据库链接读的汇率，第 8 批 G1）。
 * 写数据的用自己的测试成本单（data.copyDoc('2550')：2550 的币种是人民币、汇率 1、状态商业化），用例结束时删除。
 */
import { formatScale } from '../../src/modules/page/fields';
import { samePrice } from './data';
import { backendScript, cell, expect, masterGrid, mustSave, openDoc, save, test, toast } from './support';

/** 旧系统 USESTATUS 下拉的 5 个值，顺序同旧列配置的 cellEditorParams.values */
const STATUSES = ['商业化', '已立项', '评估中', '商业化-成本复核', '已立项-成本复核'];

test('币种：双击币种打开币种选择，选"欧元"，汇率带出 T_COST_FORMONEY_V 中欧元的汇率；保存后重读一致', async ({
  page,
  data,
  api
}) => {
  const doc = await data.copyDoc('2550');
  // 欧元的汇率在用例运行时直接读旧系统的视图（汇率经 ERP 数据库链接取出，会变），不写死
  const euro = JSON.parse(backendScript('tests.e2e.formoney', ['欧元']).at(-1)!) as {
    FMNAME: string;
    FMRATE: string;
  };
  expect(euro.FMRATE).toBeTruthy();
  const rate = (await api.view()).master.fields.find(f => f.name === 'FMRATE')!;
  const rateText = formatScale(euro.FMRATE, rate.scale);

  await openDoc(page, doc.docId);
  const grid = masterGrid(page);
  await (await cell(grid, doc.docId, 'FMNAME')).dblclick();
  const dialog = page.locator('.lookup-dialog');
  await expect(dialog.locator('.ag-center-cols-container .ag-row').first()).toBeVisible();
  await dialog
    .locator('.ag-center-cols-container .ag-row')
    .filter({ has: page.locator('[col-id="FMNAME"]', { hasText: /^欧元$/ }) })
    .first()
    .dblclick();
  await expect(dialog).toHaveCount(0);
  await expect(await cell(grid, doc.docId, 'FMNAME')).toHaveText('欧元');
  await expect(await cell(grid, doc.docId, 'FMRATE')).toHaveText(rateText);

  mustSave(await save(page));
  await toast(page, '已保存');
  const master = (await api.record(doc.docId)).master.values;
  expect(master.FMNAME).toBe('欧元');
  expect(samePrice(master.FMRATE, euro.FMRATE), `汇率 ${master.FMRATE} 应为 ${euro.FMRATE}`).toBe(true);

  await openDoc(page, doc.docId);
  await expect(await cell(grid, doc.docId, 'FMNAME')).toHaveText('欧元');
  await expect(await cell(grid, doc.docId, 'FMRATE')).toHaveText(rateText);
});

test('状态：下拉列出旧系统的 5 个值，选"已立项"保存后重读一致', async ({ page, data, api }) => {
  const doc = await data.copyDoc('2550');
  await openDoc(page, doc.docId);
  const grid = masterGrid(page);
  const target = await cell(grid, doc.docId, 'USESTATUS');
  await expect(target).toHaveText('商业化');

  await target.dblclick();
  await expect(grid.locator('.ag-cell-inline-editing')).toBeVisible();
  const items = page.locator('.ag-select-list .ag-list-item');
  if (!(await items.count())) await grid.locator('.ag-cell-inline-editing .ag-picker-field-wrapper').first().click();
  await expect(items.first()).toBeVisible();
  // 第一项是空白（清空状态），后面依次是字典的 5 个值
  const texts = (await items.allTextContents()).map(t => t.trim()).filter(Boolean);
  expect(texts).toEqual(STATUSES);
  await items
    .filter({ hasText: /^\s*已立项\s*$/ })
    .first()
    .click();
  await expect(grid.locator('.ag-cell-inline-editing')).toHaveCount(0);
  await expect(target).toHaveText('已立项');

  mustSave(await save(page));
  await toast(page, '已保存');
  expect((await api.record(doc.docId)).master.values.USESTATUS).toBe('已立项');

  await openDoc(page, doc.docId);
  await expect(await cell(grid, doc.docId, 'USESTATUS')).toHaveText('已立项');
});
