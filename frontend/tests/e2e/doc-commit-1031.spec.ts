/**
 * 按单据提交（C02 v10 第 1 节；用户 2026-10-31："我也是要求一单一单的提交啊……100个单据 失败了1个，就全部失败"是不可以的）。
 * 成本核算页 /page/COST_PINGGU，admin。
 *
 * 数据隔离：经平台复制 2550 出两张测试成本单 A、B（备注带 PF_TEST 标记，主表按备注筛出这两张），用例结束时删除。
 *
 * admin 在 A 的原料/辅料把预胶化淀粉的每片含量改成 0，在 B 把聚维酮K30 的备注改为"按单据提交"，点一次保存：
 * 一个请求，后端每张单据一个事务。A 被规则"每片含量必填且必须大于0"拒绝，B 照常保存。页面提示"保存成功 1 张，失败 1 张"
 * 和 A 的原因；B 的修改已写入数据库，A 没有变；A 的修改留在页面上（1 行未保存），预胶化淀粉的每片含量格子标出错误。
 */
import { cell, detailGrid, edit, expect, filterColumn, masterGrid, openPage, save, selectRow, showDetail, test, toast } from './support';

const SOURCE = '2550';
const K30 = '206323';
const PREGEL = '206324';

test('一次保存两张成本单，一张被规则拒绝：另一张照常保存，被拒的修改留在页面上并标出', async ({ page, data, api }) => {
  const a = await data.copyDoc(SOURCE);
  const b = await data.copyDoc(SOURCE);
  const before = await api.record(a.docId);
  await openPage(page, 'COST_PINGGU');
  await filterColumn(page, 'MEMO', data.marker);
  await expect(masterGrid(page).locator('.ag-pinned-left-cols-container .ag-row')).toHaveCount(2);
  const materials = detailGrid(page, 'COST_MATERIAL');

  await selectRow(page, a.docId);
  await showDetail(page, '原料/辅料');
  await edit(page, await cell(materials, a.row(PREGEL), 'PER_HL'), '0');
  await selectRow(page, b.docId);
  await edit(page, await cell(materials, b.row(K30), 'MEMO'), '按单据提交');
  await expect(page.getByText('2 行未保存')).toBeVisible();

  const result = await save(page);
  expect(result.outcome).toBe('saved');
  expect(result.rows.some(r => r.rowKey === b.row(K30))).toBe(true);
  expect(result.failed?.map(f => [f.rowKey, f.error.code])).toEqual([[a.docId, 'RULE_REJECTED']]);
  await toast(page, '保存成功 1 张，失败 1 张');
  await toast(page, new RegExp(`单据 ${a.docId} .*：每片含量必填且必须大于0（原料/辅料 `));
  await expect(page.getByText('1 行未保存')).toBeVisible();

  const savedB = await api.record(b.docId);
  expect(savedB.details.COST_MATERIAL.find(r => r.rowKey === b.row(K30))!.values.MEMO).toBe('按单据提交');
  expect(await api.record(a.docId)).toEqual(before);

  await selectRow(page, a.docId);
  const perHl = await cell(materials, a.row(PREGEL), 'PER_HL');
  await expect(perHl).toHaveText('0');
  await expect(perHl).toHaveClass(/cell-error/);

  // 刷新放弃 A 的修改（浏览器问要不要离开，确认离开）
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(masterGrid(page).locator('.ag-row').first()).toBeVisible();
  await expect(page.getByText(/行未保存/)).toHaveCount(0);
});
