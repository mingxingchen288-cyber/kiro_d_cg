/**
 * 计算 Worker 的模拟实现（C07 第 5 节、C11 的 `ShellApi.calc`）：不运行 rules-core，按预设给出求值结果。
 * 默认结果是 C07 第 3 节的样例；测试用 `respond` 按请求计算结果，用 `fail` 预设错误。
 */
import type { CalcPack, CalcWorkerClient, EvaluationRequest, EvaluationResult, RulesPack } from '../rules';
import { evaluationResultSample } from './samples';

export type CalcResponder = (request: EvaluationRequest, pack: RulesPack) => EvaluationResult;

export class FakeCalc implements CalcWorkerClient {
  /** 加载过的规则包，按 `packId@version` */
  readonly packs = new Map<string, RulesPack>();
  /** 收到的求值请求（已从 JSON 文本解析） */
  readonly requests: EvaluationRequest[] = [];
  readonly disposed: number[] = [];
  terminated = false;
  private readonly handles = new Map<number, string>();
  private nextHandle = 1;
  private responder: CalcResponder = () => structuredClone(evaluationResultSample);
  private pendingError: (Error & { code: string }) | null = null;

  respond(responder: CalcResponder) {
    this.responder = responder;
    return this;
  }

  /** 下一次 evaluate 以该错误拒绝 */
  fail(code: string, message: string) {
    this.pendingError = Object.assign(new Error(message), { code });
    return this;
  }

  async load(pack: CalcPack) {
    const key = `${pack.packId}@${pack.version}`;
    const existing = [...this.handles].find(([, k]) => k === key);
    if (existing) return existing[0];
    const bytes = pack.bytes instanceof Uint8Array ? pack.bytes : new Uint8Array(pack.bytes);
    this.packs.set(key, JSON.parse(new TextDecoder().decode(bytes)) as RulesPack);
    const handle = this.nextHandle++;
    this.handles.set(handle, key);
    return handle;
  }

  async evaluate(handle: number, request: string) {
    const key = this.handles.get(handle);
    if (!key) throw Object.assign(new Error(`没有句柄 ${handle}`), { code: 'EVAL_FAILED' });
    if (this.pendingError) {
      const error = this.pendingError;
      this.pendingError = null;
      throw error;
    }
    const parsed = JSON.parse(request) as EvaluationRequest;
    this.requests.push(parsed);
    return JSON.stringify(this.responder(parsed, this.packs.get(key)!));
  }

  dispose(handle: number) {
    this.disposed.push(handle);
    this.handles.delete(handle);
  }

  terminate() {
    this.terminated = true;
  }
}

export function createFakeCalc() {
  return new FakeCalc();
}
