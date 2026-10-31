/**
 * 行表单里的对比与表格同一格相同（FP-03、FP-15、FP-24，2026-11-01）。依据用户 2026-11-01："表单和表格可以公用一个元数据，
 * 表单唯一的区别仅仅是可以调整每个表单列的位置和带线（大小）"。
 *
 * d_cg 上物料清单没有配对比（2026-11-01 只读查询 `.reports/form-compare-20261101/01-物料清单对比配置.out.txt`），同 B9
 * （batch8-config-caps.spec.ts）临时给物料清单实体的执行价配"与参考价格对比、都显示"，结束时恢复实体配置。物料清单按物料ID
 * 筛出 14142（复合硬片，参考价格 54、执行价 56，执行价与参考价格不同的物料之一）；表格执行价这一格的对比与列表接口给出的
 * 对比结果相同；点这一行的 ⊞，表单里执行价下面的对比文字、颜色与表格同一格相同。不改业务数据。
 */
import { cell, expect, filterColumn, masterGrid, openPage, test } from './support';

const GOODS = '14142';

test(
  '物料清单：执行价配了与参考价格对比时，点 ⊞ 后表单里执行价的对比与表格同一格相同',
  { lock: 'page.GOODS_PRICE_MANAGE', tag: '@shared-config' },
  async ({ page, api, adminApi }) => {
    const item = await adminApi.get('/api/config/items/entity/COST_GOODS_PRICE');
    const content = structuredClone(item.content);
    content.fields.find((f: { name: string }) => f.name === 'ZX_PRICE').compare = {
      mode: 'field',
      field: 'PRICE',
      format: 'both'
    };
    try {
      await adminApi.ok('PUT', '/api/config/items/entity/COST_GOODS_PRICE', { name: item.name, content });
      const view = await api.get('/api/pages/GOODS_PRICE_MANAGE/view');
      expect(view.master.fields.find((f: { name: string }) => f.name === 'ZX_PRICE').compare).toEqual({
        format: 'both'
      });

      await openPage(page, 'GOODS_PRICE_MANAGE');
      const { body } = await filterColumn(page, 'GOODSID', GOODS);
      const row = body.rows.find((r: { rowKey: string }) => r.rowKey === GOODS);
      const compare = row.compare.ZX_PRICE as { diff: string; percent: string };
      expect(Number(compare.diff), '执行价与参考价格不同').not.toBe(0);
      const arrow = compare.diff.startsWith('-') ? '↓' : '↑';
      const text = `${arrow}${compare.diff.replace(/^-/, '')} (${compare.percent.replace(/^-/, '')}%)`;

      const grid = masterGrid(page);
      const tableDiff = (await cell(grid, GOODS, 'ZX_PRICE')).locator('.cell-compare');
      await expect(tableDiff).toHaveText(text);
      const tableColor = await tableDiff.evaluate(el => getComputedStyle(el).color);
      // 上升红色、下降绿色（fields.ts 的 COMPARE_UP_COLOR、COMPARE_DOWN_COLOR）
      expect(tableColor).toBe(arrow === '↑' ? 'rgb(229, 57, 53)' : 'rgb(67, 160, 71)');

      await grid.locator(`.ag-row[row-id="${GOODS}"] [col-id="__form"] button`).first().click();
      const form = page.locator('.record-form');
      await expect(form).toBeVisible();
      const formDiff = form.locator('[data-field="ZX_PRICE"] .cell-compare');
      await expect(formDiff).toHaveText(text);
      expect(await formDiff.evaluate(el => getComputedStyle(el).color)).toBe(tableColor);
    } finally {
      await adminApi.ok('PUT', '/api/config/items/entity/COST_GOODS_PRICE', { name: item.name, content: item.content });
    }
    expect((await adminApi.get('/api/config/items/entity/COST_GOODS_PRICE')).content).toEqual(item.content);
  }
);
