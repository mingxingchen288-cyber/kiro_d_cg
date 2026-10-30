/**
 * 待办列表的行为：沿用旧系统审批通知中心（`approval-notification-center.vue`）的页签和条数，数据来自
 * `GET /api/approvals?box=todo|mine|all`（C09 第 6 节），每个审批一行（FA-06）。
 *
 * - 页签："待审批""我的发起"，以及"全部审批"（FA-11，C09 v14 的 `box=all`）：旧系统点"查看全部"后第一个页签换成
 *   "全部审批"（第 47、105–108 行），列出当前用户是审批人的全部审批，含已处理、已结束的。这里做成第三个页签。
 * - 打开时读取当前页签的一页，另两个页签只读条数（`endRow` 为 0）。
 * - 旧系统每 60 秒轮询条数；这里改为：审批详情中处理成功后、收到链接为 `/approval/…` 的站内通知（C10）时重新读取。
 * - "原单据"带 `?record=<来源单据号>`（FA-14，C11 v3），通用页面打开后选中这张单据（旧系统 `openOriginal` 的 `focusId`）。
 */
import { reactive } from 'vue';
import type { PlatformApi } from '../../contracts/api';
import type { ApprovalSummary } from '../../contracts/http';
import type { RealtimeClient } from '../../contracts/realtime';
import type { ShellApi } from '../../contracts/shell';
import { onApprovalProcessed } from './events';
import { errorText, formatTime, pageText, sourceText, summaryStatus } from './view-model';

export type Box = 'todo' | 'mine' | 'all';

export const BOXES: Box[] = ['todo', 'mine', 'all'];

export const BOX_LABEL: Record<Box, string> = { todo: '待审批', mine: '我的发起', all: '全部审批' };

export const PAGE_SIZE = 50;

export interface TodoDeps {
  api: PlatformApi;
  message: ShellApi['message'];
  tabs: ShellApi['tabs'];
  realtime: RealtimeClient;
}

/** 列表一行的显示文字：来源页面和操作、来源单据号、提交人、提交时间、状态和当前级别 */
export function summaryTexts(item: ApprovalSummary) {
  return {
    source: pageText(item),
    recordKey: sourceText(item.source),
    applicant: item.applicant.displayName,
    submittedAt: formatTime(item.submittedAt),
    status: summaryStatus(item)
  };
}

/** 审批详情的路由（FA-05；通知中的链接也是这个格式） */
export function detailPath(approvalId: string) {
  return `/approval/${encodeURIComponent(approvalId)}`;
}

/** 原单据的路由：来源页面，带要定位的来源单据号（FA-14，C11 v3 的 `?record=`） */
export function sourcePath(item: Pick<ApprovalSummary, 'page' | 'source'>) {
  return `/page/${encodeURIComponent(item.page)}?record=${encodeURIComponent(item.source.recordKey)}`;
}

export class ApprovalTodoRuntime {
  readonly state = reactive({
    box: 'todo' as Box,
    rows: [] as ApprovalSummary[],
    total: 0,
    counts: { todo: 0, mine: 0, all: 0 } as Record<Box, number>,
    /** 从 1 开始 */
    page: 1,
    loading: false,
    error: ''
  });

  private pending: Promise<void> = Promise.resolve();
  private seq = 0;

  constructor(private readonly deps: TodoDeps) {}

  /** 读取当前页签的当前页，以及另一个页签的条数 */
  load() {
    this.pending = this.read();
    return this.pending;
  }

  /** 等最近一次读取完成 */
  idle() {
    return this.pending;
  }

  private async read() {
    const seq = ++this.seq;
    const { box, page } = this.state;
    const others = BOXES.filter(b => b !== box);
    const api = this.deps.api;
    this.state.loading = true;
    this.state.error = '';
    try {
      const list = await api.approvals({ box, startRow: (page - 1) * PAGE_SIZE, endRow: page * PAGE_SIZE });
      const counts = { ...this.state.counts, [box]: list.total };
      for (const other of others) {
        // eslint-disable-next-line no-await-in-loop -- 依次读另两个页签的条数（与当前页签用同一个请求序号判断是否作废）
        counts[other] = (await api.approvals({ box: other, startRow: 0, endRow: 0 })).total;
      }
      if (seq !== this.seq) return;
      this.state.rows = list.rows;
      this.state.total = list.total;
      this.state.counts = counts;
    } catch (error) {
      if (seq === this.seq) this.state.error = errorText(error);
    } finally {
      if (seq === this.seq) this.state.loading = false;
    }
  }

  switchBox(box: Box) {
    this.state.box = box;
    this.state.page = 1;
    return this.load();
  }

  setPage(page: number) {
    this.state.page = page;
    return this.load();
  }

  /** 打开审批详情页签 */
  open(item: Pick<ApprovalSummary, 'approvalId'>) {
    this.deps.tabs.open(detailPath(item.approvalId), `审批详情 ${item.approvalId}`);
  }

  /**
   * 原单据：打开来源页面并定位到来源单据（FA-14；旧系统通知中心的"原单据"按钮，`openOriginal` 带 `focusId`）。
   * 通用页面的路由带 `?record=<来源单据号>`（C11 v3），打开后只显示、选中这张单据并显示它的明细。
   */
  openSource(item: Pick<ApprovalSummary, 'page' | 'pageTitle' | 'source'>) {
    this.deps.tabs.open(sourcePath(item), item.pageTitle);
  }

  /** 处理成功、收到审批通知时重新读取；返回取消监听的函数 */
  watch() {
    const stopProcessed = onApprovalProcessed(() => void this.load());
    const stopNotice = this.deps.realtime.onEvent('notification', payload => {
      if (payload.link?.startsWith('/approval/')) void this.load();
    });
    return () => {
      stopProcessed();
      stopNotice();
    };
  }
}
