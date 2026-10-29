/**
 * 找出 `src/modules/<模块>/index.ts` 导出的 FrontendModule（C11）。模块像插件一样放进 `src/modules/` 就会被注册，
 * 外壳不导入具体模块；还没有建好的模块不影响外壳和其他模块。
 */
import type { FrontendModule } from '../../contracts/shell';
import { pickModules } from './registry';

export function discoverModules(): FrontendModule[] {
  const loaded = import.meta.glob<Record<string, unknown>>(['../*/index.ts', '!../shell/**'], { eager: true });
  return pickModules(loaded);
}
