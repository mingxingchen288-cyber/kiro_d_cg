/**
 * 链路 1：成本核算主从页的明细。admin 打开成本核算（通用页面 /page/COST_PINGGU），选中成本单，
 * 在"原料/辅料"把聚维酮K30 这一行的备注改为"测试"并保存；重新打开显示"测试"；再改回原值保存。
 * "客户指定"复选框勾选、保存，重新打开仍勾选，再取消、保存。
 * 数据隔离：经平台复制 2550（250mg乙酰唑胺片，只带单价等于执行价的明细）出一张测试成本单，改它，用例结束时删除。
 * 明细按 admin 自己的个人配置显示为页签或上下堆叠（showDetail），用例两种都能跑，不改个人配置。
 */
import { type Page, cell, detailGrid, edit, expect, openDoc, save, showDetail, test, toast } from './support';

const K30 = '206323';

const materials = (page: Page) => detailGrid(page, 'COST_MATERIAL');

async function open(page: Page, docId: string, row: string) {
  await openDoc(page, docId);
  await showDetail(page, '原料/辅料');
  await expect(materials(page).locator(`.ag-center-cols-container .ag-row[row-id="${row}"]`)).toBeVisible();
}

async function saveAndWait(page: Page) {
  await expect(page.getByText('1 行未保存')).toBeVisible();
  expect((await save(page)).outcome).toBe('saved');
  await toast(page, '已保存');
  await expect(page.getByText('1 行未保存')).toBeHidden();
}

test('明细：admin 把原料/辅料一行的备注改为"测试"，重新打开显示"测试"，再改回原值', async ({ page, data, api }) => {
  const doc = await data.copyDoc('2550');
  const row = doc.row(K30);
  await open(page, doc.docId, row);
  const memo = () => cell(materials(page), row, 'MEMO');
  const original = ((await (await memo()).textContent()) ?? '').trim();
  expect(original).not.toBe('测试');

  await edit(page, await memo(), '测试');
  await saveAndWait(page);
  await expect(await memo()).toHaveText('测试');

  await open(page, doc.docId, row);
  await expect(await memo()).toHaveText('测试');

  await edit(page, await memo(), original);
  await saveAndWait(page);

  await open(page, doc.docId, row);
  await expect(await memo()).toHaveText(original);
  const saved = (await api.record(doc.docId)).details.COST_MATERIAL.find(r => r.rowKey === row)!;
  expect(saved.values.MEMO ?? '').toBe(original);
});

test('明细：admin 勾选原料/辅料一行的"客户指定"并保存，重新打开仍勾选，再取消', async ({ page, data, api }) => {
  const doc = await data.copyDoc('2550');
  const row = doc.row(K30);
  await open(page, doc.docId, row);
  const checkbox = async () =>
    (await cell(materials(page), row, 'CUSTOMER_SPECIFIED')).locator('input[type="checkbox"]');
  await expect(await checkbox()).not.toBeChecked();

  await (await checkbox()).click();
  await saveAndWait(page);
  await expect(await checkbox()).toBeChecked();

  await open(page, doc.docId, row);
  await expect(await checkbox()).toBeChecked();

  await (await checkbox()).click();
  await saveAndWait(page);

  await open(page, doc.docId, row);
  await expect(await checkbox()).not.toBeChecked();
  const saved = (await api.record(doc.docId)).details.COST_MATERIAL.find(r => r.rowKey === row)!;
  expect(saved.values.CUSTOMER_SPECIFIED).toBe(false);
});
