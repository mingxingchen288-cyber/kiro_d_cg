/**
 * 待办列表（"待审批 / 我的发起 / 全部审批"，同旧系统审批通知中心）：每个审批一行，列为来源页面和操作、提交时间、提交人、
 * 来源单据号、状态和当前级别（FA-06、FA-11）；打开审批详情走路由 `/approval/{approvalId}`（FA-05）；"原单据"打开来源页面并
 * 带要定位的单据号（FA-14）；处理后、收到审批通知时刷新列表。
 * 数据为 C09 第 6 节的样例（审批 203，物料清单及成本页保存聚维酮K30）。
 */
import { describe, expect, it } from "vitest";
import { createPlatformApi } from "../../src/contracts/api";
import { createFakeShell } from "../../src/contracts/fakes/shell";
import { approvalModule } from "../../src/modules/approval";
import { ApprovalDetailRuntime } from "../../src/modules/approval/detail-runtime";
import {
  ApprovalTodoRuntime,
  sourcePath,
  summaryTexts,
} from "../../src/modules/approval/todo-runtime";
import { historyRows } from "../../src/modules/approval/view-model";
import { approvalDetailSample } from "../../src/contracts/fakes/samples";

function setup() {
  const fake = createFakeShell();
  const rt = new ApprovalTodoRuntime({
    api: createPlatformApi(fake.http),
    message: fake.shell.message,
    tabs: fake.shell.tabs,
    realtime: fake.shell.realtime,
  });
  return { fake, rt };
}

describe("待办列表", () => {
  it('打开时读取"待审批"一页，并读取"我的发起""全部审批"的条数', async () => {
    const { fake, rt } = setup();
    await rt.load();
    const queries = fake.http
      .callsTo("GET", "/api/approvals")
      .map((c) => c.options?.query);
    expect(queries).toEqual([
      { box: "todo", startRow: 0, endRow: 50 },
      { box: "mine", startRow: 0, endRow: 0 },
      { box: "all", startRow: 0, endRow: 0 },
    ]);
    // C09 第 6 节样例的 total 为 7（各页签用同一个样例）
    expect(rt.state.counts).toEqual({ todo: 7, mine: 7, all: 7 });
    expect(rt.state.rows.map((r) => r.approvalId)).toEqual(["203"]);
    expect(summaryTexts(rt.state.rows[0])).toEqual({
      source: "物料清单及成本（保存）",
      recordKey: "25（聚维酮K30）",
      applicant: "杨娜",
      submittedAt: "2026-10-24 09:30:00",
      status: "审批中 · 第 1 级",
    });
  });

  it('切换到"我的发起""全部审批"；打开详情用 /approval/{approvalId}', async () => {
    const { fake, rt } = setup();
    await rt.load();
    await rt.switchBox("mine");
    expect(
      fake.http.callsTo("GET", "/api/approvals").at(-3)?.options?.query,
    ).toEqual({
      box: "mine",
      startRow: 0,
      endRow: 50,
    });
    await rt.switchBox("all");
    expect(
      fake.http.callsTo("GET", "/api/approvals").at(-3)?.options?.query,
    ).toEqual({
      box: "all",
      startRow: 0,
      endRow: 50,
    });
    rt.open(rt.state.rows[0]);
    expect(fake.opened).toEqual([
      { path: "/approval/203", title: "审批详情 203" },
    ]);
  });

  it("原单据：打开来源页面，带要定位的来源单据号", async () => {
    const { fake, rt } = setup();
    await rt.load();
    rt.openSource(rt.state.rows[0]);
    expect(fake.opened).toEqual([
      { path: "/page/GOODS_PRICE_MANAGE?record=25", title: "物料清单及成本" },
    ]);
    expect(
      sourcePath({
        page: "COST_PINGGU",
        source: { entity: "COST_PINGGU", recordKey: "2550", label: null },
      }),
    ).toBe("/page/COST_PINGGU?record=2550");
  });

  it("审批处理完成、收到审批通知时重新读取列表", async () => {
    const { fake, rt } = setup();
    const stop = rt.watch();
    await rt.load();
    const before = fake.http.callsTo("GET", "/api/approvals").length;

    const detail = new ApprovalDetailRuntime("203", {
      api: createPlatformApi(fake.http),
      message: fake.shell.message,
    });
    await detail.load();
    await detail.pass();
    await rt.idle();
    expect(fake.http.callsTo("GET", "/api/approvals").length).toBe(before + 3);

    fake.realtime.push({
      topic: "notification",
      eventId: "2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d",
      payload: {
        deliveryId: "3b4c5d6e-7f8a-4b9c-8d0e-2f3a4b5c6d7e",
        title: "您有来自于物料清单及成本页面，业务单据为25的审批",
        body: "",
        link: "/approval/203",
      },
    });
    await rt.idle();
    expect(fake.http.callsTo("GET", "/api/approvals").length).toBe(before + 6);
    stop();
  });

  it("处理了审批后让外壳刷新铃铛角标（C11 v3 ShellApi.bell）", async () => {
    const fake = createFakeShell();
    approvalModule.install(fake.shell);
    const detail = new ApprovalDetailRuntime("203", {
      api: createPlatformApi(fake.http),
      message: fake.shell.message,
    });
    await detail.load();
    await detail.pass();
    expect(fake.bell.refreshed).toBe(1);
  });
});

describe("审批记录（FA-12）", () => {
  it("每次提交、通过、驳回、撤回一行：动作、操作人、处理时间、意见、说明", () => {
    const by = (userId: string, displayName: string) => ({
      userId,
      displayName,
    });
    const approved = historyRows({
      status: "approved",
      history: [
        {
          action: "submit",
          level: 1,
          by: by("112", "杨娜"),
          at: "2026-10-29T09:30:00",
          comment: null,
        },
        {
          action: "pass",
          level: 1,
          by: by("1", "系统管理员"),
          at: "2026-10-29T10:00:00",
          comment: "价格已核对",
        },
        {
          action: "pass",
          level: 2,
          by: by("2001", "采购员"),
          at: "2026-10-29T11:00:00",
          comment: null,
        },
      ],
    });
    expect(approved).toEqual([
      {
        action: "提交",
        by: "杨娜",
        at: "2026-10-29 09:30:00",
        comment: "—",
        note: "提交审批，进入第 1 级",
      },
      {
        action: "通过",
        by: "系统管理员",
        at: "2026-10-29 10:00:00",
        comment: "价格已核对",
        note: "第 1 级通过",
      },
      {
        action: "通过",
        by: "采购员",
        at: "2026-10-29 11:00:00",
        comment: "—",
        note: "第 2 级通过，审批通过",
      },
    ]);
    const withdrawn = historyRows({
      status: "withdrawn",
      history: [
        ...approvalDetailSample.history,
        {
          action: "withdraw",
          level: 1,
          by: by("112", "杨娜"),
          at: "2026-10-24T10:00:00",
          comment: "录入有误",
        },
      ],
    });
    expect(withdrawn.at(-1)).toEqual({
      action: "撤回",
      by: "杨娜",
      at: "2026-10-24 10:00:00",
      comment: "录入有误",
      note: "发起人撤回，审批结束",
    });
  });
});
