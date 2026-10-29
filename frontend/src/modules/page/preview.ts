/**
 * 本地预览（FP-05）：编辑后按 C07 第 2 节组装一张单据的 preview 阶段求值请求，经 `ShellApi.calc`（rules-core 的
 * 计算 Worker）求值。请求中的 `old` 取编辑缓冲中的已提交值（从后端加载到的值）。结果只用于显示。
 */
import type { FieldValues } from '../../contracts/command';
import type { CurrentUser, RoleRef } from '../../contracts/http';
import type { PageView } from '../../contracts/page-view';
import {
  type CalcWorkerClient,
  type ChangedRow,
  type EvalRow,
  type EvaluationRequest,
  EvaluationResult,
  type RulesPack
} from '../../contracts/rules';
import { localDate } from './fields';
import type { PageModel } from './view-model';

interface RowPlan {
  row: EvalRow;
  changed: ChangedRow | null;
}

function rowPlan(model: PageModel, entity: string, id: string): RowPlan {
  const buffer = model.buffer;
  const values = buffer.current(entity, id) ?? {};
  const identity = buffer.isNew(entity, id) ? { clientRowId: id } : { rowKey: id };
  if (buffer.isNew(entity, id)) {
    return { row: { ...identity, values }, changed: { entity, ...identity, op: 'add', fields: Object.keys(values) } };
  }
  if (buffer.isDeleted(entity, id)) {
    return { row: { ...identity, values }, changed: { entity, ...identity, op: 'delete', fields: [] } };
  }
  const fields = buffer.changedFields(entity, id);
  if (!fields.length) return { row: { ...identity, values }, changed: null };
  const committed = buffer.committed(entity, id) ?? {};
  const old: FieldValues = Object.fromEntries(fields.map(f => [f, committed[f] ?? null]));
  return { row: { ...identity, values, old }, changed: { entity, ...identity, op: 'modify', fields } };
}

export interface PreviewContext {
  user: CurrentUser | null;
  role: RoleRef | null;
  now: Date;
}

/** 一张单据（主表行及已加载的明细）的 preview 求值请求 */
export function buildPreviewRequest(model: PageModel, recordId: string, ctx: PreviewContext): EvaluationRequest {
  const view: PageView = model.view;
  const master = rowPlan(model, view.master.entity, recordId);
  const changed: ChangedRow[] = master.changed ? [master.changed] : [];
  const details: Record<string, EvalRow[]> = {};
  for (const detail of view.details) {
    details[detail.entity] = model.detailIds(detail.entity, recordId).map(id => {
      const plan = rowPlan(model, detail.entity, id);
      if (plan.changed) changed.push(plan.changed);
      return plan.row;
    });
  }
  return {
    purpose: 'operation',
    operation: view.saveOperation,
    page: view.pageCode,
    phase: 'preview',
    context: {
      userId: ctx.user?.userId ?? '0',
      departmentId: ctx.user?.departmentId ?? null,
      role: ctx.role?.code ?? '',
      today: localDate(ctx.now),
      origin: 'user'
    },
    document: { entity: view.master.entity, master: master.row, details },
    changed,
    data: {}
  };
}

/** Worker 多久没有响应算不可用（毫秒） */
const WORKER_TIMEOUT = 15_000;

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('计算 Worker 没有响应')), ms);
    promise.then(
      value => {
        clearTimeout(timer);
        resolve(value);
      },
      error => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

/**
 * 规则包按（packId、version）只下载和加载一次。规则包或 Worker 加载失败后，这个规则包版本不再重试（页面照常编辑和保存，
 * 只是没有本地预览），配置变更换了规则包版本时再试。
 */
export class PreviewEngine {
  private handle: Promise<number> | null = null;
  private loadedKey = '';
  private unavailable: Error | null = null;

  constructor(
    private readonly calc: CalcWorkerClient,
    private readonly fetchPack: (packId: string, version: number) => Promise<RulesPack>
  ) {}

  private ensure(view: PageView) {
    const key = `${view.rulesPack.packId}@${view.rulesPack.version}`;
    if (this.loadedKey !== key) {
      this.loadedKey = key;
      this.unavailable = null;
      this.handle = null;
    }
    if (this.unavailable) return Promise.reject(this.unavailable);
    if (!this.handle) {
      this.handle = this.fetchPack(view.rulesPack.packId, view.rulesPack.version).then(pack =>
        withTimeout(
          this.calc.load({
            packId: view.rulesPack.packId,
            version: view.rulesPack.version,
            bytes: new TextEncoder().encode(JSON.stringify(pack))
          }),
          WORKER_TIMEOUT
        )
      );
      this.handle.catch(error => {
        this.unavailable = error instanceof Error ? error : new Error(String(error));
      });
    }
    return this.handle;
  }

  async evaluate(view: PageView, request: EvaluationRequest): Promise<EvaluationResult> {
    const handle = await this.ensure(view);
    const text = await withTimeout(this.calc.evaluate(handle, JSON.stringify(request)), WORKER_TIMEOUT);
    return EvaluationResult.parse(JSON.parse(text));
  }
}
