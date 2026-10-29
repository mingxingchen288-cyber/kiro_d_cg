/**
 * 计算客户端（C07 第 5 节，C11 `ShellApi.calc`）：rules-core 交付的 `createCalcWorkerClient`，第一次使用时才创建 Worker。
 * `rules-core/dist/web/` 是 rules-core 的构建产物、不入库（先运行 tools/build-rules-core.ps1）。构建时 Vite 按
 * `new URL(..., import.meta.url)` 把 Worker（worker.js 连同 index.js）和 rules_core.wasm 打进前端产物 dist/assets；
 * 开发服务器在 vite.config.ts 中放行这个目录，并带 rules-core 要求的 COOP、COEP 响应头（AS-06）。
 */
import type { CalcWorkerClient } from '@/contracts/rules';
import { createCalcWorkerClient } from '../../../rules-core/dist/web/client.js';

const WASM_URL = new URL('../../../rules-core/dist/web/rules_core.wasm', import.meta.url).href;

export function createLazyCalc(): CalcWorkerClient {
  let client: CalcWorkerClient | null = null;
  const get = () => {
    client ??= createCalcWorkerClient(WASM_URL);
    return client;
  };
  return {
    load: pack => get().load(pack),
    evaluate: (handle, request) => get().evaluate(handle, request),
    dispose: handle => client?.dispose(handle),
    terminate: () => client?.terminate()
  };
}
