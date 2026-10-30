/**
 * 铃铛角标（FS-06）：待我审批的审批数，同旧系统 `ApprovalNotificationService.summary` 的 `unreadCount = approvalCount`。
 * 会话就绪时读一次（`box=todo` 只取条数，后台请求）；收到 `/approval/…` 的通知、`ShellApi.bell.refresh`、每 60 秒重新读。
 * 条数取 C09 第 6 节待办列表样例的 `total`（7）。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { createPlatformApi } from "../../src/contracts/api";
import { createFakeHttp } from "../../src/contracts/fakes/http";
import { createFakeRealtime } from "../../src/contracts/fakes/realtime";
import { TODO_POLL_MS, TodoCount } from "../../src/modules/shell/todo-count";

function setup() {
  const http = createFakeHttp();
  const realtime = createFakeRealtime();
  const todo = new TodoCount({ api: createPlatformApi(http), realtime });
  return { http, realtime, todo };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  vi.useRealTimers();
});

describe("铃铛角标：待我审批数（FS-06）", () => {
  it("会话就绪时读取 box=todo 的条数（后台请求，只取条数）", async () => {
    const { http, todo } = setup();
    await todo.start();
    const calls = http.callsTo("GET", "/api/approvals");
    expect(calls.map((c) => c.options)).toEqual([
      { query: { box: "todo", startRow: 0, endRow: 0 }, background: true },
    ]);
    expect(todo.count.value).toBe(7);
  });

  it("审批人通过后（bell.refresh）条数跟着变；收到审批通知时重新读，其他通知不读", async () => {
    const { http, realtime, todo } = setup();
    await todo.start();
    http.on("GET", "/api/approvals", { rows: [], total: 6 });
    await todo.refresh();
    expect(todo.count.value).toBe(6);

    http.on("GET", "/api/approvals", { rows: [], total: 7 });
    realtime.push({
      topic: "notification",
      eventId: "2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d",
      payload: {
        deliveryId: "3b4c5d6e-7f8a-4b9c-8d0e-2f3a4b5c6d7e",
        title: "您有来自于成本核算页面，业务单据为2550的审批",
        body: "",
        link: "/approval/301",
      },
    });
    await flush();
    expect(todo.count.value).toBe(7);
    const before = http.callsTo("GET", "/api/approvals").length;
    realtime.push({
      topic: "notification",
      eventId: "4c5d6e7f-8a9b-4c0d-9e1f-3a4b5c6d7e8f",
      payload: {
        deliveryId: "5d6e7f8a-9b0c-4d1e-8f2a-4b5c6d7e8f9a",
        title: "其他通知",
        body: "",
        link: null,
      },
    });
    await flush();
    expect(http.callsTo("GET", "/api/approvals").length).toBe(before);
  });

  it("每 60 秒重新读一次（同旧系统）；会话结束后不再读，角标清零", async () => {
    vi.useFakeTimers();
    const { http, todo } = setup();
    await todo.start();
    http.on("GET", "/api/approvals", { rows: [], total: 3 });
    await vi.advanceTimersByTimeAsync(TODO_POLL_MS);
    expect(todo.count.value).toBe(3);
    todo.stop();
    expect(todo.count.value).toBe(0);
    const before = http.callsTo("GET", "/api/approvals").length;
    await vi.advanceTimersByTimeAsync(TODO_POLL_MS * 2);
    expect(http.callsTo("GET", "/api/approvals").length).toBe(before);
  });
});
