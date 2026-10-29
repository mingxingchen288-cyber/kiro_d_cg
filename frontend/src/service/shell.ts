/**
 * 过渡 ShellApi 的旧入口，已由外壳的正式 ShellApi（src/modules/shell/app.ts，T-FS-2）代替。
 *
 * 只因为 `src/views/page/[pageCode].vue` 还在导入 `interimShell` 而保留，返回的就是正式的 ShellApi。
 * 外壳启动时已按 C11 注册 frontend-page，`/page/:pageCode` 由该模块的路由打开，那个视图文件运行时不再使用；
 * 删除它之后（不在 frontend-shell 的范围内），本文件一并删除。
 */
import type { ShellApi } from '@/contracts/shell';
import { shellRuntime } from '@/modules/shell/app';

export function interimShell(): ShellApi {
  return shellRuntime().api;
}
