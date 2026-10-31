/**
 * 液体成本核算（第 8 批 G2，T-CF-10、T-OP-6）：通用页面按页面编码 COST_PINGGU_LQ 打开，列、明细、按钮、规则都来自配置
 * （seed 的 entity/page/operation/rule *_LQ，按旧 cost-pinggu-lq 转换）。admin 操作；测试数据自己建、用例结束时删
 * （support.ts 的 data：液体成本单经平台删除）。
 *
 * 1. 打开液体成本核算：备注为"ERP未搭建BOM"的 2573 整行红底（旧 GRID_STYLE 609）。复制液体成本单 2571（对话框照默认全选），
 *    在新单据的原料/辅料中改第一行的单价：页面预览中这一行的每批成本 = 每批数量 × 新单价（每批数量 = mg/ml × 批量 ×
 *    （1 + 额外投料量/100）/ 1000000，旧页面规则 616），主表合计跟着变；保存后重新打开，显示与预览相同；接口读出的每批成本
 *    与精确值相同，主表原料、辅料、包材合计等于明细每批成本按分类求和（有原料时除以 1.13，旧页面规则 604）。
 * 2. 由BOM生成明细：经平台复制 2571（产品 8726），选中它点"由BOM生成明细"：明细换成按旧 P_COST_BOM_INSERT_LQ 查出的行
 *    （backend/tests/e2e/liquid.py 只读算出），物料、单价、原辅料每片含量相同，名称、分类带出；包材名称不在三个分支里的
 *    （铝箔、硬片）每批数量为 BOM 用量。
 */
import { formatNumber } from '../../src/modules/page/fields';
import { samePrice, wp15 } from './data';
import {
  LIQUID,
  backendScript,
  cell,
  cellText,
  detailGrid,
  edit,
  expect,
  masterGrid,
  mustSave,
  openDoc,
  runButton,
  save,
  selectRow,
  showDetail,
  test,
  toast,
  toolbar
} from './support';

const RED = 'rgb(255, 204, 204)';
const SOURCE = '2571';
/** 包材每批数量的三个分支（旧页面规则 620）按名称部分匹配 */
const PACKAGE_BRANCHES = /桶|说明书|小盒|标签|瓶|盖注射器|适配器|量杯|勺|分度器|大纸箱|托盘/;

// ---------------------------------------------------------------- 十进制文本（BigInt，不经过浮点）

type Dec = { digits: bigint; scale: number };
const parse = (text: string | null | undefined): Dec => {
  const value = String(text ?? '0');
  const [int, frac = ''] = value.split('.');
  return { digits: BigInt(int + frac), scale: frac.length };
};
const mul = (a: Dec, b: Dec): Dec => ({ digits: a.digits * b.digits, scale: a.scale + b.scale });
const add = (a: Dec, b: Dec): Dec => {
  const scale = Math.max(a.scale, b.scale);
  return { digits: a.digits * 10n ** BigInt(scale - a.scale) + b.digits * 10n ** BigInt(scale - b.scale), scale };
};
/** 除以 10 的 n 次方 */
const shift = (a: Dec, n: number): Dec => ({ digits: a.digits, scale: a.scale + n });
const text = (a: Dec) => {
  const negative = a.digits < 0n;
  const raw = (negative ? -a.digits : a.digits).toString().padStart(a.scale + 1, '0');
  const int = a.scale ? raw.slice(0, -a.scale) : raw;
  const frac = a.scale ? raw.slice(-a.scale).replace(/0+$/, '') : '';
  return `${negative ? '-' : ''}${int}${frac ? `.${frac}` : ''}`;
};

/** 原辅料每批数量（616）：mg/ml × 批量 × (100 + 额外投料量) / 100000000 */
const materialBatch = (perHl: unknown, apex: unknown, extra: unknown) =>
  shift(mul(mul(parse(perHl as string), parse(apex as string)), add(parse('100'), parse((extra as string) ?? '0'))), 8);

test.describe('液体成本核算', () => {
  test('复制液体单据、改原辅料单价：预览和保存后每批成本、主表合计按规则重算，重新打开一致', async ({
    page,
    data,
    api
  }) => {
    test.slow(); // 复制、预览、保存、重新打开
    const view = await api.view(LIQUID);
    expect(view.title).toBe('液体成本核算');
    expect(view.details.map(d => [d.entity, d.title])).toEqual([
      ['COST_MATERIAL_LQ', '原料/辅料'],
      ['COST_PACKAGE_LQ', '包材']
    ]);
    expect(view.master.buttons.map(b => b.label)).toEqual(['新增', '复制', '删除', '由BOM生成明细', '保存列配置']);

    // 旧 GRID_STYLE 609：备注"ERP未搭建BOM"整行红底
    await openDoc(page, '2573', LIQUID);
    await expect(masterGrid(page).locator('.ag-center-cols-container .ag-row[row-id="2573"]')).toHaveCSS(
      'background-color',
      RED
    );

    const source = await api.record(SOURCE, LIQUID);
    await openDoc(page, SOURCE, LIQUID);
    await toolbar(page).getByRole('button', { name: '复制', exact: true }).click();
    const dialog = page.locator('.copy-dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: '确定' }).click();
    await expect(page.locator('.copy-dialog')).toHaveCount(0);
    const grid = masterGrid(page);
    const newRow = grid.locator('.ag-pinned-left-cols-container .ag-row.row-new').first();
    const clientRowId = (await newRow.getAttribute('row-id'))!;
    await selectRow(page, clientRowId); // 液体主表的备注不可编辑（旧列 1693），新单据不带测试标记，结束时按主键删

    await showDetail(page, '原料/辅料');
    const materials = detailGrid(page, 'COST_MATERIAL_LQ');
    const firstRow = materials.locator('.ag-center-cols-container .ag-row').first();
    const lineId = (await firstRow.getAttribute('row-id'))!;
    const goodsId = await cellText(materials, lineId, 'GOODSID');
    const from = source.details.COST_MATERIAL_LQ.find(r => String(r.values.GOODSID) === goodsId)!;
    const price = String(from.values.PRICE) === '100' ? '101' : '100';
    const field = view.details[0].fields.find(f => f.name === 'COST_BATCH')!;
    const cost = mul(
      materialBatch(from.values.PER_HL, source.master.values.APEX_PL, from.values.EXADD_MATER),
      parse(price)
    );
    const masterBefore = await cellText(grid, clientRowId, 'TOTAL_COST');

    await edit(page, await cell(materials, lineId, 'PRICE'), price);
    // 预览：这一行的每批成本、主表合计按规则算出
    await expect(await cell(materials, lineId, 'COST_BATCH')).toHaveText(formatNumber(field, text(cost)));
    await expect(await cell(grid, clientRowId, 'TOTAL_COST')).not.toHaveText(masterBefore);
    const names = ['TOTAL_YL', 'TOTAL_FL', 'TOTAL_BC', 'TOTAL_COST', 'COST_PERBOX', 'JGF_BATCH', 'JGF_PERQP'];
    const previewed: Record<string, string> = {};
    for (const name of names) previewed[name] = await cellText(grid, clientRowId, name); // eslint-disable-line no-await-in-loop
    const previewCost = await cellText(materials, lineId, 'COST_BATCH');

    const saved = mustSave(await save(page));
    expect(saved.approvals).toEqual([]); // 液体页面没有审批流（cmx WF_FLOW_CONFIG 没有 cost-pinggu-lq 的）
    const docId = String(saved.idMap[clientRowId]);
    data.adoptLiquid(docId);
    await toast(page, '已保存');
    const dtlId = String(saved.idMap[lineId] ?? lineId);

    // 重新打开：显示与预览相同
    await page.reload();
    await openDoc(page, docId, LIQUID);
    for (const name of names)
      // eslint-disable-next-line no-await-in-loop
      await expect(await cell(masterGrid(page), docId, name), name).toHaveText(previewed[name]);
    await showDetail(page, '原料/辅料');
    await expect(await cell(detailGrid(page, 'COST_MATERIAL_LQ'), dtlId, 'COST_BATCH')).toHaveText(previewCost);

    // 接口读出：每批成本与精确值相同（WP-15 保留 8 位小数）；主表三项合计等于明细按分类求和（有原料时除以 1.13）
    const record = await api.record(docId, LIQUID);
    const line = record.details.COST_MATERIAL_LQ.find(r => r.rowKey === dtlId)!;
    expect(samePrice(line.values.PRICE, price), `单价 ${String(line.values.PRICE)}`).toBe(true);
    expect(samePrice(line.values.COST_BATCH, wp15(text(cost))), `每批成本 ${String(line.values.COST_BATCH)}`).toBe(
      true
    );
    const sum = (rows: typeof record.details.COST_MATERIAL_LQ, flags: string[]) =>
      rows
        .filter(r => flags.includes(String(r.values.DTL_USEFLAG)))
        .reduce((s, r) => s + Number(r.values.COST_BATCH ?? 0), 0);
    const raw = sum(record.details.COST_MATERIAL_LQ, ['原料']);
    const tax = raw > 0 ? 1.13 : 1;
    const expected = {
      TOTAL_YL: raw / tax,
      TOTAL_FL: sum(record.details.COST_MATERIAL_LQ, ['辅料']) / tax,
      TOTAL_BC: sum(record.details.COST_PACKAGE_LQ, ['印字包材', '非印字包材']) / tax
    };
    for (const [name, value] of Object.entries(expected))
      expect(Math.abs(Number(record.master.values[name]) - value), name).toBeLessThan(1e-6 * Math.max(1, value));
  });

  test('由BOM生成明细：按旧 P_COST_BOM_INSERT_LQ 替换明细，每批数量、每批成本按规则算出', async ({
    page,
    data,
    api
  }) => {
    const doc = await data.copyLiquid(SOURCE);
    await openDoc(page, doc.docId, LIQUID);
    const result = mustSave(await runButton(page, '由BOM生成明细'));
    expect(result.approvals).toEqual([]);
    await toast(page, '由BOM生成明细已完成');

    type Bom = { entity: string; goodsid: string; useqty: string | null; price: string | null; perHl: string | null };
    const bom = JSON.parse(backendScript('tests.e2e.liquid', ['bom', '--doc', doc.docId]).at(-1)!) as Bom[];
    const record = await api.record(doc.docId, LIQUID);
    const apex = record.master.values.APEX_PL;
    for (const entity of ['COST_MATERIAL_LQ', 'COST_PACKAGE_LQ']) {
      const rows = record.details[entity];
      const wanted = bom.filter(b => b.entity === entity);
      expect(rows.map(r => String(r.values.GOODSID)).sort(), entity).toEqual(wanted.map(b => b.goodsid).sort());
      for (const row of rows) {
        const b = wanted.find(w => w.goodsid === String(row.values.GOODSID))!;
        expect(row.values.PRICE ?? null, `${entity} ${b.goodsid} 单价`).toEqual(b.price);
        expect(row.values.GOODSNAME && row.values.DTL_USEFLAG, `${entity} ${b.goodsid} 名称、分类`).toBeTruthy();
        if (entity === 'COST_MATERIAL_LQ') {
          expect(
            samePrice(row.values.PER_HL, wp15(b.perHl!)),
            `${b.goodsid} 每片含量 ${String(row.values.PER_HL)}`
          ).toBe(true);
          // 每批数量 = mg/ml × 批量 / 1000000（额外投料量为空）
          const batch = wp15(text(shift(mul(parse(String(row.values.PER_HL)), parse(String(apex))), 6)));
          expect(samePrice(row.values.BATCH_QTY, batch), `${b.goodsid} 每批数量 ${String(row.values.BATCH_QTY)}`).toBe(
            true
          );
        } else if (!PACKAGE_BRANCHES.test(String(row.values.GOODSNAME))) {
          const shown = `${b.goodsid} ${String(row.values.GOODSNAME)} 每批数量 ${String(row.values.BATCH_QTY)}`;
          expect(samePrice(row.values.BATCH_QTY, b.useqty), `${shown} 应为 BOM 用量 ${String(b.useqty)}`).toBe(true);
        }
      }
    }
    // 页面上明细区显示新的行
    await showDetail(page, '原料/辅料');
    for (const row of record.details.COST_MATERIAL_LQ)
      // eslint-disable-next-line no-await-in-loop
      await expect(
        detailGrid(page, 'COST_MATERIAL_LQ').locator(`.ag-row[row-id="${row.rowKey}"]`).first()
      ).toBeVisible();
  });
});
