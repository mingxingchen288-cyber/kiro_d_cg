/**
 * 列虚拟化（只读）：测试模式（`vite --mode test`、`pnpm build:test`）下表格关掉了列虚拟化（用户 2026-10-30 同意，
 * src/modules/page/grid-adapter/columns.ts），默认窗口 1600×900 里成本核算主表和明细也一次渲染出全部可见字段的列：
 * 主表 43 列，原料/辅料、包材各 18 列（d_cg 的页面视图）。渲染出的列与页面视图的可见字段逐个对上。
 * 正式构建（`pnpm build`，`--mode prod`）仍只渲染视野内的列，这条用例在正式构建上不成立。
 */
import { type Locator, detailGrid, expect, masterGrid, openPage, selectRow, test } from './support';

/** 表头里渲染出的列（col-id，去掉原地表单的展开列） */
const renderedColumns = (grid: Locator) =>
  grid
    .locator('.ag-header-row-column .ag-header-cell[col-id]')
    .evaluateAll(cells => [...new Set(cells.map(c => c.getAttribute('col-id')!))].filter(id => id !== '__form'));

test('列虚拟化：测试模式下成本核算主表 43 列、原料/辅料和包材各 18 列全部渲染', async ({ page, api }) => {
  const view = await api.view();
  await openPage(page, 'COST_PINGGU');
  await selectRow(page, '2550');
  const regions = [
    { name: '主表', grid: masterGrid(page), region: view.master },
    ...view.details.map(d => ({ name: d.title, grid: detailGrid(page, d.entity), region: d }))
  ];
  await Promise.all(
    regions.map(({ grid }) => expect(grid.locator('.ag-center-cols-container .ag-row').first()).toBeVisible())
  );
  const fields = regions.map(({ region }) => region.fields.filter(f => f.visible).map(f => f.name));
  const counts = async () =>
    Promise.all(
      regions.map(async ({ name, grid }, i) => ({
        name,
        rendered: (await renderedColumns(grid)).length,
        total: fields[i].length
      }))
    );
  await expect.poll(counts).toEqual([
    { name: '主表', rendered: 43, total: 43 },
    { name: '原料/辅料', rendered: 18, total: 18 },
    { name: '包材', rendered: 18, total: 18 }
  ]);
  test.info().annotations.push({ type: '列数', description: JSON.stringify(await counts()) });
  for (const [i, { name, grid }] of regions.entries())
    // eslint-disable-next-line no-await-in-loop -- 逐个区域比较
    expect((await renderedColumns(grid)).sort(), name).toEqual([...fields[i]].sort());
});
