// 主线程客户端：createCalcWorkerClient(wasmUrl) 返回 C11 的 CalcWorkerClient（C07 第 5 节）。
// 同一规则包版本（packId + version）只加载一次（RC-03）。

export function createCalcWorkerClient(wasmUrl) {
  const worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' })
  worker.postMessage({ type: 'init', wasmUrl: new URL(wasmUrl, globalThis.location?.href).href })
  const pending = new Map()
  const loaded = new Map()
  let nextId = 1

  worker.onmessage = ({ data: msg }) => {
    const waiter = pending.get(msg.id)
    if (!waiter) return
    pending.delete(msg.id)
    if (msg.ok) waiter.resolve(msg)
    else waiter.reject(Object.assign(new Error(msg.error.message), { code: msg.error.code }))
  }
  worker.onerror = (event) => {
    for (const waiter of pending.values()) waiter.reject(Object.assign(new Error(event.message || 'Worker 出错'), { code: 'EVAL_FAILED' }))
    pending.clear()
  }

  function send(msg) {
    const id = nextId++
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject })
      worker.postMessage({ id, ...msg })
    })
  }

  return {
    /** pack：{packId, version, bytes}，bytes 为规则包 JSON 的 UTF-8 字节；返回句柄。 */
    load(pack) {
      const key = `${pack.packId}@${pack.version}`
      if (!loaded.has(key)) {
        const bytes = pack.bytes instanceof ArrayBuffer ? pack.bytes.slice(0) : new Uint8Array(pack.bytes).buffer.slice(0)
        const handle = send({ type: 'load', packId: pack.packId, version: pack.version, bytes }).then((msg) => msg.handle)
        handle.catch(() => loaded.delete(key))
        loaded.set(key, handle)
      }
      return loaded.get(key)
    },
    /** request：C07 第 2 节的 JSON 文本；返回第 3 节的 JSON 文本。 */
    evaluate(handle, request) {
      return send({ type: 'evaluate', handle, request }).then((msg) => msg.result)
    },
    dispose(handle) {
      for (const [key, value] of loaded) {
        value.then((h) => { if (h === handle) loaded.delete(key) }, () => {})
      }
      worker.postMessage({ type: 'dispose', handle })
    },
    terminate() {
      worker.terminate()
    },
  }
}
