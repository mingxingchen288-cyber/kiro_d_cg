/** rules-core 的 WASM ES 模块（C07 第 5 节）。 */
export function init(wasmUrl: string): Promise<void>
/** 返回句柄；规则包不合法时抛出带 code 的错误（PACK_INVALID）。 */
export function loadPack(bytes: Uint8Array): number
export function evaluate(handle: number, request: string): string
export function dispose(handle: number): void
export function coreVersion(): string
export function compileCount(): number
/** 按 C01 第 3 节比较两段 JSON 文本，返回不一致的位置；空数组表示一致。 */
export function compareJson(a: string, b: string): string[]
