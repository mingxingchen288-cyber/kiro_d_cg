/**
 * 实时客户端（C10 第 2 节）：连接 `/ws`，按页面订阅 `config.changed`，按 eventId 去重后交给监听者；断线后自动重连并重新订阅。
 * 实现 C11 的 `RealtimeClient`，外加外壳用的 `start`、`stop`：
 *
 * - 会话就绪后外壳调用 `start` 才连接，注销或会话失效时调用 `stop` 断开；没有登录时不连接（握手会被拒绝）。
 * - 服务端在会话失效时以关闭码 4401 关闭连接（realtime 缺口 1）：这时不重连，调用 `onSessionEnded`，由外壳核对会话
 *   （仍有效就再调用 `start`，否则回登录页或选角色，FS-02）。其他原因断开时按退避间隔重连。
 * - 开发服务器的代理是否转发 WebSocket 由 assembly 配置（AS-06）；连不上时只在后台重试，页面照常使用。
 */
import { type RealtimeClient, ServerMessage, type Topic, type TopicPayloads } from '../contracts/realtime';

type Listener = (payload: unknown, eventId: string) => void;

const MAX_SEEN = 500;

/** 服务端在会话失效时关闭连接用的关闭码（realtime 的 `CLOSE_SESSION_ENDED`） */
export const CLOSE_SESSION_ENDED = 4401;

export interface ShellRealtimeClient extends RealtimeClient {
  /** 开始连接（已连接时什么也不做） */
  start(): void;
  /** 断开并停止重连；订阅和监听保留，下次 `start` 后重新订阅 */
  stop(): void;
}

export interface RealtimeOptions {
  /** 连接以 4401 关闭 */
  onSessionEnded?: () => void;
}

export function createRealtimeClient(url: string, options: RealtimeOptions = {}): ShellRealtimeClient {
  const listeners = new Map<Topic, Set<Listener>>();
  const counts = new Map<string, number>();
  const seen: string[] = [];
  let socket: WebSocket | null = null;
  let started = false;
  let retry = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function send(message: object) {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  }

  function connect() {
    if (!started || socket || typeof WebSocket === 'undefined') return;
    let current: WebSocket;
    try {
      current = new WebSocket(url);
    } catch {
      schedule();
      return;
    }
    socket = current;
    current.onopen = () => {
      retry = 0;
      if (counts.size) send({ type: 'subscribe', pages: [...counts.keys()] });
    };
    current.onmessage = event => {
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
    current.onclose = event => {
      if (socket !== current) return;
      socket = null;
      if (event.code === CLOSE_SESSION_ENDED) {
        started = false;
        options.onSessionEnded?.();
        return;
      }
      schedule();
    };
  }

  function schedule() {
    if (timer || !started) return;
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
    start() {
      started = true;
      connect();
    },
    stop() {
      started = false;
      retry = 0;
      if (timer) clearTimeout(timer);
      timer = null;
      const current = socket;
      socket = null;
      current?.close(1000);
    },
    subscribe(pages) {
      const added = pages.filter(page => {
        const count = counts.get(page) ?? 0;
        counts.set(page, count + 1);
        return count === 0;
      });
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
      return () => set.delete(handler as Listener);
    }
  };
}
