/**
 * 第 8 批 G5 配置能力（盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B8、B9、B14、B15）的浏览器用例。
 *
 * 1. 新建页面向导搜表、取列注释（B14、B15，config CF-20、frontend-config FC-14）：配置 →"+ 新增页面"，第 2 步在"目标表"
 *    输入 T_COST_GOODS，下拉列出物料表（表）和物料清单视图（视图），先表后视图，与 `schema/objects` 的结果相同；再输入
 *    T_COST_PINGGU_LQ 选中液体成本核算主表，"导入列"后标题列中每盒成本（COST_PERBOX）、每中盒小盒数（M_PERPACK）是列注释，
 *    没有注释的 DOCID 是列名（d_cg 只读查询 `.reports/batch8-20261031/g5-config-caps/02-*`、`03-*`）。到导入列为止，不点生成，
 *    整个过程不发任何写配置的请求。只读，不改共用配置。
 * 2. 新增行立即显示默认值（B8，FP-23，E28 的写法）：临时给成本核算主表实体配商务人员默认当前用户名、剂型下拉"片剂、胶囊剂"、
 *    收率固定 98；admin 在成本核算点"新增"，新行上马上显示 admin 的姓名、片剂、98，剂型双击出下拉；不保存，结束时恢复实体配置。
 * 3. 对比的显示方式（B9，FP-24，E29 的写法）：临时给物料清单实体的执行价配"与参考价格对比"，显示方式先"只显示差值"、再
 *    "只显示百分比"；物料清单按物料ID 筛出 14142（复合硬片，参考价格 54、执行价 56，2026-10-31 只读查询 04：d_cg 9837 个物料中
 *    执行价与参考价格不同的 5 个之一），执行价旁只显示差值、只显示百分比，与列表接口给出的对比结果相同。结束时恢复实体配置。
 *
 * 2、3 用了 C05 v9 的页面视图字段（`default`、`compare`），main 的后端（8080）读不了，待主代理合并后运行。
 */
import { formatNumber } from '../../src/modules/page/fields';
import { type Locator, type Page, cell, expect, filterColumn, masterGrid, openPage, test, toolbar } from './support';

type SchemaObjects = { objects: Array<{ name: string; type: 'table' | 'view' }> };
type WizardColumns = { columns: Array<{ name: string; label: string }> };

/** 向导里的下拉项（NAutoComplete 的菜单挂在 body 下） */
const options = (page: Page) => page.locator('.n-auto-complete-menu .n-base-select-option').filter({ visible: true });

/** 在"目标表"输入关键字，等搜表的响应 */
async function searchTable(page: Page, dialog: Locator, keyword: string) {
  const searched = page.waitForResponse(
    r => r.url().endsWith('/api/config/schema/objects') && r.request().postDataJSON()?.keyword === keyword
  );
  await dialog.getByPlaceholder('搜索表...').fill(keyword);
  return (await (await searched).json()) as SchemaObjects;
}

test('B14、B15 新建页面向导：输入 T_COST_GOODS 列出表和视图；选液体成本核算主表导入列，标题是列注释（不生成）', async ({
  page
}) => {
  const writes: string[] = [];
  page.on('request', r => {
    const path = new URL(r.url()).pathname;
    if ((path.startsWith('/api/config/items') && r.method() !== 'GET') || path.endsWith('/api/config/wizard/generate'))
      writes.push(`${r.method()} ${path}`);
  });
  await page.goto('/config');
  await page.getByRole('button', { name: '+ 新增页面' }).click();
  const dialog = page.locator('.n-card').filter({ hasText: '页面创建向导' });
  await dialog.getByPlaceholder('请输入页面名称').fill('PF_TEST 向导搜表');
  await dialog.getByPlaceholder(/只允许大写字母/).fill('PF_TEST_WIZARD');
  await dialog.getByRole('button', { name: '下一步' }).click();

  const goods = await searchTable(page, dialog, 'T_COST_GOODS');
  const names = goods.objects.map(o => o.name);
  expect(names).toEqual(expect.arrayContaining(['T_COST_GOODS', 'T_COST_GOODS_PRICE_V']));
  expect(names.every(n => n.includes('T_COST_GOODS'))).toBe(true);
  const kinds = goods.objects.map(o => o.type);
  expect(kinds).toEqual([...kinds].sort());
  await expect(options(page)).toHaveText(goods.objects.map(o => `${o.name}（${o.type === 'table' ? '表' : '视图'}）`));
  await expect(options(page).filter({ hasText: 'T_COST_GOODS（表）' })).toHaveCount(1);
  await expect(options(page).filter({ hasText: 'T_COST_GOODS_PRICE_V（视图）' })).toHaveCount(1);

  await searchTable(page, dialog, 'T_COST_PINGGU_LQ');
  await options(page).filter({ hasText: /^T_COST_PINGGU_LQ（表）$/ }).click();
  await expect(dialog.getByPlaceholder('搜索表...')).toHaveValue('T_COST_PINGGU_LQ');

  const imported = page.waitForResponse(r => r.url().endsWith('/api/config/wizard/columns'));
  await dialog.getByRole('button', { name: '导入列' }).click();
  const body = (await (await imported).json()) as WizardColumns;
  const labels = Object.fromEntries(body.columns.map(c => [c.name, c.label]));
  expect([labels.COST_PERBOX, labels.M_PERPACK, labels.DOCID]).toEqual(['每盒成本', '每中盒小盒数', 'DOCID']);
  // 表格里的标题列：列多时行是按需渲染的，先把这一行滚进来
  const grid = dialog.locator('.ag-root-wrapper');
  for (const [name, label] of [
    ['DOCID', 'DOCID'],
    ['COST_PERBOX', '每盒成本'],
    ['M_PERPACK', '每中盒小盒数']
  ]) {
    const index = body.columns.findIndex(c => c.name === name);
    // 逐行滚动核对，按顺序进行
    // eslint-disable-next-line no-await-in-loop
    await grid
      .locator('.ag-body-viewport')
      .first()
      .evaluate((el, ratio) => {
        el.scrollTop = el.scrollHeight * ratio;
      }, index / body.columns.length);
    // eslint-disable-next-line no-await-in-loop
    await expect(grid.locator(`.ag-row[row-id="${name}"] [col-id="label"]`).first()).toHaveText(label);
  }
  await dialog.locator('.n-card-header__close').click();
  await expect(dialog).toHaveCount(0);
  expect(writes).toEqual([]);
});

test(
  'B8 新增行立即显示默认值：商务人员为当前用户、剂型下拉默认第一个、收率固定 98（待主代理合并后运行）',
  { lock: 'page.COST_PINGGU', tag: '@shared-config' },
  async ({ page, api, adminApi }) => {
    const me = await api.get<{ user: { displayName: string } }>('/api/me');
    const item = await adminApi.get('/api/config/items/entity/COST_PINGGU');
    const changed = structuredClone(item.content);
    const defaults: Record<string, unknown> = {
      BUSINESS_USER: { type: 'builtin', value: 'currentUserName' },
      DOSAGE: { type: 'options', value: ['片剂', '胶囊剂'] },
      YIELD: { type: 'static', value: '98' }
    };
    for (const field of changed.fields) if (defaults[field.name]) field.default = defaults[field.name];
    try {
      await adminApi.ok('PUT', '/api/config/items/entity/COST_PINGGU', { name: item.name, content: changed });
      const view = await api.get('/api/pages/COST_PINGGU/view');
      const yieldField = view.master.fields.find((f: { name: string }) => f.name === 'YIELD');
      expect(yieldField.default).toEqual(defaults.YIELD);

      await openPage(page, 'COST_PINGGU');
      const grid = masterGrid(page);
      await toolbar(page).getByRole('button', { name: '新增', exact: true }).click();
      const newRow = grid.locator('.ag-pinned-left-cols-container .ag-row.row-new').first();
      await expect(newRow).toBeVisible();
      const id = (await newRow.getAttribute('row-id'))!;
      await expect(await cell(grid, id, 'BUSINESS_USER')).toHaveText(me.user.displayName);
      await expect(await cell(grid, id, 'DOSAGE')).toHaveText('片剂');
      await expect(await cell(grid, id, 'YIELD')).toHaveText(formatNumber(yieldField, '98'));
      // 剂型用下拉选这两个值（同旧系统 multi 默认值的 agSelectCellEditor）
      await (await cell(grid, id, 'DOSAGE')).dblclick();
      await expect(grid.locator('.ag-cell-inline-editing')).toBeVisible();
      const items = page.locator('.ag-select-list .ag-list-item');
      if (!(await items.count())) await grid.locator('.ag-cell-inline-editing .ag-picker-field-wrapper').first().click();
      await expect(items).toHaveText([/^\s*片剂\s*$/, /^\s*胶囊剂\s*$/]);
      await page.keyboard.press('Escape');
    } finally {
      await adminApi.ok('PUT', '/api/config/items/entity/COST_PINGGU', { name: item.name, content: item.content });
    }
    expect((await adminApi.get('/api/config/items/entity/COST_PINGGU')).content).toEqual(item.content);
  }
);

test(
  'B9 对比显示方式：物料清单执行价与参考价格对比，"只显示差值""只显示百分比"按配置显示（待主代理合并后运行）',
  { lock: 'page.GOODS_PRICE_MANAGE', tag: '@shared-config' },
  async ({ page, api, adminApi }) => {
    const item = await adminApi.get('/api/config/items/entity/COST_GOODS_PRICE');
    const withFormat = (format: 'value' | 'percent') => {
      const content = structuredClone(item.content);
      const field = content.fields.find((f: { name: string }) => f.name === 'ZX_PRICE');
      field.compare = { mode: 'field', field: 'PRICE', format };
      return content;
    };
    try {
      for (const format of ['value', 'percent'] as const) {
        // 每种显示方式依次保存、打开页面核对，按顺序进行
        // eslint-disable-next-line no-await-in-loop
        await adminApi.ok('PUT', '/api/config/items/entity/COST_GOODS_PRICE', { name: item.name, content: withFormat(format) });
        // eslint-disable-next-line no-await-in-loop
        const view = await api.get('/api/pages/GOODS_PRICE_MANAGE/view');
        expect(view.master.fields.find((f: { name: string }) => f.name === 'ZX_PRICE').compare).toEqual({ format });
        // eslint-disable-next-line no-await-in-loop
        await openPage(page, 'GOODS_PRICE_MANAGE');
        // eslint-disable-next-line no-await-in-loop
        const { body } = await filterColumn(page, 'GOODSID', '14142');
        const row = body.rows.find((r: { rowKey: string }) => r.rowKey === '14142');
        const compare = row.compare.ZX_PRICE as { diff: string; percent: string };
        expect(Number(compare.diff), '执行价与参考价格不同').not.toBe(0);
        const arrow = compare.diff.startsWith('-') ? '↓' : '↑';
        const shown = format === 'value' ? compare.diff.replace(/^-/, '') : `${compare.percent.replace(/^-/, '')}%`;
        // eslint-disable-next-line no-await-in-loop
        const target = await cell(masterGrid(page), '14142', 'ZX_PRICE');
        // eslint-disable-next-line no-await-in-loop
        await expect(target).toContainText(`${arrow}${shown}`);
        // eslint-disable-next-line no-await-in-loop
        if (format === 'value') await expect(target).not.toContainText('%');
        // eslint-disable-next-line no-await-in-loop
        else await expect(target).not.toContainText(`${compare.diff.replace(/^-/, '')} (`);
      }
    } finally {
      await adminApi.ok('PUT', '/api/config/items/entity/COST_GOODS_PRICE', { name: item.name, content: item.content });
    }
    expect((await adminApi.get('/api/config/items/entity/COST_GOODS_PRICE')).content).toEqual(item.content);
  }
);
