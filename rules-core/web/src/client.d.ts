/** C11 ShellApi.calc：按 C07 第 5 节经 Worker 调用 rules-core 的 WASM。 */
export interface CalcPack {
  packId: string
  version: number
  /** 规则包（C07 第 1 节）JSON 的 UTF-8 字节 */
  bytes: ArrayBuffer | Uint8Array
}

export interface CalcError extends Error {
  /** PACK_INVALID、INPUT_INVALID 或 EVAL_FAILED */
  code: string
}

export interface CalcWorkerClient {
  /** 加载规则包，同一 packId + version 只加载一次；不合法时以 CalcError（PACK_INVALID）拒绝。 */
  load(pack: CalcPack): Promise<number>
  /** request 为 C07 第 2 节的 JSON 文本，结果为第 3 节的 JSON 文本。 */
  evaluate(handle: number, request: string): Promise<string>
  dispose(handle: number): void
  terminate(): void
}

export function createCalcWorkerClient(wasmUrl: string | URL): CalcWorkerClient
