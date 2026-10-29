/**
 * 实时客户端（C10 第 2 节）：连接 `/ws`，按页面订阅 `config.changed`，按 eventId 去重后交给监听者；断线后自动重连并重新订阅。
 * 实现 C11 的 `RealtimeClient`。这是 assembly 接入前（AS-06、T-AS-3）的过渡实现：开发服务器的代理还没有转发
 * WebSocket（build/config/proxy.ts 没有 `ws: true`），连不上时只在后台重试，页面照常使用。
 */
import { type RealtimeClient, ServerMessage, type Topic, type TopicPayloads } from '@/contracts/realtime';

type Listener = (payload: unknown, eventId: string) => void;

const MAX_SEEN = 500;

export function createRealtimeClient(url: string): RealtimeClient {
  const listeners = new Map<Topic, Set<Listener>>();
  const counts = new Map<string, number>();
  const seen: string[] = [];
  let socket: WebSocket | null = null;
  let retry = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function send(message: object) {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  }

  function connect() {
    if (socket || typeof WebSocket === 'undefined') return;
    try {
      socket = new WebSocket(url);
    } catch {
      schedule();
      return;
    }
    socket.onopen = () => {
      retry = 0;
      if (counts.size) send({ type: 'subscribe', pages: [...counts.keys()] });
    };
    socket.onmessage = event => {
      let message: ServerMessage;
      try {
        message = ServerMessage.parse(JSON.parse(String(event.data)));
      } catch {
        return;
      }
      if (!('topic' in message) || seen.includes(message.eventId)) return;
      seen.push(message.eventId);
      if (seen.length > MAX_SEEN) seen.shift();
      for (const listener of listeners.get(message.topic) ?? []) listener(message.payload, message.eventId);
    };
    socket.onclose = () => {
      socket = null;
      schedule();
    };
  }

  function schedule() {
    if (timer) return;
    retry += 1;
    timer = setTimeout(
      () => {
        timer = null;
        connect();
      },
      Math.min(30_000, 1000 * 2 ** Math.min(retry, 5))
    );
  }

  return {
    subscribe(pages) {
      const added = pages.filter(page => {
        const count = counts.get(page) ?? 0;
        counts.set(page, count + 1);
        return count === 0;
      });
      connect();
      if (added.length) send({ type: 'subscribe', pages: added });
    },
    unsubscribe(pages) {
      const removed = pages.filter(page => {
        const count = counts.get(page) ?? 0;
        if (count <= 1) {
          counts.delete(page);
          return count === 1;
        }
        counts.set(page, count - 1);
        return false;
      });
      if (removed.length) send({ type: 'unsubscribe', pages: removed });
    },
    onEvent<T extends Topic>(topic: T, handler: (payload: TopicPayloads[T], eventId: string) => void) {
      const set = listeners.get(topic) ?? new Set<Listener>();
      set.add(handler as Listener);
      listeners.set(topic, set);
      connect();
      return () => set.delete(handler as Listener);
    }
  };
}
