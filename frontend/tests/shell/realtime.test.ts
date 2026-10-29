/**
 * 实时连接（C10 第 2 节）：会话就绪后才连接；收到 session.revoked 交给外壳；服务端在会话失效时以 4401 关闭连接
 * （realtime 缺口 1），这时不重连，交给外壳核对会话，核对后回登录页（FS-02）。WebSocket 用替代实现。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PlatformError } from '../../src/contracts/errors';
import { CLOSE_SESSION_ENDED, createRealtimeClient } from '../../src/service/realtime';
import { loggedInYangna } from './support';

class FakeSocket {
  static readonly OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 0;
  readonly sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  send(text: string) {
    this.sent.push(JSON.parse(text));
  }

  close() {
    this.readyState = 3;
  }

  /** 服务端接受连接 */
  accept() {
    this.readyState = 1;
    this.onopen?.();
  }

  /** 服务端推送 */
  push(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  /** 服务端关闭连接 */
  serverClose(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const WS = 'ws://localhost/ws';

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('实时连接和会话（FS-02、C10）', () => {
  it('会话就绪后才连接；连接后补发已订阅页面；收到 session.revoked 交给外壳', () => {
    const client = createRealtimeClient(WS);
    const reasons: string[] = [];
    client.onEvent('session.revoked', payload => reasons.push(payload.reason));
    client.subscribe(['COST_PINGGU']);
    expect(FakeSocket.instances).toHaveLength(0);

    client.start();
    const socket = FakeSocket.instances[0];
    socket.accept();
    socket.push({
      topic: 'session.revoked',
      eventId: '4c5d6e7f-8a9b-4c0d-9e1f-3a4b5c6d7e8f',
      payload: { reason: 'accountDisabled' }
    });

    expect(socket.url).toBe(WS);
    expect(socket.sent).toEqual([{ type: 'subscribe', pages: ['COST_PINGGU'] }]);
    expect(reasons).toEqual(['accountDisabled']);
  });

  it('连接以 4401 关闭：不重连，外壳后台读 /api/me 核对，会话已失效就回登录页', async () => {
    const { session, http, nav } = await loggedInYangna();
    http.fail('GET', '/api/me', new PlatformError(401, 'SESSION_REQUIRED', '请先登录'));
    let checking: Promise<void> | null = null;
    const client = createRealtimeClient(WS, {
      onSessionEnded: () => {
        checking = session.verify();
      }
    });
    client.start();
    FakeSocket.instances[0].accept();

    FakeSocket.instances[0].serverClose(CLOSE_SESSION_ENDED);
    await checking;
    vi.advanceTimersByTime(60_000);

    expect(FakeSocket.instances).toHaveLength(1);
    expect(http.callsTo('GET', '/api/me').at(-1)?.options?.background).toBe(true);
    expect(nav).toEqual([{ to: 'login', keepRedirect: true }]);
  });

  it('网络断开（不是 4401）时按退避间隔重连；注销后停止，不再重连', () => {
    const client = createRealtimeClient(WS);
    client.start();
    FakeSocket.instances[0].accept();

    FakeSocket.instances[0].serverClose(1006);
    vi.advanceTimersByTime(2_000);
    expect(FakeSocket.instances).toHaveLength(2);

    client.stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(2);
  });
});
