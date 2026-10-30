/**
 * 审批进度弹窗（FP-16、FP-21）和按地址定位单据（FP-20）：
 * - 弹窗的文字：各级节点的审批人和处理情况（C09 第 6 节）；
 * - "查看审批进度"：选中的单据的审批，进行中的优先，没有进行中的显示最近一个，都没有时"暂无审批记录"（C09 v14 `box=record`）；
 *   每个审批"查看审批详情"打开审批详情页签；
 * - 定位：`/page/COST_PINGGU?record=2551` 打开后主表只显示 2551 并选中，地址改回 `/page/COST_PINGGU`；"显示全部"后照常查询。
 * 数据同 support.ts：成本单 2550、2551，审批 203 为 C09 第 6 节的样例。
 */
import { describe, expect, it } from "vitest";
import {
  approvalDetailSample,
  approvalSummarySample,
} from "../../src/contracts/fakes/samples";
import {
  MEMBER_STATUS,
  type ProgressStep,
  membersText,
} from "../../src/modules/page/approval-progress";
import { FROZEN_TITLE } from "../../src/modules/page/page-runtime";
import { MASTER, masterRow, openCostPage } from "./support";

describe("审批进度弹窗的审批人", () => {
  it("或签节点一人通过后，另一人显示已跳过", () => {
    const step: ProgressStep = {
      level: 1,
      flow: "COST_TO_GOODS",
      flowName: "成本明细改价审批",
      node: "管理员审批",
      mode: "or",
      status: "passed",
      members: [
        {
          type: "user",
          id: "1",
          name: "系统管理员",
          status: "passed",
          processedBy: { userId: "1", displayName: "系统管理员" },
          processedAt: "2026-10-30T10:00:00",
          comment: null,
        },
        {
          type: "user",
          id: "200",
          name: "第二审批人",
          status: "skipped",
          processedBy: null,
          processedAt: null,
          comment: null,
        },
      ],
    };
    expect(membersText(step)).toBe(
      "系统管理员（已通过，系统管理员 2026-10-30 10:00:00）；第二审批人（已跳过）",
    );
  });

  it("五种审批人状态都有文字", () => {
    expect(
      ["pending", "passed", "rejected", "withdrawn", "skipped"].map(
        (s) => MEMBER_STATUS[s],
      ),
    ).toEqual(["待处理", "已通过", "已驳回", "已撤回", "已跳过"]);
  });
});

const summary = (
  approvalId: string,
  status: "pending" | "approved" | "withdrawn",
) => ({
  ...approvalSummarySample,
  approvalId,
  page: MASTER,
  status,
  source: { entity: MASTER, recordKey: "2550", label: "250mg乙酰唑胺片" },
});

describe("查看审批进度（FP-21）", () => {
  it('选中 2550：按单据查审批，显示进行中的那个，"查看审批详情"打开审批详情页签', async () => {
    const ctx = await openCostPage(undefined, (fake) => {
      fake.http.on("GET", "/api/approvals", {
        rows: [summary("205", "pending"), summary("203", "approved")],
        total: 2,
      });
      fake.http.on(
        "GET",
        "/api/approvals/:approvalId",
        (call: { params: Record<string, string> }) => ({
          ...approvalDetailSample,
          approvalId: call.params.approvalId,
        }),
      );
    });
    ctx.master.select("2550");
    await ctx.runtime.showRecordApprovals();
    expect(
      ctx.fake.http.callsTo("GET", "/api/approvals").at(-1)?.options?.query,
    ).toEqual({
      box: "record",
      page: MASTER,
      recordKey: "2550",
      startRow: 0,
      endRow: 20,
    });
    const shown = ctx.runtime.ui.frozen.value!;
    expect([
      shown.title,
      shown.items.map((i) => i.approvalId),
      shown.message,
    ]).toEqual(["单据 2550 的审批进度", ["205"], ""]);

    ctx.runtime.openApprovalDetail("205");
    expect(ctx.fake.opened.at(-1)).toEqual({
      path: "/approval/205",
      title: "审批详情 205",
    });
    expect(ctx.runtime.ui.frozen.value).toBeNull();
  });

  it('没有进行中的显示最近一个；没有审批时"暂无审批记录"；没选中时提示先选择', async () => {
    let rows = [summary("203", "approved"), summary("201", "withdrawn")];
    const ctx = await openCostPage(undefined, (fake) => {
      fake.http.on("GET", "/api/approvals", () => ({
        rows,
        total: rows.length,
      }));
      fake.http.on("GET", "/api/approvals/:approvalId", approvalDetailSample);
    });
    await ctx.runtime.showRecordApprovals();
    expect(ctx.fake.messages.at(-1)).toEqual({
      kind: "warning",
      text: "请先选择一条单据",
    });

    ctx.master.select("2550");
    await ctx.runtime.showRecordApprovals();
    expect(
      ctx.fake.http
        .callsTo("GET", "/api/approvals/:approvalId")
        .map((c) => c.params.approvalId),
    ).toEqual(["203"]);

    rows = [];
    await ctx.runtime.showRecordApprovals();
    expect(ctx.runtime.ui.frozen.value).toMatchObject({
      items: [],
      message: "暂无审批记录",
      loading: false,
    });
  });

  it('修改被冻结的单据时弹窗标题仍是"单据在审批中，不能修改"', async () => {
    const ctx = await openCostPage(undefined, (fake) =>
      fake.http.on("GET", "/api/approvals/:approvalId", approvalDetailSample),
    );
    await ctx.runtime.showApprovals(["203"]);
    expect(ctx.runtime.ui.frozen.value?.title).toBe(FROZEN_TITLE);
  });
});

describe("按地址定位单据（FP-20）", () => {
  it("?record=2551：主表只取 2551、选中它，地址改回不带 record；之后的查询照常", async () => {
    const ctx = await openCostPage(undefined, (fake) => {
      fake.http.on("POST", "/api/pages/:pageCode/rows/by-keys", {
        rows: [masterRow("2551", "原备注")],
      });
    });
    const { runtime, fake, master } = ctx;
    runtime.focus("2551");
    // 页面已打开：去掉地址中的 record，主表从第一页重新查询
    expect(fake.opened.at(-1)).toEqual({
      path: `/page/${MASTER}`,
      title: "成本核算",
    });
    expect(master.reloads.at(-1)).toBe(true);

    const focused = await runtime.fetchMasterRows({ startRow: 0, endRow: 100 });
    expect(
      fake.http.callsTo("POST", "/api/pages/:pageCode/rows/by-keys").at(-1)
        ?.body,
    ).toEqual({
      entity: MASTER,
      rowKeys: ["2551"],
    });
    expect([
      focused.rows.map((r) => r.__id),
      focused.total,
      focused.focus,
    ]).toEqual([["2551"], 1, "2551"]);
    expect(runtime.state.focused).toBe("2551");

    // 表格选中定位的行后，明细显示这张单据
    master.select(focused.focus!);
    runtime.onSelection(MASTER, [focused.focus!]);
    await runtime.activate("2551");
    expect(runtime.state.activeRecord).toBe("2551");

    // 用户再查询（例如排序）：照常列出全部
    const listed = fake.http.callsTo(
      "POST",
      "/api/pages/:pageCode/rows",
    ).length;
    const next = await runtime.fetchMasterRows({
      startRow: 0,
      endRow: 100,
      sortModel: [{ colId: "DOCID", sort: "desc" }],
    });
    expect(fake.http.callsTo("POST", "/api/pages/:pageCode/rows").length).toBe(
      listed + 1,
    );
    expect([
      next.rows.map((r) => r.__id),
      next.focus,
      runtime.state.focused,
    ]).toEqual([["2550", "2551"], undefined, null]);
  });

  it('"显示全部"：不再只显示定位的单据，从第一页重新查询', async () => {
    const ctx = await openCostPage(undefined, (fake) => {
      fake.http.on("POST", "/api/pages/:pageCode/rows/by-keys", {
        rows: [masterRow("2551", "原备注")],
      });
    });
    ctx.runtime.focus("2551");
    await ctx.runtime.fetchMasterRows({ startRow: 0, endRow: 100 });
    ctx.runtime.clearFocus();
    expect([ctx.runtime.state.focused, ctx.master.reloads.at(-1)]).toEqual([
      null,
      true,
    ]);
    const all = await ctx.runtime.fetchMasterRows({ startRow: 0, endRow: 100 });
    expect(all.rows.map((r) => r.__id)).toEqual(["2550", "2551"]);
  });
});
