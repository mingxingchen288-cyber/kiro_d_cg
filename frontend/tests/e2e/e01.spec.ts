/**
 * T-AS-9 业务例子 E01（真实联调，浏览器 → 后端 → d_cg）：admin 在成本核算页把单据 200680 主表的 MEMO 改为"测试"并保存；
 * 重新打开页面显示"测试"；再改回原值保存。数据库中的值由 backend/tests/e2e/test_e01.py 和运行后的只读查询核对。
 */
import { type Page, expect, test } from '@playwright/test';

const DOCID = '200680';

function memoCell(page: Page) {
  return page.locator(`.ag-center-cols-container .ag-row[row-id="${DOCID}"] [col-id="MEMO"]`);
}

/** 打开成本核算页，按 ID 降序（服务端排序），把备注列横向滚进视野 */
async function openCostPage(page: Page) {
  await page.goto('/cost-pinggu');
  const idHeader = page.locator('.ag-pinned-left-header .ag-header-cell');
  await idHeader.locator('.ag-header-cell-label').click();
  await expect(idHeader).toHaveAttribute('aria-sort', 'ascending');
  await idHeader.locator('.ag-header-cell-label').click();
  await expect(idHeader).toHaveAttribute('aria-sort', 'descending');
  await expect(page.locator(`.ag-pinned-left-cols-container .ag-row[row-id="${DOCID}"]`)).toBeVisible();
  // AG Grid 只渲染视野内的列：像用户拖动横向滚动条一样，逐段向右滚到备注列出现
  await page.locator('.ag-body-horizontal-scroll-viewport').evaluate(async (el, docid) => {
    const selector = `.ag-center-cols-container .ag-row[row-id="${docid}"] [col-id="MEMO"]`;
    for (let left = 0; left < 20_000 && !document.querySelector(selector); left += 500) {
      el.scrollLeft = left;
      // eslint-disable-next-line no-await-in-loop
      await new Promise(resolve => {
        setTimeout(resolve, 100);
      });
    }
  }, DOCID);
  await expect(memoCell(page)).toBeVisible();
}

async function editMemo(page: Page, value: string) {
  await memoCell(page).dblclick();
  await page.keyboard.press('Control+A');
  if (value) {
    await page.keyboard.type(value);
  } else {
    await page.keyboard.press('Backspace');
  }
  await page.keyboard.press('Enter');
  await expect(page.getByText('1 行未保存')).toBeVisible();
  await page.getByRole('button', { name: '保存' }).click();
  await expect(page.getByText('已保存')).toBeVisible();
  await expect(memoCell(page)).toHaveText(value);
}

test('E01：admin 把 200680 的备注改为"测试"，重新打开显示"测试"，再改回原值', async ({ page }) => {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill('admin');
  await page.getByPlaceholder('请输入密码').fill('admin123..');
  await page.getByRole('button', { name: '确认' }).click();
  await page.waitForURL('**/home');

  await openCostPage(page);
  const original = ((await memoCell(page).textContent()) ?? '').trim();
  expect(original).not.toBe('测试');

  await editMemo(page, '测试');

  await page.reload();
  await openCostPage(page);
  await expect(memoCell(page)).toHaveText('测试');

  await editMemo(page, original);

  await page.reload();
  await openCostPage(page);
  await expect(memoCell(page)).toHaveText(original);
});
