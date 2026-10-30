/**
 * T-AS-9 业务例子 E01：admin 在成本核算页把单据主表的备注改为"测试"并保存；重新打开页面显示"测试"；再改回原值保存。
 * 数据隔离：经平台复制 200680（只有主表，cmx 中已经没有明细）出一张测试成本单，改它，用例结束时删除。
 * 成本核算页由通用页面按页面编码打开：`/page/COST_PINGGU`（frontend-page，C11）。
 */
import { type Page, cell, edit, expect, masterGrid, openDoc, save, test, toast } from './support';

async function editMemo(page: Page, docId: string, value: string) {
  await edit(page, await cell(masterGrid(page), docId, 'MEMO'), value);
  await expect(page.getByText('1 行未保存')).toBeVisible();
  expect((await save(page)).outcome).toBe('saved');
  await toast(page, '已保存');
  await expect(await cell(masterGrid(page), docId, 'MEMO')).toHaveText(value);
}

test('E01：admin 把测试成本单的备注改为"测试"，重新打开显示"测试"，再改回原值', async ({ page, data, api }) => {
  const { docId } = await data.copyDoc('200680', { details: 'none' });
  await openDoc(page, docId);
  const original = ((await (await cell(masterGrid(page), docId, 'MEMO')).textContent()) ?? '').trim();
  expect(original).toBe(data.marker);

  await editMemo(page, docId, '测试');
  await openDoc(page, docId);
  await expect(await cell(masterGrid(page), docId, 'MEMO')).toHaveText('测试');
  expect((await api.record(docId)).master.values.MEMO).toBe('测试');

  await editMemo(page, docId, original);
  await openDoc(page, docId);
  await expect(await cell(masterGrid(page), docId, 'MEMO')).toHaveText(original);
  expect((await api.record(docId)).master.values.MEMO).toBe(original);
});
