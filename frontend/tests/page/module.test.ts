/**
 * C11 契约测试（frontend-page 部分）：用 ShellApi 的模拟实现装载模块，路由 `/page/:pageCode` 注册成功，install 只依赖 ShellApi。
 */
import { describe, expect, it } from 'vitest';
import { createFakeShell } from '../../src/contracts/fakes/shell';
import { isPageModuleInstalled, pageModule, usePageShell } from '../../src/modules/page';

describe('frontend-page 模块装载（C11）', () => {
  it('导出 FrontendModule：名称 page，路由 /page/:pageCode，页面编码来自路由参数', () => {
    expect(pageModule.name).toBe('page');
    expect(pageModule.routes.map(r => [r.path, r.name, r.props])).toEqual([['/page/:pageCode', 'page', true]]);
  });

  it('install 只接收 ShellApi，之后页面经它调用接口', () => {
    const { shell } = createFakeShell();
    expect(isPageModuleInstalled()).toBe(false);
    pageModule.install(shell);
    expect(isPageModuleInstalled()).toBe(true);
    expect(usePageShell()).toBe(shell);
  });
});
