// rules-core 的 WASM ES 模块（C07 第 5 节）：内含 WASI 适配，Worker 内部调用；在主线程也能直接用。
// 只做 JSON 文本进出（RC-01），业务逻辑都在 WASM 中。

const encoder = new TextEncoder()
const decoder = new TextDecoder()
let wasm = null

const ERRNO_SUCCESS = 0
const ERRNO_BADF = 8
const ERRNO_NOSYS = 52

/** 最小的 wasi_snapshot_preview1：内核不读写文件，只用到时钟、随机数、标准输出（panic 信息）和环境变量。 */
function wasiImports(memory) {
  const view = () => new DataView(memory().buffer)
  const bytes = () => new Uint8Array(memory().buffer)
  const lines = { 1: '', 2: '' }
  return {
    args_sizes_get(argc, size) { view().setUint32(argc, 0, true); view().setUint32(size, 0, true); return ERRNO_SUCCESS },
    args_get() { return ERRNO_SUCCESS },
    environ_sizes_get(count, size) { view().setUint32(count, 0, true); view().setUint32(size, 0, true); return ERRNO_SUCCESS },
    environ_get() { return ERRNO_SUCCESS },
    clock_res_get(_id, out) { view().setBigUint64(out, 1000n, true); return ERRNO_SUCCESS },
    clock_time_get(id, _precision, out) {
      const ns = id === 0 ? BigInt(Date.now()) * 1000000n : BigInt(Math.round(performance.now() * 1e6))
      view().setBigUint64(out, ns, true)
      return ERRNO_SUCCESS
    },
    random_get(ptr, len) {
      for (let off = 0; off < len; off += 65536) {
        crypto.getRandomValues(bytes().subarray(ptr + off, ptr + Math.min(len, off + 65536)))
      }
      return ERRNO_SUCCESS
    },
    fd_write(fd, iovs, iovsLen, written) {
      let total = 0
      for (let i = 0; i < iovsLen; i++) {
        const ptr = view().getUint32(iovs + i * 8, true)
        const len = view().getUint32(iovs + i * 8 + 4, true)
        if (fd === 1 || fd === 2) lines[fd] += decoder.decode(bytes().slice(ptr, ptr + len))
        total += len
      }
      for (const f of [1, 2]) {
        const parts = lines[f].split('\n')
        lines[f] = parts.pop()
        for (const line of parts) (f === 1 ? console.log : console.error)(`[rules-core] ${line}`)
      }
      view().setUint32(written, total, true)
      return ERRNO_SUCCESS
    },
    fd_fdstat_get(fd, out) {
      if (fd > 2) return ERRNO_BADF
      new Uint8Array(memory().buffer, out, 24).fill(0)
      view().setUint8(out, 2) // 字符设备
      return ERRNO_SUCCESS
    },
    fd_prestat_get() { return ERRNO_BADF },
    fd_prestat_dir_name() { return ERRNO_BADF },
    fd_close() { return ERRNO_SUCCESS },
    sched_yield() { return ERRNO_SUCCESS },
    proc_exit(code) { throw new Error(`rules-core 退出（${code}）`) },
  }
}

/** 加载 WASM：wasmUrl 为 rules_core.wasm 的地址。 */
export async function init(wasmUrl) {
  const response = await fetch(wasmUrl)
  if (!response.ok) throw new Error(`读取 ${wasmUrl} 失败：HTTP ${response.status}`)
  const module = await WebAssembly.compile(await response.arrayBuffer())
  let instance = null
  const wasi = wasiImports(() => instance.exports.memory)
  const imports = {}
  for (const imp of WebAssembly.Module.imports(module)) {
    if (imp.kind !== 'function') continue
    imports[imp.module] ??= {}
    imports[imp.module][imp.name] = (imp.module === 'wasi_snapshot_preview1' && wasi[imp.name]) || (() => ERRNO_NOSYS)
  }
  instance = await WebAssembly.instantiate(module, imports)
  instance.exports._initialize?.()
  wasm = instance.exports
}

function output() {
  const ptr = wasm.rc_out_ptr() >>> 0
  const len = wasm.rc_out_len() >>> 0
  return decoder.decode(new Uint8Array(wasm.memory.buffer, ptr, len).slice())
}

/** 把若干段字节写进 WASM 内存，调用 fn(ptr1, len1, ptr2, len2, …)，再释放。 */
function withInputs(chunks, fn) {
  const allocated = chunks.map((chunk) => {
    const ptr = wasm.rc_alloc(chunk.length) >>> 0
    new Uint8Array(wasm.memory.buffer, ptr, chunk.length).set(chunk)
    return [ptr, chunk.length]
  })
  try {
    return fn(...allocated.flat())
  } finally {
    for (const [ptr, len] of allocated) wasm.rc_free(ptr, len)
  }
}

/** C07 load_pack：返回句柄；规则包不合法时抛出带 code（PACK_INVALID）的错误。 */
export function loadPack(bytes) {
  const handle = withInputs([bytes], (p, l) => wasm.rc_load_pack(p, l)) >>> 0
  if (handle === 0) {
    const { error } = JSON.parse(output())
    throw Object.assign(new Error(error.message), { code: error.code })
  }
  return handle
}

/** C07 evaluate：request 为第 2 节的 JSON 文本，返回第 3 节的 JSON 文本。 */
export function evaluate(handle, request) {
  withInputs([encoder.encode(request)], (p, l) => wasm.rc_evaluate(handle, p, l))
  return output()
}

export function dispose(handle) {
  wasm.rc_dispose(handle)
}

export function coreVersion() {
  wasm.rc_core_version()
  return output()
}

/** 已编译的规则包个数（检查重复求值不重新编译，RC-03）。 */
export function compileCount() {
  return Number(wasm.rc_compile_count())
}

/** 按 C01 第 3 节比较两段 JSON 文本，返回不一致的位置；空数组表示一致。 */
export function compareJson(a, b) {
  withInputs([encoder.encode(a), encoder.encode(b)], (ap, al, bp, bl) => wasm.rc_compare_json(ap, al, bp, bl))
  return JSON.parse(output())
}
