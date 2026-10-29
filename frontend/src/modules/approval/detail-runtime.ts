/**
 * 审批详情的行为（FA-01、FA-03、FA-04、FA-07、FA-08）：读取详情、勾选和重算（preview）、通过、驳回、撤回。
 * 不引用 Vue 组件和 AG Grid；界面状态放在 `state`、`detail`、`view`、`checked`，组件直接绑定。
 *
 * 对照旧系统 `ApprovalDetailDialog.vue`：load、validateDecision、decisionPayload、submit；提示文字沿用旧系统。
 * 与旧系统不同的：勾选按修改表的主键（`ref.key`），改了勾选立即用 preview 重算"改前 → 改后"（C09 v9）；
 * 一张单据的几个审批流合在一个审批里，只有一个"通过"（FA-07）。
 */
import { reactive, ref, shallowRef } from 'vue';
import type { PlatformApi } from '../../contracts/api';
import type { CommandResult } from '../../contracts/command';
import { PlatformError } from '../../contracts/errors';
import type { ApprovalDetail, PassRequest, WithdrawRequest } from '../../contracts/http';
import type { ShellApi } from '../../contracts/shell';
import { notifyApprovalProcessed } from './events';
import { type ApprovalView, type ViewAffectedTable, errorText, flowNameMap, gridRows } from './view-model';

/** 人工参数的值：字符串、数值（输入框给出数字，提交时转成十进制文本，C01 第 2 节）、是非、日期（YYYY-MM-DD） */
export type ParamValue = string | number | boolean | null;

type FlowParam = ApprovalDetail['params'][number];
type CheckedRow = NonNullable<PassRequest['checkedRows']>[number];

export interface DetailDeps {
  api: PlatformApi;
  message: ShellApi['message'];
  /** 新的请求键（C01 第 5 节：每次提交新生成的小写 UUID） */
  newRequestKey?: () => string;
}

/** 受影响单据一块的勾选情况 */
interface Selection {
  flow: string;
  block: string;
  editable: boolean;
  /** 这一块的主键，按行的顺序（不含记录已不存在的行） */
  keys: string[];
  missing: number;
  /** 不能改的主键：块不能改勾选时为全部；能改时为打开详情时已取消的（上一级取消的，不能再勾回，AP-07） */
  locked: Set<string>;
}

const blockId = (flow: string, block: string) => `${flow}\u0000${block}`;

const isEmpty = (value: ParamValue | undefined) => value === null || value === undefined || String(value).trim() === '';

function defaultParam(param: FlowParam): ParamValue {
  const value = param.value;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value;
  return param.type === 'boolean' ? false : null;
}

export class ApprovalDetailRuntime {
  readonly detail = shallowRef<ApprovalDetail | null>(null);
  /** 当前显示的修改内容：打开详情时为详情的 view，改了勾选后为 preview 返回的 view */
  readonly view = shallowRef<ApprovalView | null>(null);
  /** 最近一次详情或 preview 返回的结果指纹，通过时带上 */
  readonly fingerprint = ref('');
  /** 当前勾选：块 → 勾选的主键 */
  readonly checked = shallowRef<Record<string, readonly string[]>>({});
  readonly state = reactive({
    loading: false,
    previewing: false,
    submitting: false,
    /** 读取详情或处理失败时的错误（同旧系统的 errorText，显示在顶部，可以重新读取详情） */
    error: '',
    /** 通过时收到 409 RECONFIRM_REQUIRED，已重新读取详情，请审批人再次确认（FA-03） */
    reconfirm: false,
    comment: '',
    params: {} as Record<string, ParamValue>
  });

  private selections = new Map<string, Selection>();
  private loadSeq = 0;
  private previewSeq = 0;
  private readonly newRequestKey: () => string;

  constructor(
    readonly approvalId: string,
    private readonly deps: DetailDeps
  ) {
    this.newRequestKey = deps.newRequestKey ?? (() => crypto.randomUUID());
  }

  get busy() {
    return this.state.loading || this.state.previewing || this.state.submitting;
  }

  /** 审批流编码 → 名称（"触发审批"列） */
  flowNames() {
    return flowNameMap(this.detail.value?.steps ?? []);
  }

  // ================================================================ 读取

  async load() {
    const seq = ++this.loadSeq;
    this.state.loading = true;
    this.state.error = '';
    try {
      const detail = await this.deps.api.approvalDetail(this.approvalId);
      if (seq === this.loadSeq) this.apply(detail);
    } catch (error) {
      if (seq === this.loadSeq) this.state.error = errorText(error);
    } finally {
      if (seq === this.loadSeq) this.state.loading = false;
    }
  }

  private apply(detail: ApprovalDetail) {
    // 还没返回的 preview 作废：详情是重新读取的结果
    this.previewSeq += 1;
    this.state.previewing = false;
    this.detail.value = detail;
    this.view.value = detail.view;
    this.fingerprint.value = detail.fingerprint;
    const selections = new Map<string, Selection>();
    const checked: Record<string, string[]> = {};
    for (const block of detail.view.affected) {
      const rows = gridRows(block.rows);
      const keys: string[] = [];
      const on: string[] = [];
      block.rows.forEach((row, index) => {
        const key = rows[index].lead ? rows[index].key : null;
        if (!key) return;
        keys.push(key);
        if (row.checked) on.push(key);
      });
      const locked = new Set(block.editable ? keys.filter(k => !on.includes(k)) : keys);
      const id = blockId(block.flow, block.key);
      selections.set(id, {
        flow: block.flow,
        block: block.key,
        editable: block.editable,
        keys,
        missing: rows.filter(r => r.missing).length,
        locked
      });
      checked[id] = on;
    }
    this.selections = selections;
    this.checked.value = checked;
    // 人工参数：保留已经填写的（重新读取详情时），其余取默认
    const params: Record<string, ParamValue> = {};
    for (const param of detail.params) {
      params[param.name] = param.name in this.state.params ? this.state.params[param.name] : defaultParam(param);
    }
    this.state.params = params;
  }

  // ================================================================ 勾选（FA-01、FA-09）

  isChecked(block: Pick<ViewAffectedTable, 'flow' | 'key'>, key: string) {
    return this.checkedKeys(block).includes(key);
  }

  /** 这一块当前勾选的主键 */
  checkedKeys(block: Pick<ViewAffectedTable, 'flow' | 'key'>): readonly string[] {
    return this.checked.value[blockId(block.flow, block.key)] ?? [];
  }

  /** 块能改勾选（`editable`）、当前用户能通过，而且不是上一级取消的行 */
  canToggle(block: Pick<ViewAffectedTable, 'flow' | 'key'>, key: string) {
    const selection = this.selections.get(blockId(block.flow, block.key));
    const detail = this.detail.value;
    if (!selection || !detail) return false;
    return (
      selection.editable &&
      detail.status === 'pending' &&
      detail.actions.canPass &&
      selection.keys.includes(key) &&
      !selection.locked.has(key)
    );
  }

  /** 能改勾选的主键（表头全选的范围，不含记录已不存在的行） */
  selectableKeys(block: Pick<ViewAffectedTable, 'flow' | 'key'>) {
    const selection = this.selections.get(blockId(block.flow, block.key));
    return selection ? selection.keys.filter(key => this.canToggle(block, key)) : [];
  }

  /** 块标题后的条数：修改表的记录数（主键数），加上记录已不存在的行 */
  groupCount(block: Pick<ViewAffectedTable, 'flow' | 'key'>) {
    const selection = this.selections.get(blockId(block.flow, block.key));
    return selection ? selection.keys.length + selection.missing : 0;
  }

  /** 能改勾选的各块中：已勾选几条 / 能勾选几条（同旧系统"已勾选 x / y"） */
  selectionCount() {
    let checked = 0;
    let total = 0;
    for (const selection of this.selections.values()) {
      const target = { flow: selection.flow, key: selection.block };
      const keys = this.selectableKeys(target);
      total += keys.length;
      checked += keys.filter(key => this.isChecked(target, key)).length;
    }
    return { checked, total };
  }

  async toggle(block: Pick<ViewAffectedTable, 'flow' | 'key'>, key: string, value: boolean) {
    if (!this.canToggle(block, key)) return;
    const id = blockId(block.flow, block.key);
    const current = new Set(this.checked.value[id] ?? []);
    if (value) current.add(key);
    else current.delete(key);
    this.setChecked(id, current);
    await this.preview();
  }

  async toggleAll(block: Pick<ViewAffectedTable, 'flow' | 'key'>, value: boolean) {
    const keys = this.selectableKeys(block);
    if (!keys.length) return;
    const id = blockId(block.flow, block.key);
    const current = new Set(this.checked.value[id] ?? []);
    for (const key of keys) {
      if (value) current.add(key);
      else current.delete(key);
    }
    this.setChecked(id, current);
    await this.preview();
  }

  private setChecked(id: string, keys: Set<string>) {
    const selection = this.selections.get(id)!;
    this.checked.value = { ...this.checked.value, [id]: selection.keys.filter(key => keys.has(key)) };
  }

  /** 能改勾选的各块中勾选的行（C09 第 6 节：不能改勾选的块不用提交） */
  checkedRows(): CheckedRow[] {
    const rows: CheckedRow[] = [];
    for (const [id, selection] of this.selections) {
      if (!selection.editable) continue;
      for (const key of this.checked.value[id] ?? []) rows.push({ flow: selection.flow, block: selection.block, key });
    }
    return rows;
  }

  /** 用 preview 提交当前的勾选，按返回的 view 刷新"改前 → 改后"，保存返回的指纹；只用最后一次的结果 */
  private async preview() {
    const seq = ++this.previewSeq;
    this.state.previewing = true;
    try {
      const response = await this.deps.api.approvalPreview(this.approvalId, { checkedRows: this.checkedRows() });
      if (seq !== this.previewSeq) return;
      this.view.value = response.view;
      this.fingerprint.value = response.fingerprint;
    } catch (error) {
      if (seq === this.previewSeq) this.deps.message.error(`按勾选重新计算失败：${errorText(error)}`);
    } finally {
      if (seq === this.previewSeq) this.state.previewing = false;
    }
  }

  // ================================================================ 通过、驳回、撤回（FA-03、FA-04、FA-07、FA-08）

  /** 人工参数中还没填的必填项 */
  missingParam() {
    return this.detail.value?.params.find(p => p.required && isEmpty(this.state.params[p.name])) ?? null;
  }

  /** 通过：各审批流勾选的行一起提交，带最近一次的结果指纹和新的请求键（FA-01、FA-07） */
  async pass(): Promise<CommandResult | null> {
    const detail = this.detail.value;
    if (!detail || !detail.actions.canPass || this.busy) return null;
    const missing = this.missingParam();
    if (missing) {
      this.deps.message.warning(`请填写${missing.label || missing.name}`);
      return null;
    }
    const body: PassRequest = {
      requestKey: this.newRequestKey(),
      fingerprint: this.fingerprint.value,
      checkedRows: this.checkedRows(),
      comment: this.state.comment.trim() || null
    };
    const params = this.paramsBody(detail.params);
    if (Object.keys(params).length) body.params = params;
    return this.submit(() => this.deps.api.passApproval(this.approvalId, body), '本级审批已提交');
  }

  /** 驳回：必须填写驳回原因；不带人工参数（FA-08） */
  async reject(): Promise<CommandResult | null> {
    const detail = this.detail.value;
    if (!detail || !detail.actions.canReject || this.busy) return null;
    const comment = this.state.comment.trim();
    if (!comment) {
      this.deps.message.warning('请填写驳回原因');
      return null;
    }
    return this.submit(
      () => this.deps.api.rejectApproval(this.approvalId, { requestKey: this.newRequestKey(), comment }),
      '已驳回'
    );
  }

  /** 撤回：只有 `canWithdraw` 时可用（FA-04），原因可以不填 */
  async withdraw(): Promise<CommandResult | null> {
    const detail = this.detail.value;
    if (!detail || !detail.actions.canWithdraw || this.busy) return null;
    const body: WithdrawRequest = { requestKey: this.newRequestKey() };
    const comment = this.state.comment.trim();
    if (comment) body.comment = comment;
    return this.submit(() => this.deps.api.withdrawApproval(this.approvalId, body), '已撤回');
  }

  private paramsBody(params: readonly FlowParam[]) {
    const body: Record<string, string | boolean> = {};
    for (const param of params) {
      const value = this.state.params[param.name];
      if (isEmpty(value)) continue;
      body[param.name] = param.type === 'boolean' ? Boolean(value) : String(value).trim();
    }
    return body;
  }

  private async submit(call: () => Promise<CommandResult>, successText: string) {
    this.state.submitting = true;
    this.state.error = '';
    try {
      const result = await call();
      this.deps.message.success(successText);
      this.state.reconfirm = false;
      this.state.comment = '';
      this.state.params = {};
      notifyApprovalProcessed(this.approvalId);
      await this.load();
      return result;
    } catch (error) {
      if (error instanceof PlatformError && error.code === 'RECONFIRM_REQUIRED') {
        this.state.reconfirm = true;
        this.deps.message.warning('审批内容已变化，已重新读取详情，请核对后重新确认');
        await this.load();
        return null;
      }
      this.state.error = errorText(error);
      return null;
    } finally {
      this.state.submitting = false;
    }
  }
}
