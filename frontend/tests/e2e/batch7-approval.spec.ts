/**
 * 第 7 批 AP 组：旧系统在用、新平台补上的审批功能（盘点 `.reports/inventory-20261030/甲-任务卡核对.md` 第四节 B1～B5、
 * 第五节 U1；C09 v14、C11 v3）。业务流程同 basic-1029 场景 4b：chengben01 改测试物料的单价提交审批，admin 在待办中通过。
 * 测试物料、测试成本单由 `data` 建，用例结束删除；不用 d_cg 的真实单据走审批（通过时会改物料的执行价）。
 *
 * 核对：
 * 1. 进度弹窗到详情（B3）：chengben01 双击被冻结的单价，弹出审批进度，点"查看审批详情"打开审批详情。
 * 2. 铃铛角标（U1）：admin 的角标是待我审批数（`box=todo` 的条数），通过后少一个。
 * 3. 审批记录（B4）：审批详情底部"审批记录（2）"，展开后是提交、通过两行。
 * 4. 全部审批（B1）：待办"全部审批"页签里有这个已通过的审批。
 * 5. 原单据（B2）：从"全部审批"点"原单据"，成本核算只显示并选中这张单据，明细跟着显示。
 * 6. 查看审批进度（B3）：选中单据点工具栏"查看审批进度"，弹窗是这张单据的审批，能进审批详情。
 */
import {
  type Page,
  cell,
  detailGrid,
  edit,
  expect,
  masterGrid,
  noticed,
  openDoc,
  openMenu,
  openTodo,
  passInDetail,
  realtimeEvents,
  save,
  showDetail,
  test,
  toast,
  toolbar
} from './support';

/**
 * 顶栏铃铛的角标（数字为 0 时不显示）。NBadge 的数字用滚动动画画出（每位数字上下排着 0～9，textContent 不是显示的数），
 * 显示的数在 `title` 属性中。
 */
const badge = (page: Page) => page.locator('header button:has(.n-badge)').first().locator('.n-badge-sup');

test('批次 7 审批：进度到详情、铃铛是待审批数、审批记录、全部审批、原单据定位、查看审批进度', async ({
  page: admin,
  as,
  data,
  adminApi
}) => {
  const goods = data.goods('75');
  const { docId, rows } = await data.newDoc([{ GOODSID: goods, PER_HL: '10', PRICE: '75' }]);
  const [line] = rows;
  const adminEvents = realtimeEvents(admin);
  await admin.goto('/home');

  // chengben01 改单价提交审批
  const user = await as('chengben01');
  await openDoc(user, docId);
  await showDetail(user, '原料/辅料');
  const grid = detailGrid(user, 'COST_MATERIAL');
  await edit(user, await cell(grid, line, 'PRICE'), '90');
  const submitted = await save(user);
  expect(submitted.outcome).toBe('approvalSubmitted');
  const approvalId = submitted.approvals[0].approvalId;
  await toast(user, new RegExp(`单据 ${docId} 已提交审批`));

  // 1. 双击被冻结的单价：弹出审批进度，"查看审批详情"打开审批详情
  await (await cell(grid, line, 'PRICE')).dblclick();
  const frozen = user.locator('.approval-progress');
  await expect(frozen).toContainText('单据在审批中，不能修改');
  await expect(frozen).toContainText(approvalId);
  await frozen.getByRole('button', { name: '查看审批详情' }).click();
  await user.waitForURL(`**/approval/${approvalId}`);
  const userDetail = user.locator('.approval-detail-page');
  await expect(userDetail.locator('.approval-information')).toContainText(approvalId);
  await expect(userDetail.locator('summary', { hasText: '审批记录（1）' })).toBeVisible();

  // 2. admin 的铃铛：收到提交的通知后，角标等于待我审批的条数；通过后这个审批不在待审批里，角标仍等于待我审批的条数。
  // 整套并行运行时别的用例也在给 admin 提交、处理审批，所以每次都和当时的条数比（角标在通知、处理后或 60 秒内刷新）
  const pending = () =>
    adminApi.get<{ rows: Array<{ approvalId: string }>; total: number }>(
      '/api/approvals?box=todo&startRow=0&endRow=500'
    );
  // 数字为 0 时角标不显示（元素去掉或隐藏）；一次读完，不等元素出现
  const badgeText = () =>
    badge(admin).evaluateAll(els => {
      const el = els[0] as HTMLElement | undefined;
      if (!el || !el.offsetParent) return null;
      return el.getAttribute('title');
    });
  const badgeMatchesTodo = () =>
    expect
      .poll(
        async () => {
          const { total } = await pending();
          return (await badgeText()) === (total > 0 ? String(total) : null);
        },
        { timeout: 65_000 }
      )
      .toBe(true);
  await expect.poll(() => noticed(adminEvents, `/approval/${approvalId}`)).toBe(true);
  expect((await pending()).rows.map(r => r.approvalId)).toContain(approvalId);
  await badgeMatchesTodo();

  const detail = await openTodo(admin, docId, approvalId);
  await passInDetail(admin, detail);
  expect((await pending()).rows.map(r => r.approvalId)).not.toContain(approvalId);
  await badgeMatchesTodo();

  // 3. 审批记录：提交、通过两行；默认收起，点开后显示
  const history = detail.locator('.approval-history');
  await expect(history.locator('summary')).toHaveText('审批记录（2）');
  await history.locator('summary').click();
  const records = history.locator('.ag-center-cols-container .ag-row');
  await expect(records).toHaveCount(2);
  await expect(records.nth(0)).toContainText('提交');
  await expect(records.nth(0)).toContainText('提交审批，进入第 1 级');
  await expect(records.nth(1)).toContainText('通过');
  await expect(records.nth(1)).toContainText('第 1 级通过，审批通过');

  // 4. 待办的"全部审批"：已通过的审批还在
  await openMenu(admin, '待办');
  await admin.waitForURL('**/approval');
  const todo = admin.locator('.approval-todo-page');
  await todo.locator('.n-tabs-tab', { hasText: '全部审批' }).click();
  await expect(todo.getByText('当前显示全部审批历史')).toBeVisible();
  const row = todo.locator('.ag-center-cols-container .ag-row', { hasText: `${docId}（` }).first();
  await expect(row).toContainText('已通过');

  // 5. 原单据：成本核算只显示并选中这张单据，明细跟着显示；地址不再带 record
  await row.getByRole('button', { name: '原单据' }).click();
  await admin.waitForURL('**/page/COST_PINGGU');
  const master = masterGrid(admin);
  await expect(master.locator(`.ag-row-selected[row-id="${docId}"]`).first()).toBeVisible();
  await expect(master.locator('.ag-pinned-left-cols-container .ag-row')).toHaveCount(1);
  await expect(toolbar(admin)).toContainText(`只显示单据 ${docId}`);
  await showDetail(admin, '原料/辅料');
  await expect(await cell(detailGrid(admin, 'COST_MATERIAL'), line, 'PRICE')).toHaveText('90.00');

  // 6. 查看审批进度：这张单据的审批（已通过），能进审批详情
  await toolbar(admin).getByRole('button', { name: '查看审批进度' }).click();
  const progress = admin.locator('.approval-progress');
  await expect(progress).toContainText(`单据 ${docId} 的审批进度`);
  await expect(progress).toContainText(approvalId);
  await expect(progress).toContainText('已通过');
  await progress.getByRole('button', { name: '查看审批详情' }).click();
  await admin.waitForURL(`**/approval/${approvalId}`);
  await expect(admin.locator('.approval-detail-page .approval-status').first()).toContainText('已通过');
});
