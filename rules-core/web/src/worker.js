// rules-core 的计算 Worker（C07 第 5 节）。消息：
//   {type: 'init', wasmUrl}                              由 createCalcWorkerClient 在创建后先发，rules-core 内部使用
//   {id, type: 'load', packId, version, bytes}        → {id, ok: true, handle}
//   {id, type: 'evaluate', handle, request}           → {id, ok: true, result}
//   {type: 'dispose', handle}
// 出错时返回 {id, ok: false, error: {code, message}}。
import { dispose, evaluate, init, loadPack } from './index.js'

let ready = null

self.onmessage = async ({ data: msg }) => {
  if (msg.type === 'init') {
    ready = init(msg.wasmUrl)
    return
  }
  try {
    await ready
  } catch (e) {
    if (msg.id !== undefined) self.postMessage({ id: msg.id, ok: false, error: { code: 'EVAL_FAILED', message: `WASM 加载失败：${e.message}` } })
    return
  }
  try {
    if (msg.type === 'load') {
      self.postMessage({ id: msg.id, ok: true, handle: loadPack(new Uint8Array(msg.bytes)) })
    } else if (msg.type === 'evaluate') {
      self.postMessage({ id: msg.id, ok: true, result: evaluate(msg.handle, msg.request) })
    } else if (msg.type === 'dispose') {
      dispose(msg.handle)
    }
  } catch (e) {
    const error = e.code ? { code: e.code, message: e.message } : { code: 'EVAL_FAILED', message: '求值出错' }
    if (msg.id !== undefined) self.postMessage({ id: msg.id, ok: false, error })
  }
}
