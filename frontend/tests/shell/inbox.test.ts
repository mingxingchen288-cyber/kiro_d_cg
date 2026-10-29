/**
 * 站内通知（FS-04）：未读数只在打开时读取一次（后台请求），之后随 notification 事件更新，不轮询；
 * 点击通知标为已读并按 link 跳转。通知内容取 C09 第 7 节、C10 第 2 节的样例（物料清单及成本页单据 115 的审批 203）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPlatformApi } from '../../src/contracts/api';
import { createFakeHttp } from '../../src/contracts/fakes/http';
import { createFakeRealtime } from '../../src/contracts/fakes/realtime';
import { inboxListSample } from '../../src/contracts/fakes/samples';
import { Inbox } from '../../src/modules/shell/inbox';

const NOTICE = {
  deliveryId: '3b4c5d6e-7f8a-4b9c-8d0e-2f3a4b5c6d7e',
  title: '您有来自于物料清单及成本页面，业务单据为115的审批',
  body: '',
  link: '/approval/203'
};

function setup() {
  const http = createFakeHttp();
  const realtime = createFakeRealtime();
  const visited: string[] = [];
  const inbox = new Inbox({
    api: createPlatformApi(http),
    realtime,
    navigate: link => visited.push(link),
    now: () => new Date(2026, 9, 29, 9, 30, 1)
  });
  return { http, realtime, visited, inbox };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('站内通知（FS-04）', () => {
  it('打开时读取一次未读通知（后台请求）：铃铛显示 2', async () => {
    const { http, inbox } = setup();

    await inbox.start();

    const calls = http.callsTo('GET', '/api/inbox');
    expect(calls).toHaveLength(1);
    expect(calls[0].options).toEqual({ query: { unread: true, startRow: 0, endRow: 50 }, background: true });
    expect(inbox.unread.value).toBe(2);
    expect(inbox.items.value).toEqual(inboxListSample.rows);
  });

  it('之后按 notification 事件更新，不再请求，也不轮询；同一 deliveryId 只算一次', async () => {
    vi.useFakeTimers();
    const { http, realtime, inbox } = setup();
    await inbox.start();

    realtime.push({ topic: 'notification', eventId: '2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d', payload: NOTICE });
    // 投递重试：事件编号不同，deliveryId 相同
    realtime.push({ topic: 'notification', eventId: '5d6e7f8a-9b0c-4d1e-8f2a-3b4c5d6e7f8a', payload: NOTICE });
    vi.advanceTimersByTime(10 * 60 * 1000);

    expect(inbox.unread.value).toBe(3);
    expect(inbox.items.value[0]).toEqual({ ...NOTICE, createdAt: '2026-10-29T09:30:01', read: false });
    expect(inbox.items.value).toHaveLength(2);
    expect(http.callsTo('GET', '/api/inbox')).toHaveLength(1);
  });

  it('点击通知：标为已读（POST /api/inbox/{deliveryId}/read），未读数减一，跳到 /approval/203', async () => {
    const { http, inbox, visited } = setup();
    await inbox.start();
    const [first] = inbox.items.value;

    await inbox.open(first);

    expect(http.callsTo('POST', '/api/inbox/:deliveryId/read').map(c => c.params.deliveryId)).toEqual([
      first.deliveryId
    ]);
    expect(inbox.unread.value).toBe(1);
    expect(inbox.items.value.some(item => item.deliveryId === first.deliveryId)).toBe(false);
    expect(visited).toEqual(['/approval/203']);
  });

  it('退出登录后清空，下次登录重新读取一次', async () => {
    const { http, inbox } = setup();
    await inbox.start();

    inbox.stop();
    expect(inbox.unread.value).toBe(0);
    await inbox.start();

    expect(http.callsTo('GET', '/api/inbox')).toHaveLength(2);
    expect(inbox.unread.value).toBe(2);
  });
});
