/**
 * 计算客户端（C07 第 5 节，C11 `ShellApi.calc`）：rules-core 交付的 `createCalcWorkerClient`，第一次使用时才创建 Worker。
 * rules-core 说明页面要带 COOP、COEP 响应头，由 assembly 配置开发服务器和生产环境（AS-06）；
 * `rules-core/dist/web/` 是构建产物、不入库，由 assembly 按 rules-core 模块说明第 6 节放进前端工程后改这里的路径。
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
