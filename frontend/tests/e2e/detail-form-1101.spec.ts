/**
 * T-FP-21 通用的行表单（FP-03）：明细区也能点 ⊞ 在表单里看和改这一行（2026-11-01）。
 * 依据用户 2026-11-01："我知道旧项目没有，但是新项目要有，而且主表已经有表单了，明明可以做成一个通用方法套用的，
 * 表单和表格可以公用一个元数据，表单唯一的区别仅仅是可以调整每个表单列的位置和带线（大小）"。旧系统没有行表单。
 *
 * admin 打开测试成本单（经平台复制 2550），在"原料/辅料"点聚维酮K30 那一行的 ⊞，明细区显示这一行的表单；在表单里把备注改为
 * "表单测试"并保存，提示"已保存"；返回后表格同一行也是"表单测试"、选中行还在；重新打开再点 ⊞，表单里是改后的值，接口读回也是。
 * 测试数据由 fixture 结束时删除；不改共用配置（原料/辅料的表单布局用 d_cg 上现有的配置）。
 */
import { type Page, cell, detailGrid, expect, openDoc, save, showDetail, test, toast } from './support';

const K30 = '206323';
const MEMO = '表单测试';

const materials = (page: Page) => detailGrid(page, 'COST_MATERIAL');

async function open(page: Page, docId: string, row: string) {
  await openDoc(page, docId);
  await showDetail(page, '原料/辅料');
  await expect(materials(page).locator(`.ag-center-cols-container .ag-row[row-id="${row}"]`)).toBeVisible();
}

/** 点明细这一行最前面的 ⊞，等明细区显示表单（明细表格只设为不可见） */
async function openForm(page: Page, row: string) {
  await materials(page).locator(`.ag-row[row-id="${row}"] [col-id="__form"] button`).first().click();
  const form = materials(page).locator('.record-form');
  await expect(form).toBeVisible();
  await expect(materials(page).locator(`.ag-center-cols-container .ag-row[row-id="${row}"]`)).toBeHidden();
  return form;
}

test('明细表单：admin 在原料/辅料点聚维酮K30 的 ⊞，表单里把备注改为"表单测试"并保存，重新打开表单里是改后的值', async ({
  page,
  data,
  api
}) => {
  const doc = await data.copyDoc('2550');
  const row = doc.row(K30);
  await open(page, doc.docId, row);

  const form = await openForm(page, row);
  await expect(form.locator('.record-form__header')).toContainText('原料/辅料 聚维酮K30');
  const field = form.locator('[data-field="MEMO"]');
  const memo = field.locator('input');
  await expect(memo).not.toHaveValue(MEMO);
  await memo.fill(MEMO);
  await memo.press('Enter');
  await expect(page.getByText('1 行未保存')).toBeVisible();
  await expect(field).toHaveClass(/cell-user-changed/);

  // 表单开着时点工具栏的保存，同在表格里改
  expect((await save(page)).outcome).toBe('saved');
  await toast(page, '已保存');
  await expect(page.getByText('1 行未保存')).toBeHidden();
  await expect(memo).toHaveValue(MEMO);
  await expect(field).not.toHaveClass(/cell-user-changed/);

  // 返回：表格同一行显示改后的值，选中行还在
  await form.getByRole('button', { name: '返回', exact: true }).click();
  await expect(form).toHaveCount(0);
  await expect(await cell(materials(page), row, 'MEMO')).toHaveText(MEMO);
  await expect(materials(page).locator(`.ag-row-selected[row-id="${row}"]`).first()).toBeVisible();

  await open(page, doc.docId, row);
  const reopened = await openForm(page, row);
  await expect(reopened.locator('[data-field="MEMO"] input')).toHaveValue(MEMO);
  const saved = (await api.record(doc.docId)).details.COST_MATERIAL.find(r => r.rowKey === row)!;
  expect(saved.values.MEMO).toBe(MEMO);
});
