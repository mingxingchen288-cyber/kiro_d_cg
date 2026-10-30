/**
 * T-AS-7 样例二：在浏览器中完成 C06 7.9、7.10 两个审批场景（真实联调，浏览器 → 前端 → 后端 → d_cg）。
 * 发起人 jishu01（部门 18 技术中心，角色"技术中心"），审批人 admin。测试数据自己建、用例结束时自动删（support.ts 的 data）：
 * - 成本单由 admin 经接口新建（备注带 PF_TEST）；ERP 物料（模拟 ERP 同步写入）和液体成本单平台写不了，由
 *   `backend/tests/e2e/sample_two.py` 直接写表、删除（见那里的说明）。
 *
 * 1. 7.9：admin 新建一张"评估中"的成本单（硬脂酸镁客户指定、玉米淀粉不是）；jishu01 在成本核算页取消硬脂酸镁的
 *    "客户指定"并保存，提示已提交审批；admin 不刷新就收到通知，在待办中打开详情（客户指定 是 → 否）并通过；
 *    jishu01 收到"已通过"，单据中这一行不再是客户指定。
 * 2. 7.10：ERP 物料（参考价格 10，执行价为空）、含它的两张成本单 D1、D2 和一张液体成本单。jishu01 打开物料清单及成本，
 *    这一行是 ERP 行（绿底，物料名称不能编辑），把单价改成 12 并保存，提示已提交审批；admin 在待办中打开详情，
 *    受影响单据"成本核算（原辅料）"有 D1、D2 两行，取消 D2 后 D2 恢复为 10.00，通过；D1 单价 12、金额 120，D2 不变，
 *    物料清单执行价 12，液体明细单价 12。
 */
import {
  type Api,
  canEdit,
  cell,
  detailGrid,
  edit,
  expect,
  masterGrid,
  noticed,
  openDoc,
  openPage,
  openTodo,
  passInDetail,
  realtimeEvents,
  save,
  showDetail,
  test,
  toast
} from './support';

/** 物料清单的单价（成本核算原辅料 Lookup costMaterialEffective 的 ZX_PRICE） */
async function listPrice(api: Api, keyword: string, goodsId: string) {
  const found = await api.ok('POST', '/api/lookups/costMaterialEffective/search', { keyword, startRow: 0, endRow: 50 });
  return found.rows.find((r: { values: Record<string, string> }) => r.values.GOODSID === goodsId).values
    .ZX_PRICE as string;
}

// ---------------------------------------------------------------- 1：C06 7.9

test('7.9 技术中心取消客户指定：提交审批、管理员在待办中通过、发起人收到已通过', async ({
  page: admin,
  as,
  data,
  api
}) => {
  const adminEvents = realtimeEvents(admin);
  await admin.goto('/home');
  const { docId, rows } = await data.newDoc(
    [
      { GOODSID: '115', PER_HL: '2.5', PRICE: await listPrice(api, '硬脂酸镁', '115'), CUSTOMER_SPECIFIED: true },
      { GOODSID: '310', PER_HL: '42.5', PRICE: await listPrice(api, '玉米淀粉', '310') }
    ],
    { USESTATUS: '评估中' }
  );
  const [specified] = rows;

  const tech = await as('jishu01');
  const techEvents = realtimeEvents(tech);
  await openDoc(tech, docId);
  await showDetail(tech, '原料/辅料');
  const grid = detailGrid(tech, 'COST_MATERIAL');
  const box = async () => (await cell(grid, specified, 'CUSTOMER_SPECIFIED')).locator('input[type="checkbox"]');
  await expect(await box()).toBeChecked();
  await (await box()).click();
  await expect(await box()).not.toBeChecked();
  const submitted = await save(tech);
  expect(submitted.outcome, JSON.stringify(submitted)).toBe('approvalSubmitted');
  expect(submitted.approvals[0].flows).toEqual(['TECH_CUSTOMER_MATERIAL']);
  const approvalId = submitted.approvals[0].approvalId;
  await toast(tech, /已提交审批/);
  await expect(await box()).toBeChecked();

  const link = `/approval/${approvalId}`;
  await expect.poll(() => noticed(adminEvents, link)).toBe(true);
  const detail = await openTodo(admin, docId, approvalId);
  await expect(detail).toContainText('技术中心客指物料变更审批');
  await expect(detail).toContainText('是 → 否');
  await passInDetail(admin, detail);

  await expect.poll(() => noticed(techEvents, link, true)).toBe(true);
  const after = await api.record(docId);
  expect(after.details.COST_MATERIAL.map(r => [r.rowKey, r.values.CUSTOMER_SPECIFIED])).toEqual([
    [specified, false],
    [rows[1], false]
  ]);
});

// ---------------------------------------------------------------- 2：C06 7.10

test('7.10 物料清单改价：ERP 行只能改单价，审批人取消一张成本单，通过后只更新勾选的成本单', async ({
  page: admin,
  as,
  data,
  api
}) => {
  const goodsid = data.goods('10');
  const material = { GOODSID: goodsid, PER_HL: '10', PRICE: '10' };
  const d1 = await data.newDoc([material]);
  const d2 = await data.newDoc([material]);
  const lq = data.liquid(goodsid, '10');
  await admin.goto('/home');

  const tech = await as('jishu01');
  await openPage(tech, 'GOODS_PRICE_MANAGE');
  const grid = masterGrid(tech);
  // 物料ID 列表头点两次（升序、降序），新增的物料主键最大，排在最前
  const target = grid.locator(`.ag-center-cols-container .ag-row[row-id="${goodsid}"]`);
  const header = grid.locator('.ag-header-cell[col-id="GOODSID"]');
  await header.locator('.ag-header-cell-label').click();
  await expect(header).toHaveAttribute('aria-sort', 'ascending');
  await header.locator('.ag-header-cell-label').click();
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(target).toBeVisible();
  await expect(target).toHaveCSS('background-color', 'rgb(230, 255, 237)'); // ERP 行绿底（旧 GRID_STYLE）
  const name = await cell(grid, goodsid, 'GOODSNAME');
  await expect(name).toHaveText('H5联调辅料');
  expect(await canEdit(tech, name)).toBe(false); // ERP 行的 ERP 列只读
  await expect(await cell(grid, goodsid, 'ZX_PRICE')).toHaveText('10');
  await edit(tech, await cell(grid, goodsid, 'ZX_PRICE'), '12');
  const submitted = await save(tech);
  expect(submitted.outcome, JSON.stringify(submitted)).toBe('approvalSubmitted');
  expect(submitted.approvals[0].flows).toEqual(['GOODS_TO_COST']);
  const approvalId = submitted.approvals[0].approvalId;
  await toast(tech, /已提交审批/);
  await expect(await cell(grid, goodsid, 'ZX_PRICE')).toHaveText('10'); // 审批结束前显示正式数据

  const detail = await openTodo(admin, goodsid, approvalId);
  await expect(detail).toContainText('物料清单改价审批');
  await expect(detail.locator('.n-tabs-tab[data-name="GOODS_TO_COST:costMaterial"]')).toHaveText(
    '成本核算（原辅料）（2 条）'
  );
  await expect(detail.locator('.n-tabs-tab[data-name="GOODS_TO_COST:lqMaterial"]')).toHaveText(
    '液体成本核算（原辅料）（1 条）'
  );
  const affected = detail
    .locator('.approval-presentation-grid')
    .filter({ has: admin.getByLabel(`勾选 ${d2.rows[0]}`) });
  await expect(affected).toContainText('10.00 → 12.00');
  await admin.getByLabel(`勾选 ${d2.rows[0]}`).uncheck();
  await expect(detail.getByText('正在按勾选重新计算')).toHaveCount(0);
  await expect(affected.locator('.ag-center-cols-container .ag-row', { hasText: d2.docId })).not.toContainText('→');
  await expect(affected.locator('.ag-center-cols-container .ag-row', { hasText: d1.docId })).toContainText(
    '10.00 → 12.00'
  );
  await passInDetail(admin, detail);

  const price = async (docId: string) => {
    const values = (await api.record(docId)).details.COST_MATERIAL[0].values;
    return [values.PRICE, values.COST_BATCH];
  };
  expect(await price(d1.docId)).toEqual(['12', '120']);
  expect(await price(d2.docId)).toEqual(['10', '100']);
  expect(data.showGoods(goodsid, lq.dtlid)).toEqual({ zxPrice: '12', lqPrice: '12', lqCostBatch: '50' });

  // WP-20：审批通过时写修改人（审批人 admin，同旧系统 DynamicDataService 写 UPDATE_BY），视图按 UPDATE_BY 判断这一行
  // 已被人工修改，重新打开后变成黄底（旧 GRID_STYLE 的 erp-updated）
  await tech.reload();
  await expect(header).toBeVisible();
  await header.locator('.ag-header-cell-label').click();
  await expect(header).toHaveAttribute('aria-sort', 'ascending');
  await header.locator('.ag-header-cell-label').click();
  await expect(header).toHaveAttribute('aria-sort', 'descending');
  await expect(target).toHaveCSS('background-color', 'rgb(255, 242, 168)');
  await expect(await cell(grid, goodsid, 'ZX_PRICE')).toHaveText('12');
});
