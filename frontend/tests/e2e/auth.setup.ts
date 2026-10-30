/**
 * setup 项目：每个账号从登录页登录一次，存登录状态，用例直接用（不再每条用例走一遍登录）。
 * Cookie 存在 storageState 文件；外壳的会话（CSRF 令牌和角色列表）在 sessionStorage，storageState 不存它，另存一份
 * （support.ts 的 restoreSession 在页面脚本运行前写回）。
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { test as setup } from '@playwright/test';
import { USERS, type UserName, authFile, login, sessionFile } from './support';

for (const user of Object.keys(USERS) as UserName[]) {
  setup(`登录 ${user}`, async ({ page }) => {
    await login(page, USERS[user]);
    mkdirSync(dirname(authFile(user)), { recursive: true });
    await page.context().storageState({ path: authFile(user) });
    const session = await page.evaluate(() =>
      Object.fromEntries(
        Object.keys(sessionStorage)
          .filter(key => key.endsWith('shell-session'))
          .map(key => [key, sessionStorage.getItem(key) ?? ''])
      )
    );
    writeFileSync(sessionFile(user), JSON.stringify(session));
  });
}
