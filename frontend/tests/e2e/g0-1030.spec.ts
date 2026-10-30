/**
 * 2026-10-30 G0 浏览器核对的 8 个场景（.reports/batch2-20261030/g0-verify/findings.md）改成的正式用例。
 * 场景 5 按 V3（.reports/batch3-20261030/v3-verify/findings.md 场景 1、2）的做法：新单据先用产品 Lookup 选产品；
 * 场景 6"同步采购价"按钮用户 2026-10-30 已删除，改成核对主表不再有这个按钮。
 * 写数据的用自己的测试成本单（data），只读的直接看 d_cg 已有的单据（2919、200721、审批 13、14）。
 */
import type { Locator } from '@playwright/test';
import { formatScale } from '../../src/modules/page/fields';
import { summaryTexts } from './data';
import {
  DIALOG_SLOT_WARNINGS,
  type Page,
  cell,
  detailGrid,
  edit,
  expect,
  filterColumn,
  masterGrid,
  mustSave,
  nextFrame,
  openDoc,
  openPage,
  runButton,
  save,
  scrollToColumn,
  selectRow,
  showDetail,
  test,
  toast,
  toolbar,
  watchConsole
} from './support';

type ListBody = {
  rows: Array<{ rowKey: string; values: Record<string, string | null> }>;
  total: number;
  aggregates: Record<string, string | null>;
};

/** 打开成本核算，同时拿到第一次列表查询（主表第一页）的响应 */
async function openWithList(page: Page) {
  const listed = page.waitForResponse(
    r => r.url().endsWith('/api/pages/COST_PINGGU/rows') && r.request().method() === 'POST'
  );
  await openPage(page, 'COST_PINGGU');
  return (await (await listed).json()) as ListBody;
}

/** 汇总行（表格底部固定行）中这些字段的文字；列在视野外时逐个横向滚过去再读 */
async function summaryValues(grid: Locator, fields: string[]) {
  const out: Record<string, string> = {};
  for (const name of fields) {
    // 逐列滚动后读取，按顺序进行
    // eslint-disable-next-line no-await-in-loop
    await scrollToColumn(grid, name);
    // eslint-disable-next-line no-await-in-loop
    out[name] = ((await grid.locator(`.ag-floating-bottom [col-id="${name}"]`).first().textContent()) ?? '').trim();
  }
  return out;
}

const num = (text: unknown) => Number(String(text ?? '').replace(/,/g, '') || 0);

/** 新增行保存后在主表里的 row-id：换成新主键，或仍是临时编号（等两者之一出现） */
async function savedRowId(grid: Locator, docId: string, clientRowId: string) {
  const either = grid.locator(
    `.ag-pinned-left-cols-container .ag-row[row-id="${docId}"], .ag-pinned-left-cols-container .ag-row[row-id="${clientRowId}"]`
  );
  await expect(either.first()).toBeVisible();
  return (await either.first().getAttribute('row-id'))!;
}

// ---------------------------------------------------------------- 1 主表汇总行

test('场景 1 主表汇总行：不筛选和产品名称含"片"时，汇总行按小数位显示后端返回的合计', async ({ page, api }) => {
  const view = await api.view();
  const summed = view.master.fields.filter(f => f.aggregate === 'sum');
  expect(summed.map(f => f.name)).toEqual([
    'TOTAL_FL',
    'TOTAL_BC',
    'TOTAL_YL',
    'TOTAL_COST',
    'COST_PERBOX',
    'OUT_PRICE_RMB',
    'SALEMONEY',
    'JGF_BATCH',
    'COST_PERQP',
    'JGF_PERQP',
    'ML_PERQP',
    'Y_JG_RE',
    'Y_ML',
    'Y_SALE'
  ]);
  const names = summed.map(f => f.name);
  const grid = masterGrid(page);
  const all = await openWithList(page);
  const read = () => summaryValues(grid, names);
  await expect.poll(read).toEqual(summaryTexts(summed, all.aggregates));

  const filtered = await filterColumn(page, 'GOODSNAME', '片');
  expect(filtered.request.filterModel).toEqual({ GOODSNAME: { filterType: 'text', type: 'contains', filter: '片' } });
  expect(filtered.body.total).toBeGreaterThan(0);
  expect(filtered.body.total).toBeLessThan(all.total);
  await expect.poll(read).toEqual(summaryTexts(summed, filtered.body.aggregates));
});

// ---------------------------------------------------------------- 2 明细汇总行

/** 明细区的按钮：堆叠方式在各明细的标题旁，页签方式在明细栏右侧 */
function detailButton(page: Page, entity: string, label: string) {
  const inStack = detailGrid(page, entity).getByRole('button', { name: label, exact: true });
  const inBar = page.locator('.generic-page__detail-bar').getByRole('button', { name: label, exact: true });
  return inStack.or(inBar).first();
}

test('场景 2 明细汇总行：标删除后汇总行和主表合计跟着变，撤销恢复，刷新放弃后不变，全程不提交命令', async ({
  page,
  data,
  api
}) => {
  const doc = await data.copyDoc('2550');
  const k30 = doc.row('206323');
  const record = await api.record(doc.docId);
  const sum = (entity: string) => record.details[entity].reduce((s, r) => s + num(r.values.COST_BATCH), 0);
  const commands: string[] = [];
  page.on('request', r => {
    if (r.url().endsWith('/api/commands')) commands.push(r.url());
  });
  await openDoc(page, doc.docId);
  await showDetail(page, '原料/辅料');
  const materials = detailGrid(page, 'COST_MATERIAL');
  const master = masterGrid(page);
  const materialSum = () => summaryValues(materials, ['COST_BATCH']);
  // 原辅料每批成本 0 位小数，包材 2 位（页面视图）
  await expect.poll(materialSum).toEqual({ COST_BATCH: formatScale(String(sum('COST_MATERIAL')), 0) });
  await showDetail(page, '包材');
  await expect
    .poll(() => summaryValues(detailGrid(page, 'COST_PACKAGE'), ['COST_BATCH']))
    .toEqual({ COST_BATCH: formatScale(String(sum('COST_PACKAGE')), 2) });
  await showDetail(page, '原料/辅料');
  const masterTotal = async () => num((await summaryValues(master, ['TOTAL_FL'])).TOTAL_FL);
  const rowTotal = async () => num(await (await cell(master, doc.docId, 'TOTAL_FL')).textContent());
  const [summaryBefore, rowBefore] = [await masterTotal(), await rowTotal()];

  // 聚维酮K30（每批成本 750）标删除：删除线、1 行未保存；原辅料汇总少 750；主表这一行的辅料合计预览变了，主表汇总行变得一样多
  await (await cell(materials, k30, 'GOODSNAME')).click();
  await detailButton(page, 'COST_MATERIAL', '明细删除').click();
  await expect(materials.locator(`.ag-row[row-id="${k30}"]`).first()).toHaveClass(/row-deleted/);
  await expect(page.getByText('1 行未保存')).toBeVisible();
  await expect.poll(materialSum).toEqual({ COST_BATCH: formatScale(String(sum('COST_MATERIAL') - 750), 0) });
  await expect.poll(rowTotal).not.toBe(rowBefore);
  const rowAfter = await rowTotal();
  await expect
    .poll(async () => ((await masterTotal()) - summaryBefore).toFixed(2))
    .toBe((rowAfter - rowBefore).toFixed(2));

  // Ctrl+Z 撤销：删除标记去掉，汇总恢复
  await page.keyboard.press('Control+z');
  await expect(materials.locator(`.ag-row[row-id="${k30}"]`).first()).not.toHaveClass(/row-deleted/);
  await expect(page.getByText(/行未保存/)).toHaveCount(0);
  await expect.poll(materialSum).toEqual({ COST_BATCH: formatScale(String(sum('COST_MATERIAL')), 0) });
  await expect.poll(masterTotal).toBe(summaryBefore);

  // 再标删除后刷新：浏览器问要不要离开（确认离开），重新打开后汇总不变
  await (await cell(materials, k30, 'GOODSNAME')).click();
  await detailButton(page, 'COST_MATERIAL', '明细删除').click();
  await expect(page.getByText('1 行未保存')).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await openDoc(page, doc.docId);
  await showDetail(page, '原料/辅料');
  await expect.poll(materialSum).toEqual({ COST_BATCH: formatScale(String(sum('COST_MATERIAL')), 0) });
  expect(commands).toEqual([]);
  expect(await api.record(doc.docId)).toEqual(record);
});

// ---------------------------------------------------------------- 3 配置页求和列

type FieldState = { checked: boolean | null; disabled: boolean | null; type: string };

/** 配置页字段表的全部行：先横向滚到"求和"列，再纵向滚动收集字段名、类型、求和复选框的状态 */
async function sumColumn(grid: Locator) {
  await scrollToColumn(grid, 'aggregate');
  return grid
    .locator('.ag-body-viewport')
    .first()
    .evaluate(async el => {
      const frame = () =>
        new Promise(resolve => {
          requestAnimationFrame(() => requestAnimationFrame(resolve));
        });
      const root = el.closest('.ag-root-wrapper') as HTMLElement;
      const rows: Record<string, { checked: boolean | null; disabled: boolean | null; type: string }> = {};
      const grab = () => {
        for (const row of Array.from(root.querySelectorAll('.ag-center-cols-container .ag-row'))) {
          const name = row.querySelector('[col-id="name"]')?.textContent?.trim();
          const box = row.querySelector<HTMLInputElement>('[col-id="aggregate"] input[type="checkbox"]');
          if (name && !rows[name])
            rows[name] = {
              checked: box ? box.checked : null,
              disabled: box ? box.disabled : null,
              type: row.querySelector('[col-id="type"]')?.textContent?.trim() ?? ''
            };
        }
      };
      el.scrollTop = 0;
      await frame();
      for (let top = 0; top <= el.scrollHeight; top += el.clientHeight / 2) {
        el.scrollTop = top;
        // 逐段滚，每段等表格画完再收集
        // eslint-disable-next-line no-await-in-loop
        await frame();
        grab();
      }
      el.scrollTop = 0;
      return rows;
    }) as Promise<Record<string, FieldState>>;
}

test('场景 3 配置页"求和"列：主表勾的正好是 14 个汇总字段、明细只有每批成本；文本和布尔字段不能勾（只看不存）', async ({
  page,
  api
}) => {
  const writes: string[] = [];
  page.on('request', r => {
    if (r.url().includes('/api/config/items') && r.method() !== 'GET') writes.push(`${r.method()} ${r.url()}`);
  });
  const view = await api.view();
  await page.goto('/config');
  await page.locator('.unified-config').getByText('成本核算', { exact: true }).first().click();
  const section = page.locator('.section-tables');
  await expect(section.locator('.ag-root-wrapper').first()).toBeVisible();
  const items = section.locator('.n-collapse-item');
  await expect(items).toHaveCount(3);
  await expect(section.locator('.n-collapse-item__header-main')).toHaveText([
    /主表: COST_PINGGU/,
    /从表: COST_MATERIAL/,
    /从表: COST_PACKAGE/
  ]);
  for (const item of await items.all()) {
    // 逐个展开，按顺序进行
    // eslint-disable-next-line no-await-in-loop
    const opened = await item.locator('.ag-root-wrapper').count();
    // eslint-disable-next-line no-await-in-loop
    if (!opened) await item.locator('.n-collapse-item__header-main').first().click();
  }
  const grids = section.locator('.ag-root-wrapper').filter({ has: page.locator('[col-id="locks"]') });
  await expect(grids).toHaveCount(3);
  const [master, material, pkg] = [
    await sumColumn(grids.nth(0)),
    await sumColumn(grids.nth(1)),
    await sumColumn(grids.nth(2))
  ];
  const checked = (rows: Record<string, FieldState>) => Object.keys(rows).filter(n => rows[n].checked);
  expect(checked(master).sort()).toEqual(
    view.master.fields
      .filter(f => f.aggregate === 'sum')
      .map(f => f.name)
      .sort()
  );
  expect(checked(material)).toEqual(['COST_BATCH']);
  expect(checked(pkg)).toEqual(['COST_BATCH']);
  for (const [name, row] of Object.entries(master)) {
    const numeric = view.master.fields.find(f => f.name === name)?.type === 'number';
    expect(row.disabled, `${name} 的"求和"${numeric ? '应能勾' : '不能勾'}`).toBe(!numeric);
  }
  // 文本字段 GOODSNAME：点了也勾不上，悬停提示只有数值字段能求和
  const goods = grids
    .nth(0)
    .locator('.ag-center-cols-container .ag-row')
    .filter({ has: page.locator('[col-id="name"]', { hasText: /^GOODSNAME$/ }) });
  await grids
    .nth(0)
    .locator('.ag-body-viewport')
    .first()
    .evaluate(el => {
      el.scrollTop = 0;
    });
  const box = goods.locator('[col-id="aggregate"] input[type="checkbox"]');
  await box.click({ force: true });
  await expect(box).not.toBeChecked();
  await goods.locator('[col-id="aggregate"]').hover();
  await expect(page.locator('.ag-tooltip')).toContainText('只有数值字段能求和');
  expect(writes).toEqual([]);
});

// ---------------------------------------------------------------- 4 校验和红底

const RED = 'rgb(255, 204, 204)';

test('场景 4a 红底：打开成本核算不做编辑，备注为"ERP未搭建BOM"的单据整行红底，其余白底（只读）', async ({ page }) => {
  const list = await openWithList(page);
  const grid = masterGrid(page);
  const rendered = await grid
    .locator('.ag-pinned-left-cols-container .ag-row[row-id]')
    .evaluateAll(rows => rows.map(r => r.getAttribute('row-id')!));
  const noBom = list.rows.filter(r => r.values.MEMO === 'ERP未搭建BOM').map(r => r.rowKey);
  const shown = rendered.filter(id => list.rows.some(r => r.rowKey === id));
  expect(
    shown.some(id => noBom.includes(id)),
    '第一页渲染出的行里要有"ERP未搭建BOM"的单据'
  ).toBe(true);
  for (const id of shown) {
    const expected = noBom.includes(id) ? RED : 'rgb(255, 255, 255)';
    for (const area of ['.ag-pinned-left-cols-container', '.ag-center-cols-container'])
      // 每行左右两区逐个核对
      // eslint-disable-next-line no-await-in-loop
      await expect(grid.locator(`${area} .ag-row[row-id="${id}"]`), `${id} ${area}`).toHaveCSS(
        'background-color',
        expected
      );
  }
});

test('场景 4b 拒绝提示：2919 改一行单价，预览和保存都提示每片含量必填，保存被拒（422），数据不变', async ({
  page,
  api
}) => {
  const before = await api.record('2919');
  await openDoc(page, '2919');
  await showDetail(page, '原料/辅料');
  const materials = detailGrid(page, 'COST_MATERIAL');
  await edit(page, await cell(materials, '100714', 'PRICE'), '27');
  await expect(page.locator('.generic-page__effects .text-error').first()).toHaveText('每片含量必填且必须大于0');
  await expect(page.getByText('1 行未保存')).toBeVisible();
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/commands') && r.request().method() === 'POST'),
    toolbar(page).getByRole('button', { name: '保存', exact: true }).click()
  ]);
  expect(response.status()).toBe(422);
  const body = await response.json();
  expect(body.code).toBe('RULE_REJECTED');
  expect(
    body.details.map((d: { entity: string; rowKey: string; field: string }) => [d.entity, d.rowKey, d.field])
  ).toEqual([['COST_MATERIAL', '100714', 'PER_HL']]);
  await toast(page, '每片含量必填且必须大于0（原料/辅料 一水乳糖（200目））');
  await expect(await cell(materials, '100714', 'PER_HL')).toHaveClass(/cell-error/);
  await expect(page.getByText('1 行未保存')).toBeVisible();
  // 刷新放弃修改（浏览器问要不要离开，确认离开）
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(masterGrid(page).locator('.ag-row').first()).toBeVisible();
  await expect(page.getByText(/行未保存/)).toHaveCount(0);
  expect(await api.record('2919')).toEqual(before);
});

// ---------------------------------------------------------------- 5 新建成本单选产品、由BOM生成明细；复制带产品

test('场景 5a 新建成本单：产品 Lookup 选 392，保存，由BOM生成 11 行明细，主表合计更新；关闭 Lookup 时控制台没有 naive 报错', async ({
  page,
  data,
  api
}) => {
  const messages = watchConsole(page);
  await openPage(page, 'COST_PINGGU');
  const grid = masterGrid(page);
  await toolbar(page).getByRole('button', { name: '新增', exact: true }).click();
  const newRow = grid.locator('.ag-pinned-left-cols-container .ag-row.row-new').first();
  await expect(newRow).toBeVisible();
  const clientRowId = (await newRow.getAttribute('row-id'))!;

  await (await cell(grid, clientRowId, 'GOODSID')).dblclick();
  const dialog = page.locator('.lookup-dialog');
  await expect(dialog.locator('.ag-center-cols-container .ag-row').first()).toBeVisible();
  const searched = page.waitForResponse(r => r.url().endsWith('/api/lookups/costGoods/search'));
  await dialog.getByPlaceholder('输入关键字搜索').fill('500mg对乙酰氨基酚片');
  await dialog.getByPlaceholder('输入关键字搜索').press('Enter');
  const lookupRow = ((await (await searched).json()).rows as Array<{ values: Record<string, string | null> }>).find(
    r => r.values.GOODSID === '392'
  )!.values;
  const target = dialog
    .locator('.ag-center-cols-container .ag-row')
    .filter({ has: page.locator('[col-id="GOODSID"]', { hasText: /^392$/ }) })
    .first();
  await target.dblclick();
  await expect(dialog).toHaveCount(0); // 离场动画结束、卡片移除
  await nextFrame(page);
  expect(messages.filter(m => DIALOG_SLOT_WARNINGS.test(m.text))).toEqual([]);
  // 带出的字段与 Lookup 返回的这一行相同；备注带出"ERP已搭建BOM"，改成测试标记
  for (const name of ['GOODSNAME', 'STRENGTH', 'MA_NO', 'MAH', 'CUSTOMNAME', 'MEMO'])
    // eslint-disable-next-line no-await-in-loop
    await expect(await cell(grid, clientRowId, name), name).toHaveText(lookupRow[name] ?? '');
  expect(lookupRow.MEMO).toBe('ERP已搭建BOM');
  await edit(page, await cell(grid, clientRowId, 'MEMO'), data.marker);

  const saved = mustSave(await save(page));
  expect(saved.approvals).toEqual([]);
  const docId = saved.idMap[clientRowId];
  data.adopt(docId);
  await toast(page, '已保存');
  const master = (await api.record(docId)).master.values;
  expect([master.GOODSID, master.GOODSNAME, master.MEMO]).toEqual(['392', '500mg对乙酰氨基酚片', data.marker]);

  await selectRow(page, await savedRowId(grid, docId, clientRowId));
  const bom = mustSave(await runButton(page, '由BOM生成明细'));
  expect(bom.approvals).toEqual([]);
  await toast(page, '由BOM生成明细已完成');
  const record = await api.record(docId);
  const goodsOf = (entity: string) => record.details[entity].map(r => r.values.GOODSID).sort();
  expect(goodsOf('COST_MATERIAL')).toEqual(['115', '57', '7109', '9631', '99'].sort());
  expect(goodsOf('COST_PACKAGE')).toEqual(['14454', '406', '407', '409', '410', '6488'].sort());
  await showDetail(page, '原料/辅料');
  for (const row of record.details.COST_MATERIAL)
    // eslint-disable-next-line no-await-in-loop
    await expect(detailGrid(page, 'COST_MATERIAL').locator(`.ag-row[row-id="${row.rowKey}"]`).first()).toBeVisible();
  const view = await api.view();
  const rowId = await savedRowId(grid, docId, clientRowId);
  for (const name of ['TOTAL_YL', 'TOTAL_FL', 'TOTAL_BC', 'TOTAL_COST']) {
    const field = view.master.fields.find(f => f.name === name)!;
    // eslint-disable-next-line no-await-in-loop
    await expect(await cell(grid, rowId, name), name).toHaveText(
      formatScale(String(record.master.values[name]), field.scale)
    );
  }
  expect(num(record.master.values.TOTAL_COST)).toBeGreaterThan(0);
});

test('场景 5b 复制带产品：复制 200721 只要主表，保存后产品ID、产品名称都在；关闭复制对话框时控制台没有 naive 报错', async ({
  page,
  data,
  api
}) => {
  const messages = watchConsole(page);
  const source = (await api.record('200721')).master.values;
  await openDoc(page, '200721');
  await toolbar(page).getByRole('button', { name: '复制', exact: true }).click();
  const dialog = page.locator('.copy-dialog');
  await expect(dialog).toBeVisible();
  // 对话框中依次为：主表字段；原料/辅料的行、字段；包材的行、字段。明细行全部不勾
  const groups = dialog.locator('.n-checkbox-group');
  await expect(groups).toHaveCount(5);
  const rowBoxes = [
    ...(await groups.nth(1).getByRole('checkbox').all()),
    ...(await groups.nth(3).getByRole('checkbox').all())
  ];
  for (const box of rowBoxes)
    // 逐个取消，按顺序进行
    // eslint-disable-next-line no-await-in-loop
    await box.setChecked(false);
  await dialog.getByRole('button', { name: '确定' }).click();
  await expect(page.locator('.copy-dialog')).toHaveCount(0); // 离场动画结束、卡片移除
  await nextFrame(page);
  expect(messages.filter(m => DIALOG_SLOT_WARNINGS.test(m.text))).toEqual([]);

  const grid = masterGrid(page);
  const newRow = grid.locator('.ag-pinned-left-cols-container .ag-row.row-new').first();
  const clientRowId = (await newRow.getAttribute('row-id'))!;
  await expect(await cell(grid, clientRowId, 'GOODSID')).toHaveText(String(source.GOODSID));
  await expect(await cell(grid, clientRowId, 'GOODSNAME')).toHaveText(String(source.GOODSNAME));
  await edit(page, await cell(grid, clientRowId, 'MEMO'), data.marker);
  const saved = mustSave(await save(page));
  const docId = saved.idMap[clientRowId];
  data.adopt(docId);
  await toast(page, '已保存');
  const copied = await api.record(docId);
  expect([copied.master.values.GOODSID, copied.master.values.GOODSNAME, copied.master.values.CUSTOMID]).toEqual([
    source.GOODSID,
    source.GOODSNAME,
    source.CUSTOMID
  ]);
  expect([copied.details.COST_MATERIAL, copied.details.COST_PACKAGE]).toEqual([[], []]);
  await expect(await cell(grid, await savedRowId(grid, docId, clientRowId), 'GOODSID')).toHaveText(
    String(source.GOODSID)
  );
});

// ---------------------------------------------------------------- 6 同步采购价按钮已删除

test('场景 6 主表工具栏不再有"同步采购价"；不选行时"由BOM生成明细"不可用（只读）', async ({ page, api }) => {
  const view = await api.view();
  expect(view.master.buttons.map(b => b.action)).not.toContain('syncPrice');
  await openPage(page, 'COST_PINGGU');
  await expect(toolbar(page).getByRole('button', { name: '由BOM生成明细' })).toBeDisabled();
  await expect(toolbar(page).getByRole('button', { name: '同步采购价' })).toHaveCount(0);
  expect(await page.locator('.ag-row-selected').count()).toBe(0);
});

// ---------------------------------------------------------------- 7 审批显示

test('场景 7 审批显示：已通过的审批 13、14 显示角色名和按 precision 补零的修改前后值（只读）', async ({ page }) => {
  await page.goto('/approval/13');
  let detail = page.locator('.approval-detail-page');
  await expect(detail.locator('.approval-status')).toContainText('已通过');
  await expect(detail).toContainText('角色：系统管理员（已通过，系统管理员）');
  for (const text of ['75.00 → 90.00', '750.00 → 900.00', '13.0065 → 13.0214', '94.73 → 94.60'])
    // eslint-disable-next-line no-await-in-loop
    await expect(detail, text).toContainText(text);

  await page.goto('/approval/14');
  detail = page.locator('.approval-detail-page');
  await expect(detail.locator('.approval-status')).toContainText('已通过');
  await expect(detail).toContainText('角色：系统管理员（已通过，系统管理员）');
  for (const text of ['90.00 → 75.00', '900.00 → 750.00', '13.0214 → 13.0065', '94.60 → 94.73'])
    // eslint-disable-next-line no-await-in-loop
    await expect(detail, text).toContainText(text);
});

// ---------------------------------------------------------------- 8 AG Grid 授权

test('场景 8 AG Grid 授权：成本核算的表格上没有可见的水印；控制台的授权消息记在用例说明里（只读）', async ({
  page
}) => {
  const messages = watchConsole(page);
  await openDoc(page, '2550');
  await expect(detailGrid(page, 'COST_MATERIAL').locator('.ag-row').first()).toBeAttached();
  await expect(page.locator('.ag-watermark').filter({ visible: true })).toHaveCount(0);
  // 授权消息是星号边框围起来的几行，每行一条 console.error；去掉星号后按出现先后去重记下
  const banner = [
    ...new Set(
      messages
        .filter(m => m.type === 'error' && m.text.startsWith('*'))
        .map(m => m.text.replace(/\*+/g, ' ').replace(/\s+/g, ' ').trim())
        .filter(Boolean)
    )
  ];
  test.info().annotations.push({ type: 'AG Grid 授权消息', description: banner.join(' / ') || '没有' });
});
