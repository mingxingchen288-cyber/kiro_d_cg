/**
 * 列虚拟化（只读）：视口设宽（5000×1200，playwright-base.ts）后，成本核算主表和明细的列能不能一次全部渲染。
 * 渲染出的列数与页面视图的可见字段数一起记在用例的说明里（annotations）。
 */
import { detailGrid, expect, masterGrid, openPage, selectRow, test } from './support';

test.use({ viewport: { width: 5000, height: 1200 } });

test('列虚拟化：宽视口下成本核算主表、原辅料、包材渲染出的列数', async ({ page, api }) => {
  const view = await api.view();
  await openPage(page, 'COST_PINGGU');
  await selectRow(page, '2550');
  const regions = [
    { name: '主表', grid: masterGrid(page), region: view.master },
    ...view.details.map(d => ({ name: d.title, grid: detailGrid(page, d.entity), region: d }))
  ];
  await Promise.all(regions.map(({ grid }) => expect(grid.locator('.ag-row').first()).toBeVisible()));
  const counts = [];
  for (const { name, grid, region } of regions) {
    // eslint-disable-next-line no-await-in-loop
    const rendered = await grid
      .locator('.ag-header-row-column .ag-header-cell[col-id]')
      .evaluateAll(cells => [...new Set(cells.map(c => c.getAttribute('col-id')))].filter(id => id !== '__form'));
    const total = region.fields.filter(f => f.visible).length;
    // eslint-disable-next-line no-await-in-loop
    const width = await grid
      .locator('.ag-body-horizontal-scroll-viewport')
      .first()
      .evaluate(el => ({
        client: el.clientWidth,
        scroll: el.scrollWidth
      }));
    counts.push({ name, rendered: rendered.length, total, ...width });
  }
  test.info().annotations.push({ type: '列数', description: JSON.stringify(counts) });
  // eslint-disable-next-line no-console
  console.log(JSON.stringify(counts));
});
