/**
 * T-AS-7 批次 D（真实联调，浏览器 → 前端 → 后端 → d_cg）。成本核算页 /page/COST_PINGGU。
 * 数据隔离：要写数据的用例经平台复制 2550（只带单价等于执行价的明细）或新建自己的测试成本单（备注带 PF_TEST），
 * 用例结束时删除（support.ts 的 data）；改共用配置的用例拿测试锁 `page.COST_PINGGU`。
 *
 * 1. 保存后不整页刷新、页面与数据库一致；前端预览与后端计算按 C01 一致：admin 把预胶化淀粉（2550 的 206324）的每片含量
 *    15 → 16，页面按 Worker 的预览显示每批成本 200；保存后 window 上的标记和主表表格的 DOM 元素都还在（没有整页刷新、
 *    没有重建表格），页面显示的值与后端重新读出的单据相同；预览的计算字段与命令结果中后端算出的值按 C01 第 3 节一致
 *    （后端写入前按 WP-15 保留 8 位小数，所以预览值先按 WP-15 处理再比较）。
 * 2. 管理员保存配置后，已打开的页面无需刷新即生效：chengben01 开着成本核算；admin 保存页面配置把主表"产品英文名"列
 *    设为不显示，chengben01 的页面上这一列随即消失、页面没有刷新；改回后这一列又出现。（页面配置的列宽用 initialWidth，
 *    已打开的表格不跟着变，FP-08、FP-09，所以用列的显示与否来看配置是否生效。）
 * 3. 复制成本单：只勾选原辅料中的聚维酮K30、玉米淀粉两行，主表不勾"备注""年需求量"，明细不勾"额外投料量""备注"，
 *    包材一行不勾；保存后新单据只有这两行明细、没有包材，没勾的字段为空，勾了的字段与来源相同，每批数量、每批成本、
 *    主表每批辅料成本为后端按新单据重算的值。
 * 4. 停用账号后浏览器立即回到登录页：测试账号（成本会计角色）开着成本核算，admin 停用它，页面不用任何操作就回到登录页；
 *    恢复启用后能重新登录。（停用会撤销这个账号的全部会话，所以用自己建的账号，不动 setup 存下的 chengben01 会话。）
 * 5. 在浏览器中完成审批（C06 7.8 样例一，d_cg 的 COST_TO_GOODS 只有第 1 级）：chengben01 把测试物料的单价 75 → 90 保存，
 *    提示已提交审批、单价仍显示 75.00，再双击单价弹出审批进度；admin 的铃铛不刷新就多一条通知，在待办中打开详情
 *    （单价 75.00 → 90.00）并通过；chengben01 的铃铛收到"已通过"。测试物料（参考价格 75、执行价为空）由
 *    backend/tests/e2e/sample_two.py 建、删，通过后写入的执行价不影响别的物料。
 */
import type { Locator } from '@playwright/test';
import { numbersConsistent } from '../../src/contracts/decimal-text';
import { formatScale } from '../../src/modules/page/fields';
import { type Row, copyRowLabel, wp15 } from './data';
import {
  cell,
  cellText,
  detailGrid,
  edit,
  expect,
  header,
  login,
  masterGrid,
  mustSave,
  notice,
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

const SOURCE = '2550';
const K30 = '206323';
const PREGEL = '206324';
const CORN = '206326';

type ViewField = { name: string; scale: number | null; calculated: boolean };

/** 在页面加载前包一层 Worker：记下每次求值的请求和结果（C07 第 5 节的消息） */
function captureCalc() {
  const NativeWorker = window.Worker;
  const calls: Array<{ request: string; result: string | null }> = [];
  (window as unknown as { e2eCalc: typeof calls }).e2eCalc = calls;
  window.Worker = class extends NativeWorker {
    constructor(url: string | URL, options?: WorkerOptions) {
      super(url, options);
      const sent = new Map<number, string>();
      const post = this.postMessage.bind(this);
      this.postMessage = ((message: { id?: number; type?: string; request?: string }, transfer?: Transferable[]) => {
        if (message?.type === 'evaluate' && message.id !== undefined) sent.set(message.id, message.request ?? '');
        return transfer ? post(message, transfer) : post(message);
      }) as Worker['postMessage'];
      this.addEventListener('message', ({ data }: MessageEvent<{ id: number; ok: boolean; result?: string }>) => {
        if (!sent.has(data.id)) return;
        calls.push({ request: sent.get(data.id)!, result: data.ok ? (data.result ?? null) : null });
        sent.delete(data.id);
      });
    }
  };
}

// ---------------------------------------------------------------- 1

test('保存后不整页刷新、页面与数据库一致；前端预览与后端计算按 C01 一致', async ({ page, data, api }) => {
  const doc = await data.copyDoc(SOURCE);
  const pregel = doc.row(PREGEL);
  await page.addInitScript(captureCalc);
  await openDoc(page, doc.docId);
  await showDetail(page, '原料/辅料');
  const grid = detailGrid(page, 'COST_MATERIAL');
  const before = await api.record(doc.docId);
  expect(before.details.COST_MATERIAL.find(r => r.rowKey === pregel)!.values.PER_HL).toBe('15');
  // 整页刷新会丢掉 window 上的标记；重建表格会换掉表格的 DOM 元素
  await page.evaluate(() => {
    (window as unknown as { e2eKept: string }).e2eKept = 'kept';
  });
  await masterGrid(page)
    .locator('.ag-root-wrapper')
    .evaluate(el => {
      (el as unknown as { e2eKept: string }).e2eKept = 'kept';
    });

  await edit(page, await cell(grid, pregel, 'PER_HL'), '16');
  await expect(await cell(grid, pregel, 'COST_BATCH')).toHaveText('200'); // 本地预览算出的每批成本
  const calls = await page.evaluate(() => (window as unknown as { e2eCalc: Array<{ result: string | null }> }).e2eCalc);
  const preview = JSON.parse(calls.findLast(c => c.result?.includes(`"${pregel}"`))!.result!) as {
    rows: Array<{ entity: string; rowKey?: string; computed: Record<string, string | null> }>;
  };
  const result = mustSave(await save(page));
  await toast(page, '已保存');
  expect(await page.evaluate(() => (window as unknown as { e2eKept?: string }).e2eKept)).toBe('kept');
  expect(
    await masterGrid(page)
      .locator('.ag-root-wrapper')
      .evaluate(el => (el as unknown as { e2eKept?: string }).e2eKept)
  ).toBe('kept');

  // 预览与后端：命令结果中的行（本次写入的明细和重算的主表）每个计算字段都按 C01 第 3 节比较
  const compared: string[] = [];
  for (const row of result.rows) {
    const previewed = preview.rows.find(p => p.entity === row.entity && p.rowKey === row.rowKey);
    expect(previewed, `${row.entity} ${row.rowKey} 没有预览结果`).toBeTruthy();
    for (const [field, value] of Object.entries(previewed!.computed)) {
      const backend = row.values[field] as string | null;
      expect(
        numbersConsistent(value === null ? null : wp15(value), backend),
        `${field}：预览 ${value}，后端 ${backend}`
      ).toBe(true);
      compared.push(`${row.entity}.${field} ${value} ${backend}`);
    }
  }
  expect(compared.length).toBeGreaterThan(10);

  // 页面与数据库：后端重新读出的单据，按页面视图的小数位显示，与页面上的格子相同
  const view = await api.view();
  const record = await api.record(doc.docId);
  type Shown = { region: { fields: ViewField[] }; on: Locator; row: Row; names: string[] };
  const shown = async ({ region, on, row, names }: Shown) => {
    for (const name of names) {
      const field = region.fields.find(f => f.name === name)!;
      // 逐格横向滚动后读取，按顺序进行
      // eslint-disable-next-line no-await-in-loop
      expect(await cellText(on, row.rowKey!, name), name).toBe(
        formatScale(String(row.values[name] ?? ''), field.scale)
      );
    }
  };
  const materialRow = record.details.COST_MATERIAL.find(r => r.rowKey === pregel)!;
  expect(materialRow.values.PER_HL).toBe('16');
  await shown({ region: view.details[0], on: grid, row: materialRow, names: ['PER_HL', 'BATCH_QTY', 'COST_BATCH'] });
  await shown({
    region: view.master,
    on: masterGrid(page),
    row: { ...record.master, rowKey: doc.docId },
    names: ['TOTAL_FL', 'TOTAL_COST', 'COST_PERBOX', 'JGF_BATCH']
  });
});

// ---------------------------------------------------------------- 2

test(
  '管理员保存配置后，已打开的成本核算页无需刷新即生效',
  { lock: 'page.COST_PINGGU', tag: '@shared-config' },
  async ({ as, adminApi }) => {
    const viewer = await as('chengben01');
    const events = realtimeEvents(viewer);
    await openPage(viewer, 'COST_PINGGU');
    // 测试模式下全部列都已渲染：列头在不在就是这一列显示没有
    const english = header(masterGrid(viewer), 'GOODSNAME_EN');
    await expect(english).toBeVisible();
    await viewer.evaluate(() => {
      (window as unknown as { e2eKept: string }).e2eKept = 'kept';
    });

    const item = await adminApi.get('/api/config/items/page/COST_PINGGU');
    expect(item.content.master.fields.GOODSNAME_EN).toBeUndefined();
    const changed = structuredClone(item.content);
    changed.master.fields.GOODSNAME_EN = { visible: false };
    try {
      await adminApi.ok('PUT', '/api/config/items/page/COST_PINGGU', { name: item.name, content: changed });
      // 经 WebSocket 收到 config.changed，重新读取页面视图，整张表都找不到这一列
      await expect.poll(() => events.some(e => e.topic === 'config.changed')).toBe(true);
      await expect(english).toHaveCount(0);
    } finally {
      await adminApi.ok('PUT', '/api/config/items/page/COST_PINGGU', { name: item.name, content: item.content });
    }
    await expect(english).toHaveCount(1);
    expect(await viewer.evaluate(() => (window as unknown as { e2eKept?: string }).e2eKept)).toBe('kept');
    expect((await adminApi.get('/api/config/items/page/COST_PINGGU')).content).toEqual(item.content);
  }
);

// ---------------------------------------------------------------- 3

/** 复制对话框中一组复选框：`labels` 中的每一项按 `checked` 勾选或取消（默认全选） */
async function choose(group: Locator, labels: string[], checked: boolean) {
  // 像用户一样逐个点，按顺序进行
  for (const label of labels) {
    const box = group.getByRole('checkbox', { name: label, exact: true });
    // eslint-disable-next-line no-await-in-loop
    await expect(box).toBeChecked();
    // eslint-disable-next-line no-await-in-loop
    if (!checked) await box.setChecked(false);
  }
}

test('复制成本单：只勾选部分明细行和字段，新单据只含这些行，未勾选的字段为空，计算字段为后端重算的值', async ({
  page,
  data,
  api
}) => {
  const doc = await data.copyDoc(SOURCE);
  const keptKeys = [doc.row(K30), doc.row(CORN)];
  await openDoc(page, doc.docId);
  const source = await api.record(doc.docId);
  await page.getByRole('button', { name: '复制', exact: true }).click();
  const dialog = page.locator('.copy-dialog');
  await expect(dialog).toBeVisible();
  // 对话框中依次为：主表字段；原料/辅料的行、字段；包材的行、字段
  const groups = dialog.locator('.n-checkbox-group');
  await expect(groups).toHaveCount(5);
  const view = await api.view();
  const [materials, packages] = view.details;
  await choose(groups.nth(0), ['备注', '年需求量'], false);
  const kept = source.details.COST_MATERIAL.filter(r => keptKeys.includes(r.rowKey!));
  const dropped = source.details.COST_MATERIAL.filter(r => !keptKeys.includes(r.rowKey!));
  await choose(
    groups.nth(1),
    kept.map(r => copyRowLabel(materials, r.values)),
    true
  );
  await choose(
    groups.nth(1),
    dropped.map(r => copyRowLabel(materials, r.values)),
    false
  );
  await choose(groups.nth(2), ['额外投料量', '备注'], false);
  await choose(
    groups.nth(3),
    source.details.COST_PACKAGE.map(r => copyRowLabel(packages, r.values)),
    false
  );
  await dialog.getByRole('button', { name: '确定' }).click();
  await expect(dialog).toBeHidden();

  const result = mustSave(await save(page));
  await toast(page, '已保存');
  const newDoc = result.rows.find(r => r.entity === 'COST_PINGGU' && r.rowKey !== doc.docId)!.rowKey!;
  data.adopt(newDoc);
  const copied = await api.record(newDoc);
  const m = copied.master.values;
  // 没勾的字段为空；勾了的、可写的字段与来源相同
  expect([m.MEMO, m.ANNUAL_QTY]).toEqual([null, null]);
  for (const name of [
    'APEX_PL',
    'P_PERPACK',
    'S_PERBACK',
    'X_PERBACK',
    'YIELD',
    'PACKTYPE',
    'DOSAGE',
    'USESTATUS',
    'FMRATE'
  ])
    expect(m[name], name).toEqual(source.master.values[name]);
  // 明细只有勾选的两行，没有包材
  expect(copied.details.COST_PACKAGE).toEqual([]);
  const lines = copied.details.COST_MATERIAL;
  expect(
    lines.map(r => [r.values.GOODSID, r.values.PER_HL, r.values.PRICE, r.values.EXADD_MATER, r.values.MEMO])
  ).toEqual(kept.map(r => [r.values.GOODSID, r.values.PER_HL, r.values.PRICE, null, null]));
  // 计算字段为后端按新单据重算：每批数量 = 每片含量 × 批量 / 1000000，每批成本 = 每批数量 × 单价；没有原料，辅料合计不除以 1.13
  expect(lines.map(r => [r.values.BATCH_QTY, r.values.COST_BATCH])).toEqual([
    ['10', '750'],
    ['42.5', '935']
  ]);
  expect(m.TOTAL_FL).toBe('1685');
  expect(m.TOTAL_FL).not.toBe(source.master.values.TOTAL_FL);
});

// ---------------------------------------------------------------- 4

test('停用账号后，浏览器立即回到登录页', async ({ fresh: open, data, adminApi }) => {
  const account = await data.account({ roleCodes: ['COST_ACCOUNTANT'] });
  const user = await open();
  await login(user, account);
  await openPage(user, 'COST_PINGGU');

  const listed = async () =>
    (await adminApi.get(`/api/admin/accounts?keyword=${account.username}`)).rows.find(
      (r: { username: string }) => r.username === account.username
    );
  const before = await listed();
  expect(before.enabled).toBe(true);
  const update = { displayName: before.displayName, departmentId: before.departmentId, roleCodes: before.roleCodes };
  try {
    await adminApi.ok('PUT', `/api/admin/accounts/${before.userId}`, { ...update, enabled: false });
    await user.waitForURL('**/login**'); // 收到 session.revoked，不用任何操作
    await expect(user.getByPlaceholder('请输入用户名')).toBeVisible();
  } finally {
    await adminApi.ok('PUT', `/api/admin/accounts/${before.userId}`, { ...update, enabled: true });
  }
  await login(user, account);
  expect(await listed()).toEqual(before);
});

// ---------------------------------------------------------------- 5

test('在浏览器中完成审批：改单价提交审批、冻结、通知，管理员在待办中打开详情并通过', async ({
  page: admin,
  as,
  data,
  api
}) => {
  const goods = data.goods('75');
  const { docId, rows } = await data.newDoc([{ GOODSID: goods, PER_HL: '10', PRICE: '75' }]);
  const [line] = rows;
  const adminEvents = realtimeEvents(admin);
  await admin.goto('/home');

  const user = await as('chengben01');
  const userEvents = realtimeEvents(user);
  await openDoc(user, docId);
  await showDetail(user, '原料/辅料');
  const grid = detailGrid(user, 'COST_MATERIAL');
  await edit(user, await cell(grid, line, 'PRICE'), '90');
  await expect(await cell(grid, line, 'COST_BATCH')).toHaveText('900'); // 预览
  const submitted = await save(user);
  expect(submitted.outcome).toBe('approvalSubmitted');
  const approvalId = submitted.approvals[0].approvalId;
  await toast(user, /已提交审批/);
  await expect(await cell(grid, line, 'PRICE')).toHaveText('75.00'); // 审批结束前显示正式数据
  await (await cell(grid, line, 'PRICE')).dblclick();
  const progress = user.locator('.approval-progress');
  await expect(progress.getByText('审批编号')).toBeVisible();
  await expect(progress).toContainText(approvalId);
  await progress.getByRole('button', { name: '关闭' }).click();
  expect(await grid.locator('.ag-cell-inline-editing').count()).toBe(0);

  // admin 的页面不刷新，经实时连接收到这条审批的通知，铃铛的消息中心里有它
  const link = `/approval/${approvalId}`;
  await expect.poll(() => noticed(adminEvents, link)).toBe(true);
  await expect(await notice(admin, `业务单据为${docId}的审批`)).toBeVisible();
  await admin.keyboard.press('Escape');
  // 待办中打开详情
  const detail = await openTodo(admin, docId, approvalId);
  await expect(detail).toContainText('75.00');
  await expect(detail).toContainText('90.00');
  await passInDetail(admin, detail);

  // chengben01 的页面经实时连接收到"已通过"，铃铛的消息中心里有它；数据库中单价为 90
  await expect.poll(() => noticed(userEvents, link, true)).toBe(true);
  await expect(await notice(user, `业务单据为${docId}的审批已通过`)).toBeVisible();
  await user.keyboard.press('Escape');
  const after = (await api.record(docId)).details.COST_MATERIAL.find(r => r.rowKey === line)!.values;
  expect([after.PRICE, after.COST_BATCH]).toEqual(['90', '900']);
});
