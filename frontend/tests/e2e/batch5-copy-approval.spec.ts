/**
 * 复制出的行进入审批后，最终通过按提交时按源行解出的值写（approval T-AP-7，AP-02、AP-10；write-pipeline WP-21）。
 *
 * 准备（经平台接口）：测试物料（参考价格 10、执行价为空）；复制成本单 2550 得到测试源单据（单价等于物料清单执行价的
 * 10 行明细），再给它加一行测试物料、单价 10（等于执行价，不进审批）。
 * 浏览器（admin）：打开测试源单据，点"复制"，对话框里主表字段和明细行都照默认全选，确定；在新单据的原料/辅料中把测试物料
 * 那一行的单价改成 12（与执行价 10 不同），保存 → 提交成本明细改价审批（COST_TO_GOODS），冻结新单据和测试物料。
 * 在待办中打开详情：复制出的行都是"新增"，测试物料那一行 10 → 12 触发审批；通过。
 * 核对（经平台接口）：新单据写入，主表和明细复制的字段与源单据相同（计算字段、主键除外；测试物料那一行单价 12），
 * 物料清单中测试物料的执行价为 12。改之前最终通过按 Patch 重放，前端带来的只在视图中的物料名称等字段返回 422，通过不了。
 *
 * 触发审批的那一行用测试物料：2550 自己单价与执行价不同的行，通过时会把真实物料清单的执行价、修改人改掉，经平台改不回。
 * 用例结束时 data 删掉两张成本单（经平台）和测试物料，审批、命令记录由 worker 结束时的 cleanup.py 删掉。
 */
import {
  type Locator,
  cell,
  detailGrid,
  edit,
  expect,
  masterGrid,
  mustSave,
  openDoc,
  openTodo,
  passInDetail,
  save,
  selectRow,
  showDetail,
  test,
  toast,
  toolbar
} from './support';

/** 表格中某一列文字等于 `text` 的行的 row-id */
async function rowIdWith(grid: Locator, column: string, text: string) {
  const target = grid.locator(`.ag-row [col-id="${column}"]`).filter({ hasText: new RegExp(`^\\s*${text}\\s*$`) });
  await expect(target.first()).toBeVisible();
  return (await target.first().locator('xpath=ancestor::*[contains(@class, "ag-row")][1]').getAttribute('row-id'))!;
}

test('复制出的行进入审批：复制成本单带明细、改测试物料那一行的单价提交审批，admin 通过后新单据与源单据相同', async ({
  page,
  data,
  api
}) => {
  test.slow(); // 复制、改价、审批、通过
  const goods = data.goods('10');
  const source = await data.copyDoc('2550');
  mustSave(
    await api.command([
      {
        entity: 'COST_PINGGU',
        master: { op: 'none', rowKey: source.docId },
        details: [
          {
            entity: 'COST_MATERIAL',
            op: 'add',
            clientRowId: `tmp-${crypto.randomUUID()}`,
            values: { GOODSID: goods, PER_HL: '10', PRICE: '10' }
          }
        ]
      }
    ])
  );
  const before = await api.record(source.docId);
  const view = await api.view();

  // 复制：主表字段、明细行都照默认全选
  await openDoc(page, source.docId);
  await toolbar(page).getByRole('button', { name: '复制', exact: true }).click();
  const dialog = page.locator('.copy-dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '确定' }).click();
  await expect(page.locator('.copy-dialog')).toHaveCount(0);
  const newRow = masterGrid(page).locator('.ag-pinned-left-cols-container .ag-row.row-new').first();
  const clientRowId = (await newRow.getAttribute('row-id'))!;
  await selectRow(page, clientRowId);
  await showDetail(page, '原料/辅料');
  const materials = detailGrid(page, 'COST_MATERIAL');
  const line = await rowIdWith(materials, 'GOODSID', goods);
  await expect(await cell(materials, line, 'PRICE')).toHaveText('10.00');
  await edit(page, await cell(materials, line, 'PRICE'), '12'); // 与执行价 10 不同

  const submitted = await save(page);
  expect(submitted.outcome).toBe('approvalSubmitted');
  const [approval] = submitted.approvals as Array<{
    approvalId: string;
    flows: string[];
    document: { recordKey: string };
  }>;
  expect(approval.flows).toEqual(['COST_TO_GOODS']);
  const docId = approval.document.recordKey;
  data.adopt(docId);
  await toast(page, /已提交审批/);

  // 待办中打开详情：复制出的行都是"新增"，测试物料那一行触发审批
  const detail = await openTodo(page, docId, approval.approvalId);
  await expect(detail).toContainText('原辅料（7）');
  await expect(detail).toContainText('新增');
  await expect(detail).toContainText('12.00');
  await passInDetail(page, detail);

  // 新单据：复制的字段与源单据相同（计算字段、主键除外）
  const after = await api.record(docId);
  const calculated = (entity: string) =>
    new Set(
      [view.master, ...view.details]
        .find(r => r.entity === entity)!
        .fields.filter(f => f.calculated)
        .map(f => f.name)
    );
  const plain = (values: Record<string, unknown>, entity: string, skip: string[]) =>
    Object.fromEntries(Object.entries(values).filter(([k]) => !calculated(entity).has(k) && !skip.includes(k)));
  expect(plain(after.master.values, 'COST_PINGGU', ['DOCID'])).toEqual(
    plain(before.master.values, 'COST_PINGGU', ['DOCID'])
  );
  for (const entity of ['COST_MATERIAL', 'COST_PACKAGE']) {
    const byGoods = (rows: Array<{ values: Record<string, unknown> }>) =>
      new Map(rows.map(r => [String(r.values.GOODSID), plain(r.values, entity, ['DTLID', 'DOCID'])]));
    const expected = byGoods(before.details[entity] ?? []);
    // 测试物料那一行：单价是改过的 12；参考采购价（BASE_PRICE，读取视图按物料清单的执行价带出）随通过后的执行价变成 12
    if (entity === 'COST_MATERIAL') expected.set(goods, { ...expected.get(goods), PRICE: '12', BASE_PRICE: '12' });
    expect(byGoods(after.details[entity] ?? []), entity).toEqual(expected);
  }
  expect(data.showGoods(goods).zxPrice).toBe('12');
});
