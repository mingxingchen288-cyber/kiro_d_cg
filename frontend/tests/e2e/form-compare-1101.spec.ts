/**
 * 行表单里的对比与表格同一格相同（FP-03、FP-15、FP-24，2026-11-01）。依据用户 2026-11-01："表单和表格可以公用一个元数据，
 * 表单唯一的区别仅仅是可以调整每个表单列的位置和带线（大小）"。
 *
 * admin 打开物料清单（/page/GOODS_PRICE_MANAGE）。配了对比的字段从页面视图取：d_cg 上执行价 ZX_PRICE 配了与参考价格的对比，
 * 种子配置（backend/seed/config 的 page.GOODS_PRICE_MANAGE.json、entity.COST_GOODS_PRICE.json）里没有，以 d_cg 当前配置为准。
 * 先经列表接口按块找出第一行这个字段对比差值不为 0 的物料（执行价与参考价格不同），主表按物料ID 筛出它；表格这一格的对比是
 * 按接口的对比结果和显示方式算出的文字；点这一行的 ⊞，表单里这个字段下面的对比文字、颜色与表格同一格相同。
 * 只读：不改数据、不改配置。
 */
import type { CompareResult, DataRow, ListResponse } from '../../src/contracts/http';
import type { ViewField } from '../../src/contracts/page-view';
import { type Api, cell, expect, filterColumn, masterGrid, openPage, test } from './support';

const PAGE = 'GOODS_PRICE_MANAGE';
/** 列表接口每次取的行数 */
const BLOCK = 1000;

type Format = 'value' | 'percent' | 'both';

/** 这个字段的对比能按显示方式显示出来：差值不为 0；只显示百分比时要有百分比 */
function shown(compare: CompareResult | undefined, format: Format) {
  return Boolean(compare?.diff && Number(compare.diff) !== 0 && (format !== 'percent' || compare.percent !== null));
}

/** 按显示方式应显示的文字（同旧系统 renderCompareValue）：上升 ↑、下降 ↓，value 只有差值、percent 只有百分比、both 都有 */
function expectedText(compare: CompareResult, format: Format) {
  const diff = compare.diff!;
  const arrow = diff.startsWith('-') ? '↓' : '↑';
  const value = diff.replace(/^-/, '');
  const percent = compare.percent === null ? null : `${compare.percent.replace(/^-/, '')}%`;
  const text = { value, percent: percent ?? '', both: percent ? `${value} (${percent})` : value }[format];
  return { text: `${arrow}${text}`, up: arrow === '↑' };
}

/** 从第 start 行起按块找第一行这个字段的对比能显示出来的物料；都没有时为 undefined */
async function firstCompared(api: Api, field: ViewField, start = 0): Promise<DataRow | undefined> {
  const format = field.compare?.format ?? 'both';
  const { rows, total } = await api.ok<ListResponse>('POST', `/api/pages/${PAGE}/rows`, {
    startRow: start,
    endRow: start + BLOCK
  });
  const row = rows.find(r => shown(r.compare?.[field.name], format));
  if (row || start + BLOCK >= total) return row;
  return firstCompared(api, field, start + BLOCK);
}

test('物料清单：执行价与参考价格不同的物料，点 ⊞ 后表单里这个字段的对比与表格同一格相同（只读）', async ({
  page,
  api
}) => {
  const view = await api.view(PAGE);
  const field = view.master.fields.find(f => f.visible && f.compare);
  expect(field, '物料清单有配了对比的可见字段（d_cg 上为执行价 ZX_PRICE）').toBeTruthy();
  const layout = view.master.formLayout;
  expect(!layout.length || layout.some(c => c.field === field!.name), '表单里有这个字段').toBe(true);
  const format = field!.compare?.format ?? 'both';
  const row = await firstCompared(api, field!);
  expect(row, `物料清单有${field!.label}对比差值不为 0 的物料`).toBeTruthy();
  const expected = expectedText(row!.compare![field!.name], format);

  await openPage(page, PAGE);
  await filterColumn(page, 'GOODSID', String(row!.values.GOODSID ?? row!.rowKey));
  const grid = masterGrid(page);
  const tableDiff = (await cell(grid, row!.rowKey, field!.name)).locator('.cell-compare');
  await expect(tableDiff).toHaveText(expected.text);
  const tableColor = await tableDiff.evaluate(el => getComputedStyle(el).color);
  // 上升红色、下降绿色（fields.ts 的 COMPARE_UP_COLOR、COMPARE_DOWN_COLOR）
  expect(tableColor).toBe(expected.up ? 'rgb(229, 57, 53)' : 'rgb(67, 160, 71)');

  await grid.locator(`.ag-row[row-id="${row!.rowKey}"] [col-id="__form"] button`).first().click();
  const form = page.locator('.record-form');
  await expect(form).toBeVisible();
  const formDiff = form.locator(`[data-field="${field!.name}"] .cell-compare`);
  await expect(formDiff).toHaveText(expected.text);
  expect(await formDiff.evaluate(el => getComputedStyle(el).color)).toBe(tableColor);
});
