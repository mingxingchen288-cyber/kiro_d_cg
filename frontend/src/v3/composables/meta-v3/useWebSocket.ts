import { onUnmounted, ref } from 'vue';
import { getToken } from '@/store/modules/auth/shared';

export type WsMessage = {
  type: string;
  payload: Record<string, any>;
};

type Listener = (payload: Record<string, any>) => void;

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
const listeners = new Map<string, Set<Listener>>();
const connected = ref(false);
let refCount = 0;

const HEARTBEAT_INTERVAL = 30_000;
const RECONNECT_DELAY = 3_000;

function getWsUrl() {
  const token = getToken();
  if (!token) return null;

  const rawBase = import.meta.env.VITE_SERVICE_BASE_URL?.trim();
  const normalizedBase = rawBase
    ? /^(https?:)?\/\//.test(rawBase)
      ? rawBase
      : `${window.location.origin}${rawBase.startsWith('/') ? '' : '/'}${rawBase}`
    : `${window.location.protocol}//${window.location.host}`;
  const wsBase = normalizedBase.replace(/^http/, 'ws').replace(/\/$/, '');
  return `${wsBase}/ws?token=${token}`;
}

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send('ping');
    }
  }, HEARTBEAT_INTERVAL);
}

function stopHeartbeat() {
  if (!heartbeatTimer) return;

  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function connect() {
  if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return;

  const url = getWsUrl();
  if (!url) return;

  ws = new WebSocket(url);

  ws.onopen = () => {
    connected.value = true;
    startHeartbeat();
    console.log('[WS] connected');
  };

  ws.onmessage = event => {
    const data = event.data;
    if (data === 'pong') return;

    try {
      const msg: WsMessage = JSON.parse(data);
      const typeListeners = listeners.get(msg.type);
      typeListeners?.forEach(listener => listener(msg.payload));
    } catch {
      // Ignore non-JSON messages.
    }
  };

  ws.onclose = () => {
    connected.value = false;
    stopHeartbeat();

    if (refCount > 0) {
      reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
    }
  };

  ws.onerror = () => {
    ws?.close();
  };
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  stopHeartbeat();
  ws?.close();
  ws = null;
  connected.value = false;
}

export function useWebSocket() {
  refCount += 1;
  if (refCount === 1) connect();

  const localSubscriptions: Array<() => void> = [];

  function subscribe(type: string, callback: Listener) {
    if (!listeners.has(type)) {
      listeners.set(type, new Set());
    }

    listeners.get(type)!.add(callback);

    const unsubscribe = () => {
      listeners.get(type)?.delete(callback);
      if (listeners.get(type)?.size === 0) {
        listeners.delete(type);
      }
    };

    localSubscriptions.push(unsubscribe);
    return unsubscribe;
  }

  onUnmounted(() => {
    localSubscriptions.forEach(unsubscribe => unsubscribe());
    localSubscriptions.length = 0;

    refCount -= 1;
    if (refCount <= 0) {
      refCount = 0;
      disconnect();
    }
  });

  return { connected, subscribe };
}

export function reconnectWebSocket() {
  disconnect();
  if (refCount > 0) connect();
}
