/**
 * 顶栏铃铛的角标（FS-06，C11 v3 `ShellApi.bell`）：待我审批的审批数，同旧系统铃铛
 * （`approval-notification-center.vue` 第 45、224 行的 `unreadCount`，后端 `ApprovalNotificationService.summary` 第 49 行
 * `unreadCount = approvalCount`）。读了通知但还没审批，角标不变；审批人通过或驳回后角标跟着少。
 *
 * - 条数为 `GET /api/approvals?box=todo&startRow=0&endRow=0` 的 `total`（C09 v14），后台请求（C09 第 1 节，不顺延会话）。
 * - 什么时候重新读：会话就绪时；收到链接为 `/approval/…` 的站内通知（有审批提交给我、进入我这一级、我发起的审批结束，C10）；
 *   本浏览器中处理了审批（`ShellApi.bell.refresh`，旧系统处理完立即 loadSummary）；点开铃铛时（旧系统 openDrawer）；
 *   以及每 60 秒一次（旧系统第 63–66 行每 60 秒读一次：同一角色的别人处理了审批、或没有配置通知时，角标也会跟着变）。
 * - 读取失败时保留原来的数（旧系统 `if (!error)` 才更新）。
 */
import { ref } from "vue";
import type { PlatformApi } from "../../contracts/api";
import type { RealtimeClient } from "../../contracts/realtime";

/** 定时重新读取的间隔（毫秒），同旧系统 */
export const TODO_POLL_MS = 60_000;

export class TodoCount {
  readonly count = ref(0);

  private started = false;
  private off: (() => void) | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private seq = 0;

  constructor(
    private readonly deps: {
      api: Pick<PlatformApi, "approvals">;
      realtime: RealtimeClient;
    },
  ) {}

  /** 会话就绪时调用；已经开始时什么也不做 */
  start(): Promise<void> {
    if (this.started) return Promise.resolve();
    this.started = true;
    this.off = this.deps.realtime.onEvent("notification", (payload) => {
      if (payload.link?.startsWith("/approval/")) void this.refresh();
    });
    this.timer = setInterval(() => void this.refresh(), TODO_POLL_MS);
    return this.refresh();
  }

  /** 会话结束时调用 */
  stop() {
    this.off?.();
    this.off = null;
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    this.started = false;
    this.seq += 1;
    this.count.value = 0;
  }

  /** 重新读取条数；几次读取同时进行时以最后发出的为准 */
  async refresh(): Promise<void> {
    if (!this.started) return;
    const seq = ++this.seq;
    try {
      const list = await this.deps.api.approvals(
        { box: "todo", startRow: 0, endRow: 0 },
        true,
      );
      if (seq === this.seq) this.count.value = list.total;
    } catch {
      // 读取失败保留原来的数；会话失效由 HTTP 客户端统一处理
    }
  }
}
