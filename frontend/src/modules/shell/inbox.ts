/**
 * 站内通知（FS-04，C09 第 7 节，C10 `notification`）：顶栏铃铛的未读数和通知列表。
 *
 * - 会话就绪时读取一次 `GET /api/inbox?unread=true`（后台请求，C09 第 1 节，不顺延会话）；之后只按 `notification`
 *   事件和"标为已读"更新，不轮询。
 * - 事件按 `deliveryId` 去重（C10 第 2 节）：已经在列表中的通知不再计数。
 * - 点击通知：未读的先标为已读（`POST /api/inbox/{deliveryId}/read`），再按 `link` 跳转（例如 `/approval/203`）。
 * - "查看全部"由用户点击后读取包括已读的通知，不改变未读数。
 */
import { ref } from 'vue';
import type { PlatformApi } from '../../contracts/api';
import type { InboxList } from '../../contracts/http';
import type { NotificationPayload, RealtimeClient } from '../../contracts/realtime';

export type InboxItem = InboxList['rows'][number];

/** 打开时读取的条数 */
export const INBOX_PAGE_SIZE = 50;

function localDateTime(date: Date) {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(
    date.getMinutes()
  )}:${pad(date.getSeconds())}`;
}

export class Inbox {
  readonly unread = ref(0);
  /** 未读通知：打开时读取的，加上之后推送来的（新的在前） */
  readonly items = ref<InboxItem[]>([]);
  /** 用户点"查看全部"后读取的通知（包括已读） */
  readonly all = ref<InboxItem[] | null>(null);
  readonly loading = ref(false);

  private started = false;
  private off: (() => void) | null = null;
  /** 列表读回之前推送来的通知，读回后按 deliveryId 合并 */
  private early: InboxItem[] = [];
  private loaded = false;

  private readonly api: PlatformApi;
  private readonly realtime: RealtimeClient;
  private readonly navigate: (link: string) => unknown;
  private readonly now: () => Date;

  /** `navigate` 按通知的链接跳转；`now` 给推送来的通知记时间（推送内容没有时间） */
  constructor(deps: {
    api: PlatformApi;
    realtime: RealtimeClient;
    navigate: (link: string) => unknown;
    now?: () => Date;
  }) {
    this.api = deps.api;
    this.realtime = deps.realtime;
    this.navigate = deps.navigate;
    this.now = deps.now ?? (() => new Date());
  }

  /** 会话就绪时调用；已经开始时什么也不做 */
  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    this.loaded = false;
    this.early = [];
    this.off = this.realtime.onEvent('notification', payload => this.receive(payload));
    const list = await this.api.inbox({ unread: true, startRow: 0, endRow: INBOX_PAGE_SIZE }, true);
    if (!this.started) return;
    const known = new Set(list.rows.map(row => row.deliveryId));
    const extra = this.early.filter(item => !known.has(item.deliveryId));
    this.items.value = [...extra, ...list.rows];
    this.unread.value = list.unread + extra.length;
    this.early = [];
    this.loaded = true;
  }

  /** 会话结束时调用 */
  stop() {
    this.off?.();
    this.off = null;
    this.started = false;
    this.loaded = false;
    this.early = [];
    this.items.value = [];
    this.all.value = null;
    this.unread.value = 0;
  }

  /** 收到 `notification` 事件 */
  receive(payload: NotificationPayload) {
    const item: InboxItem = { ...payload, createdAt: localDateTime(this.now()), read: false };
    if (!this.loaded) {
      if (!this.early.some(e => e.deliveryId === item.deliveryId)) this.early.unshift(item);
      return;
    }
    if (this.items.value.some(row => row.deliveryId === item.deliveryId)) return;
    this.items.value = [item, ...this.items.value];
    this.all.value = this.all.value ? [item, ...this.all.value] : null;
    this.unread.value += 1;
  }

  /** 点击通知：未读的先标为已读，再按链接跳转 */
  async open(item: InboxItem): Promise<void> {
    if (!item.read) {
      await this.api.markRead(item.deliveryId);
      this.markLocal(item.deliveryId);
    }
    if (item.link) await this.navigate(item.link);
  }

  /** 用户点"查看全部"：读取包括已读的通知 */
  async loadAll(): Promise<void> {
    this.loading.value = true;
    try {
      const list = await this.api.inbox({ startRow: 0, endRow: INBOX_PAGE_SIZE });
      this.all.value = list.rows;
    } finally {
      this.loading.value = false;
    }
  }

  private markLocal(deliveryId: string) {
    this.items.value = this.items.value.filter(row => row.deliveryId !== deliveryId);
    if (this.all.value) {
      this.all.value = this.all.value.map(row => (row.deliveryId === deliveryId ? { ...row, read: true } : row));
    }
    this.unread.value = Math.max(0, this.unread.value - 1);
  }
}
