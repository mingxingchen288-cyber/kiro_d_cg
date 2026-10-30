/**
 * 第 7 批页面显示（C06 v22、C05 v6，用户 2026-10-30 同意按旧系统补）：
 * 1. 千分位：成本单 2555 的批量显示 3,500,000（只读看 d_cg 已有的单据），编辑框里是 3500000；主表汇总行同样带千分位。
 *    旧系统：列配置 `{"useGrouping":true}`，useMetaColumns.ts 的 applyThousandsGrouping。
 * 2. Lookup 对话框：新增成本单点"产品ID"打开产品选择，表头是配置的中文标题（产品ID、产品名称、注册证号……），
 *    产品ID 列宽 80（旧 Lookup 配置 costGoods 的 displayColumns；LookupDialog.vue 第 107–116 行）。不保存。
 * 3. 分类（PINGGU_CLASS）：旧系统是"下拉（可填写）"（TagSelectCellEditor.vue，单值，不是多选）。在测试成本单上从下拉选"委托研发"
 *    保存、重新打开一致；再填写字典以外的值保存、重新打开一致。
 *
 * 前提：主代理把 backend/seed/config 的变化（三个实体的 grouping、四个 Lookup 的 columns、字典 pingguClass、页面 COST_PINGGU
 * 的 PINGGU_CLASS）经配置接口写进 d_cg 之后才能通过。
 */
import {
  type Page,
  cell,
  expect,
  masterGrid,
  nextFrame,
  openDoc,
  openPage,
  save,
  summary,
  test,
  toast,
  toolbar
} from './support';

const BATCH_2555 = '2555';

test('千分位：成本单 2555 的批量显示 3,500,000，主表汇总行的每批物料成本带千分位（只读）', async ({ page, api }) => {
  const record = await api.record(BATCH_2555);
  expect(record.master.values.APEX_PL).toBe('3500000');
  const view = await api.view();
  const batch = view.master.fields.find(f => f.name === 'APEX_PL')!;
  expect(batch.grouping).toBe(true);

  await openDoc(page, BATCH_2555);
  await expect(await cell(masterGrid(page), BATCH_2555, 'APEX_PL')).toHaveText('3,500,000');
  const totals = await summary(masterGrid(page));
  expect(totals.TOTAL_COST).toMatch(/^-?\d{1,3}(,\d{3})+\.\d{2}$/);
});

test('千分位：编辑框里是不带千分位的原值，取消编辑后仍显示 3,500,000', async ({ page, data }) => {
  const doc = await data.copyDoc(BATCH_2555, { details: 'none' });
  await openDoc(page, doc.docId);
  const target = await cell(masterGrid(page), doc.docId, 'APEX_PL');
  await expect(target).toHaveText('3,500,000');
  await target.dblclick();
  const input = page.locator('.ag-cell-inline-editing input').first();
  await expect(input).toHaveValue('3500000');
  await page.keyboard.press('Escape');
  await expect(page.locator('.ag-cell-inline-editing')).toHaveCount(0);
  await expect(target).toHaveText('3,500,000');
});

test('Lookup 对话框：新增成本单点产品ID，产品选择的表头是中文标题，产品ID 列宽 80（不保存）', async ({ page, api }) => {
  const view = await api.view();
  const columns = view.master.fields.find(f => f.name === 'GOODSID')!.lookup!.columns!;
  await openPage(page, 'COST_PINGGU');
  const grid = masterGrid(page);
  await toolbar(page).getByRole('button', { name: '新增', exact: true }).click();
  const newRow = grid.locator('.ag-pinned-left-cols-container .ag-row.row-new').first();
  await expect(newRow).toBeVisible();
  const clientRowId = (await newRow.getAttribute('row-id'))!;

  await (await cell(grid, clientRowId, 'GOODSID')).dblclick();
  const dialog = page.locator('.lookup-dialog');
  await expect(dialog.locator('.ag-center-cols-container .ag-row').first()).toBeVisible();
  const headers = await dialog
    .locator('.ag-header-row-column .ag-header-cell')
    .evaluateAll(cells =>
      cells.map(c => [
        c.getAttribute('col-id'),
        (c.textContent ?? '').trim(),
        Math.round(c.getBoundingClientRect().width)
      ])
    );
  expect(headers.map(h => h[1]).slice(0, 4)).toEqual(['产品ID', '产品名称', '注册证号', '批量']);
  expect(headers.map(h => h[1])).toEqual(columns.map(c => c.label));
  expect(headers.find(h => h[0] === 'GOODSID')![2]).toBe(80);
  expect(headers.find(h => h[0] === 'GOODSNAME')![2]).toBe(200);
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

/** 双击"分类"格子，打开可填写的字典下拉 */
async function openClass(page: Page, docId: string) {
  await (await cell(masterGrid(page), docId, 'PINGGU_CLASS')).dblclick();
  const editor = page.locator('.ag-popup-editor .dict-select-cell-editor');
  await expect(editor).toBeVisible();
  await editor.locator('.n-base-selection').click();
  return editor;
}

async function saveClass(page: Page) {
  await expect(page.getByText('1 行未保存')).toBeVisible();
  expect((await save(page)).outcome).toBe('saved');
  await toast(page, '已保存');
  await expect(page.getByText('1 行未保存')).toBeHidden();
}

test('分类：测试成本单从下拉选"委托研发"保存，重新打开一致；再填写"PF_TEST 外部合作"保存，重新打开一致', async ({
  page,
  data,
  api
}) => {
  const view = await api.view();
  const field = view.master.fields.find(f => f.name === 'PINGGU_CLASS')!;
  expect([field.dictType, field.dictFreeText]).toEqual(['pingguClass', true]);
  const doc = await data.copyDoc('2550', { details: 'none', master: { PINGGU_CLASS: null } });
  await openDoc(page, doc.docId);

  // 下拉里是字典的四项，选"委托研发"后结束编辑
  await openClass(page, doc.docId);
  const options = page.locator('.n-base-select-menu .n-base-select-option');
  await expect(options).toHaveText(['委托研发', '委托转移', '自主立项', '平台业务']);
  await options.filter({ hasText: '委托研发' }).click();
  await expect(page.locator('.ag-popup-editor')).toHaveCount(0);
  await expect(await cell(masterGrid(page), doc.docId, 'PINGGU_CLASS')).toHaveText('委托研发');
  await saveClass(page);
  expect((await api.record(doc.docId)).master.values.PINGGU_CLASS).toBe('委托研发');
  await openDoc(page, doc.docId);
  await expect(await cell(masterGrid(page), doc.docId, 'PINGGU_CLASS')).toHaveText('委托研发');

  // 填写字典以外的值，回车确定
  const typed = 'PF_TEST 外部合作';
  const editor = await openClass(page, doc.docId);
  await editor.locator('input').first().fill(typed);
  await nextFrame(page);
  await page.keyboard.press('Enter');
  await expect(page.locator('.ag-popup-editor')).toHaveCount(0);
  await saveClass(page);
  expect((await api.record(doc.docId)).master.values.PINGGU_CLASS).toBe(typed);
  await openDoc(page, doc.docId);
  await expect(await cell(masterGrid(page), doc.docId, 'PINGGU_CLASS')).toHaveText(typed);
});
