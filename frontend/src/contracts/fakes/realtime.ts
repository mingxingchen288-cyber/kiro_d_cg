/**
 * 实时事件的模拟发送器（C10 第 2 节）：测试用 `push` 模拟服务端推送，客户端按 eventId 去重后交给监听者。
 * 订阅和退订记在 `sent` 中，内容与浏览器发给 `/ws` 的消息相同。
 */
import type { ClientMessage, RealtimeClient, ServerMessage, Topic, TopicPayloads } from '../realtime';

type Listener = (payload: unknown, eventId: string) => void;

export class FakeRealtime implements RealtimeClient {
  /** 客户端发出的消息 */
  readonly sent: ClientMessage[] = [];
  private readonly listeners = new Map<Topic, Set<Listener>>();
  private readonly counts = new Map<string, number>();
  private readonly seen = new Set<string>();

  /** 当前订阅的页面 */
  get pages() {
    return [...this.counts.keys()];
  }

  subscribe(pages: string[]) {
    const added = pages.filter(page => {
      const count = this.counts.get(page) ?? 0;
      this.counts.set(page, count + 1);
      return count === 0;
    });
    if (added.length) this.sent.push({ type: 'subscribe', pages: added });
  }

  unsubscribe(pages: string[]) {
    const removed = pages.filter(page => {
      const count = this.counts.get(page) ?? 0;
      if (count <= 1) {
        this.counts.delete(page);
        return count === 1;
      }
      this.counts.set(page, count - 1);
      return false;
    });
    if (removed.length) this.sent.push({ type: 'unsubscribe', pages: removed });
  }

  onEvent<T extends Topic>(topic: T, handler: (payload: TopicPayloads[T], eventId: string) => void) {
    const set = this.listeners.get(topic) ?? new Set<Listener>();
    set.add(handler as Listener);
    this.listeners.set(topic, set);
    return () => set.delete(handler as Listener);
  }

  /** 模拟服务端推送一条消息；同一 eventId 只交付一次 */
  push(message: ServerMessage) {
    if (!('topic' in message)) return;
    if (this.seen.has(message.eventId)) return;
    this.seen.add(message.eventId);
    for (const listener of this.listeners.get(message.topic) ?? []) listener(message.payload, message.eventId);
  }
}

export function createFakeRealtime() {
  return new FakeRealtime();
}
