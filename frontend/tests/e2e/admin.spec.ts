/**
 * 系统管理（只读）：admin 从左侧菜单打开"系统管理"，各功能用页签显示；人员管理、部门管理的表格占满页签下方的高度，
 * 能看到数据（2026-10-29 修复前表格只有 2px 高，什么都看不到）。
 * 左侧菜单默认收起、是盖在页面上的抽屉（与旧系统相同）：先点顶栏左上角的按钮展开，点完菜单项点遮罩收起（openMenu）。
 */
import { type Page, expect, openMenu, test } from './support';

/** 当前页签里的表格：高度和所在的页签内容区 */
async function visibleGrid(page: Page) {
  const pane = page.locator('.admin-tabs__pane').filter({ visible: true }).first();
  const grid = pane.locator('.ag-root-wrapper');
  await expect(grid).toBeVisible();
  const box = await grid.boundingBox();
  return { pane, height: box?.height ?? 0 };
}

test('系统管理：人员管理、部门管理的表格占满页签高度，能看到 admin 账号和部门列表', async ({ page }) => {
  await page.goto('/home');
  await openMenu(page, '系统管理');
  await page.waitForURL('**/admin');

  const accounts = await visibleGrid(page);
  expect(accounts.height).toBeGreaterThan(400);
  await expect(accounts.pane.locator('.ag-center-cols-container .ag-row', { hasText: 'admin' }).first()).toBeVisible();

  await page.locator('.admin-tabs .n-tabs-tab', { hasText: '部门管理' }).click();
  await expect(page.locator('.admin-tabs__pane').filter({ visible: true })).toHaveCount(1);
  const departments = await visibleGrid(page);
  expect(departments.height).toBeGreaterThan(400);
  await expect(departments.pane.locator('.ag-header-cell', { hasText: '部门名称' })).toBeVisible();
});
