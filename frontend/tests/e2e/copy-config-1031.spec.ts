/**
 * 第 9 批 B 组（2026-10-31）：复制主表连明细一起复制（现有能力，FP-13），以及页面配置"不复制"的列（C05 v11、C06 v30 的
 * `copy: false`，frontend-page FP-25、write-pipeline WP-24、业务例子 E45）。用户 2026-10-31："复制主表要把明细表一起复制过来，
 * 这个是通用方法，但是也可以配置哪些列可以不复制，这个在元数据中配置即可"。旧系统 copy-row-fields.ts 只排除 id 和主键，
 * 没有可配置项，"不复制"是新增能力。
 *
 * 1. 客户信息复制客户时分销商跟着复制（第 8 批 G1 留下的未核实项）：测试客户带一个分销商，admin 在客户信息页选中它点"复制"，
 *    对话框照默认全选、确定、保存；新客户的客户名称、区域与源客户相同，分销商明细也有一行，分销商名称与源行相同，
 *    分销商ID 是新的、客户ID 指向新客户。不改配置。
 * 2. 不复制的列（@shared-config，改客户信息页的配置，结束时改回）：把主表的区域 ZONE 配成 `copy: false`；复制测试客户时
 *    对话框里没有"区域"，新行区域为空，保存后读回仍为空，客户名称、分销商照旧复制。
 *    要本组的后端（页面字段设置的 `copy`，main 的后端保存这项配置时校验不过），待主代理合并后运行。
 *
 * 测试数据经平台接口建（客户信息页的保存命令），用例结束时按主键删掉测试客户和它的分销商（含复制出的，
 * backend/tests/e2e/basic_pages.py 的 drop）。
 */
import type { PageView } from '../../src/contracts/page-view';
import {
  type Api,
  type Locator,
  type Page,
  backendScript,
  test as base,
  cell,
  detailGrid,
  expect,
  filterColumn,
  masterGrid,
  mustSave,
  openPage,
  save,
  showDetail,
  toast,
  toolbar
} from './support';

const PAGE = 'CUSTOMER_MANAGE';
const SAVE = { page: PAGE, operation: 'CUSTOMER_MANAGE.save' };
const CUSTOMER = 'COST_CUSTOMER';
const DISTRIBUTOR = 'COST_TRANPOSER';

/** 本用例建的客户（连同分销商），结束时删掉 */
const test = base.extend<{ customers: string[] }>({
  // eslint-disable-next-line no-empty-pattern
  customers: async ({}, use) => {
    const made: string[] = [];
    await use(made);
    if (made.length) backendScript('tests.e2e.basic_pages', ['drop', '--customers', made.join(',')]);
  }
});

const tmp = () => `tmp-${crypto.randomUUID()}`;

/** 经客户信息页的保存命令建一个测试客户和它的一个分销商，返回客户ID 和分销商ID */
async function newCustomer(api: Api, customers: string[]) {
  const suffix = crypto.randomUUID().slice(0, 6).toUpperCase();
  const [customerRow, distributorRow] = [tmp(), tmp()];
  const names = { customer: `PF_TEST 客户${suffix}`, zone: 'PF_TEST 区域', distributor: `PF_TEST 分销商${suffix}` };
  const result = mustSave(
    await api.command(
      [
        {
          entity: CUSTOMER,
          master: { op: 'add', clientRowId: customerRow, values: { CUSTOMNAME: names.customer, ZONE: names.zone } },
          details: [
            { entity: DISTRIBUTOR, op: 'add', clientRowId: distributorRow, values: { TRANPOSNAME: names.distributor } }
          ]
        }
      ],
      SAVE
    )
  );
  const customerId = String(result.idMap[customerRow]);
  customers.push(customerId);
  return { customerId, distributorId: String(result.idMap[distributorRow]), names };
}

/** 按客户ID 筛出这个客户、选中它，点工具栏"复制"，返回复制对话框 */
async function openCopy(page: Page, customerId: string) {
  await openPage(page, PAGE);
  await filterColumn(page, 'CUSTOMID', customerId);
  const grid = masterGrid(page);
  await expect(grid.locator('.ag-center-cols-container .ag-row')).toHaveCount(1);
  await (await cell(grid, customerId, 'CUSTOMNAME')).click();
  await expect(grid.locator(`.ag-row-selected[row-id="${customerId}"]`).first()).toBeVisible();
  await toolbar(page).getByRole('button', { name: '复制', exact: true }).click();
  const dialog = page.locator('.copy-dialog');
  await expect(dialog).toBeVisible();
  return dialog;
}

/** 对话框中一组勾选框的标题和勾选状态 */
async function boxes(group: Locator) {
  const all = group.getByRole('checkbox');
  await expect(all.first()).toBeVisible();
  return all.evaluateAll(list =>
    list.map(box => [(box.textContent ?? '').trim(), box.getAttribute('aria-checked') === 'true'] as const)
  );
}

/** 确定复制、保存，返回新客户的临时编号和ID（复制出的主表行在源行下方）；调用方把新客户记进要删的客户 */
async function copyAndSave(page: Page, dialog: Locator, distributorName: string) {
  await dialog.getByRole('button', { name: '确定' }).click();
  await expect(dialog).toBeHidden();
  const added = masterGrid(page).locator('.ag-center-cols-container .ag-row.row-new');
  await expect(added).toHaveCount(1);
  const clientRowId = (await added.getAttribute('row-id'))!;
  // 新客户的分销商明细里是复制出的一行
  await showDetail(page, '分销商');
  const distributors = detailGrid(page, DISTRIBUTOR);
  const copied = distributors.locator('.ag-center-cols-container .ag-row.row-new');
  await expect(copied).toHaveCount(1);
  await expect(copied.locator('[col-id="TRANPOSNAME"]')).toHaveText(distributorName);
  const result = mustSave(await save(page));
  await toast(page, '已保存');
  return { clientRowId, newId: String(result.idMap[clientRowId]) };
}

test('客户信息复制客户：分销商明细跟着复制，名称与源行相同，分销商ID 是新的、客户ID 指向新客户', async ({
  page,
  api,
  customers
}) => {
  const source = await newCustomer(api, customers);
  const dialog = await openCopy(page, source.customerId);
  // 对话框：主表字段、分销商的行、分销商的字段三组，默认全选
  const groups = dialog.locator('.n-checkbox-group');
  await expect(groups).toHaveCount(3);
  const states = await Promise.all([0, 1, 2].map(index => boxes(groups.nth(index))));
  expect(states.map(group => group.every(([, checked]) => checked))).toEqual([true, true, true]);
  const { newId } = await copyAndSave(page, dialog, source.names.distributor);
  customers.push(newId);

  const copied = await api.record(newId, PAGE);
  expect(newId).not.toBe(source.customerId);
  const m = copied.master.values;
  expect([m.CUSTOMNAME, m.ZONE, m.ISERP]).toEqual([source.names.customer, source.names.zone, '0']);
  const rows = copied.details[DISTRIBUTOR];
  expect(rows.map(r => [r.values.TRANPOSNAME, r.values.CUSTOMID, r.values.ISERP])).toEqual([
    [source.names.distributor, newId, '0']
  ]);
  expect(rows[0].rowKey).not.toBe(source.distributorId);
  // 源客户不变
  const kept = await api.record(source.customerId, PAGE);
  expect(kept.details[DISTRIBUTOR].map(r => [r.rowKey, r.values.TRANPOSNAME])).toEqual([
    [source.distributorId, source.names.distributor]
  ]);
});

test(
  'E45 不复制的列：客户信息主表区域配成不复制，复制客户时对话框里没有"区域"，新客户区域为空，保存后读回仍为空（待主代理合并后运行）',
  { lock: `page.${PAGE}`, tag: '@shared-config' },
  async ({ page, api, adminApi, customers }) => {
    const item = await adminApi.get(`/api/config/items/page/${PAGE}`);
    const changed = structuredClone(item.content);
    changed.master.fields = { ...changed.master.fields, ZONE: { ...changed.master.fields?.ZONE, copy: false } };
    try {
      await adminApi.ok('PUT', `/api/config/items/page/${PAGE}`, { name: item.name, content: changed });
      const view = await api.get<PageView>(`/api/pages/${PAGE}/view`);
      const zone = view.master.fields.find(f => f.name === 'ZONE')!;
      expect(zone.copy).toBe(false);
      // 其余字段没有 copy 这一项（C05 v11：只在配置了时带出）
      expect(view.master.fields.filter(f => 'copy' in f).map(f => f.name)).toEqual(['ZONE']);
      const name = view.master.fields.find(f => f.name === 'CUSTOMNAME')!;

      const source = await newCustomer(api, customers);
      const dialog = await openCopy(page, source.customerId);
      const groups = dialog.locator('.n-checkbox-group');
      // 主表字段只有客户名称（客户ID 是主键、是否ERP 是 ERP 行标识，不列；区域配成了不复制）
      expect(await boxes(groups.nth(0))).toEqual([[name.label, true]]);
      await expect(dialog.getByRole('checkbox', { name: zone.label, exact: true })).toHaveCount(0);
      const { clientRowId, newId } = await copyAndSave(page, dialog, source.names.distributor);
      customers.push(newId);

      const copied = await api.record(newId, PAGE);
      const m = copied.master.values;
      expect([m.CUSTOMNAME, m.ZONE ?? null]).toEqual([source.names.customer, null]);
      expect(copied.details[DISTRIBUTOR].map(r => [r.values.TRANPOSNAME, r.values.CUSTOMID])).toEqual([
        [source.names.distributor, newId]
      ]);
      // 页面上新客户的区域也是空的。保存后表格按原来的筛选（源客户的ID）刷新，新客户不在其中：按新客户的ID 重新筛选
      expect(clientRowId).not.toBe(newId);
      await filterColumn(page, 'CUSTOMID', newId);
      const grid = masterGrid(page);
      // 本页保存过的行仍用临时编号作 row-id（表格只换了值），所以按筛出的这一行取格子
      const shown = grid.locator('.ag-center-cols-container .ag-row');
      await expect(shown).toHaveCount(1);
      await expect(shown.locator('[col-id="CUSTOMID"]')).toHaveText(newId);
      await expect(shown.locator('[col-id="ZONE"]')).toHaveText('');
    } finally {
      await adminApi.ok('PUT', `/api/config/items/page/${PAGE}`, { name: item.name, content: item.content });
    }
    expect((await adminApi.get(`/api/config/items/page/${PAGE}`)).content).toEqual(item.content);
  }
);
