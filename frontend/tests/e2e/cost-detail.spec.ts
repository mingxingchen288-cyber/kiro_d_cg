/**
 * 链路 1（真实联调，浏览器 → 后端 → d_cg）：成本核算主从页的明细。
 * admin 打开成本核算，页面下方有"原料/辅料""包材"两个页签；选中成本单 2550，在"原料/辅料"把第一行（DTLID 206323）的
 * 备注改为"测试"并保存；刷新页面再选 2550 显示"测试"；再改回原值保存。"客户指定"复选框勾选、保存，再取消、保存。
 * 200680（E01 的单据）在 cmx 中已经没有明细，改用同为 250mg乙酰唑胺片的 2550。
 * 数据库中的值由 backend/tests/e2e/test_cost_detail.py 和运行后的只读查询核对。
 */
import { type Locator, type Page, expect, test } from '@playwright/test';

const DOCID = '2550';
const DTLID = '206323';

function materialGrid(page: Page) {
  return page.getByTestId('detail-COST_MATERIAL');
}

function detailCell(page: Page, column: string) {
  return materialGrid(page).locator(`.ag-center-cols-container .ag-row[row-id="${DTLID}"] [col-id="${column}"]`);
}

async function login(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill('admin');
  await page.getByPlaceholder('请输入密码').fill('admin123..');
  await page.getByRole('button', { name: '确认' }).click();
  await page.waitForURL('**/home');
}

/** AG Grid 只渲染视野内的列：像用户拖动横向滚动条一样，逐段向右滚到这一格出现 */
async function scrollTo(grid: Locator, cell: Locator) {
  await grid.locator('.ag-body-horizontal-scroll-viewport').evaluate(async (el, selector) => {
    const root = el.closest('[data-testid]') as HTMLElement;
    for (let left = 0; left < 20_000 && !root.querySelector(selector); left += 500) {
      el.scrollLeft = left;
      // eslint-disable-next-line no-await-in-loop
      await new Promise(resolve => {
        setTimeout(resolve, 100);
      });
    }
  }, `.ag-center-cols-container .ag-row[row-id="${DTLID}"] [col-id="MEMO"]`);
  await expect(cell).toBeVisible();
}

/** 打开成本核算页，选中成本单 2550（默认按主键升序，是第一行），等原料/辅料明细出现 */
async function openDocument(page: Page) {
  await page.goto('/cost-pinggu');
  await expect(page.locator('.n-tabs-tab', { hasText: '原料/辅料' })).toBeVisible();
  await expect(page.locator('.n-tabs-tab', { hasText: '包材' })).toBeVisible();
  await page
    .getByTestId('master-grid')
    .locator(`.ag-pinned-left-cols-container .ag-row[row-id="${DOCID}"] [col-id="DOCID"]`)
    .click();
  await expect(materialGrid(page).locator(`.ag-center-cols-container .ag-row[row-id="${DTLID}"]`)).toBeVisible();
}

async function saveAndWait(page: Page) {
  await expect(page.getByText('1 行未保存')).toBeVisible();
  await page.getByRole('button', { name: '保存' }).click();
  await expect(page.getByText('已保存')).toBeVisible();
  await expect(page.getByText('1 行未保存')).toBeHidden();
}

async function editMemo(page: Page, value: string) {
  await detailCell(page, 'MEMO').dblclick();
  await page.keyboard.press('Control+A');
  if (value) {
    await page.keyboard.type(value);
  } else {
    await page.keyboard.press('Backspace');
  }
  await page.keyboard.press('Enter');
  await saveAndWait(page);
  await expect(detailCell(page, 'MEMO')).toHaveText(value);
}

test('明细：admin 把 2550 原料/辅料第一行的备注改为"测试"，刷新后显示"测试"，再改回原值', async ({ page }) => {
  await login(page);
  await openDocument(page);
  await scrollTo(materialGrid(page), detailCell(page, 'MEMO'));
  const original = ((await detailCell(page, 'MEMO').textContent()) ?? '').trim();
  expect(original).not.toBe('测试');

  await editMemo(page, '测试');

  await page.reload();
  await openDocument(page);
  await scrollTo(materialGrid(page), detailCell(page, 'MEMO'));
  await expect(detailCell(page, 'MEMO')).toHaveText('测试');

  await editMemo(page, original);

  await page.reload();
  await openDocument(page);
  await scrollTo(materialGrid(page), detailCell(page, 'MEMO'));
  await expect(detailCell(page, 'MEMO')).toHaveText(original);
});

test('明细：admin 勾选 2550 原料/辅料第一行的"客户指定"并保存，刷新后仍勾选，再取消', async ({ page }) => {
  await login(page);
  await openDocument(page);
  const checkbox = detailCell(page, 'CUSTOMER_SPECIFIED').locator('input[type="checkbox"]');
  await expect(checkbox).not.toBeChecked();

  await checkbox.click();
  await saveAndWait(page);
  await expect(checkbox).toBeChecked();

  await page.reload();
  await openDocument(page);
  await expect(checkbox).toBeChecked();

  await checkbox.click();
  await saveAndWait(page);

  await page.reload();
  await openDocument(page);
  await expect(checkbox).not.toBeChecked();
});
