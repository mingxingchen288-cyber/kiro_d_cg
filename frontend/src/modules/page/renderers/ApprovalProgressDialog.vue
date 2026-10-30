<script setup lang="ts">
/**
 * 审批进度弹窗：用户修改被审批锁定的单据时直接弹出（FP-16），或在工具栏点"查看审批进度"时弹出（FP-21）；
 * 内容来自 GET /api/approvals/{approvalId}（C09 第 6 节）。
 * 显示来源页面、来源单据号、提交人、提交时间、状态、当前级别和各级节点的处理情况；不显示修改内容，不能在这里通过或驳回。
 * 每个审批有"查看审批详情"（FP-21），打开审批详情页签看修改内容：旧系统的进度和修改内容在同一个审批详情对话框里
 * （`ApprovalActionGroup.vue` 第 16、23 行 `ApprovalDetailDialog.open(payload, 'progress')`）。
 */
import { computed } from "vue";
import {
  APPROVAL_STATUS,
  MODE,
  STEP_STATUS,
  membersText,
} from "../approval-progress";
import type { PageRuntime } from "../page-runtime";

defineOptions({ name: "ApprovalProgressDialog" });

const props = defineProps<{ runtime: PageRuntime }>();
const runtime = props.runtime;
const frozen = computed(() => runtime.ui.frozen.value);
</script>

<template>
  <NModal
    :show="Boolean(frozen)"
    @update:show="(v: boolean) => !v && runtime.closeApprovals()"
  >
    <NCard
      class="approval-progress"
      :title="frozen?.title ?? ''"
      :bordered="false"
      size="small"
      closable
      @close="runtime.closeApprovals()"
    >
      <NSpin :show="Boolean(frozen?.loading)">
        <div
          v-for="item in frozen?.items ?? []"
          :key="item.approvalId"
          class="mb-16px"
        >
          <NDescriptions
            :column="3"
            size="small"
            bordered
            label-placement="left"
          >
            <NDescriptionsItem label="审批编号">{{
              item.approvalId
            }}</NDescriptionsItem>
            <NDescriptionsItem label="来源页面"
              >{{ item.pageTitle }}（{{
                item.operationLabel
              }}）</NDescriptionsItem
            >
            <NDescriptionsItem label="来源单据号">
              {{ item.source.recordKey }}
              <span v-if="item.source.label">（{{ item.source.label }}）</span>
            </NDescriptionsItem>
            <NDescriptionsItem label="提交人">{{
              item.applicant.displayName
            }}</NDescriptionsItem>
            <NDescriptionsItem label="提交时间">{{
              item.submittedAt.replace("T", " ")
            }}</NDescriptionsItem>
            <NDescriptionsItem label="状态">
              {{ APPROVAL_STATUS[item.status] ?? item.status }} · 第
              {{ item.currentLevel }} 级
            </NDescriptionsItem>
          </NDescriptions>
          <NTable size="small" class="mt-8px" :single-line="false">
            <thead>
              <tr>
                <th>级别</th>
                <th>审批流</th>
                <th>节点</th>
                <th>方式</th>
                <th>状态</th>
                <th>审批人</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(step, index) in item.steps" :key="index">
                <td>第 {{ step.level }} 级</td>
                <td>{{ step.flowName }}</td>
                <td>{{ step.node }}</td>
                <td>{{ MODE[step.mode] ?? step.mode }}</td>
                <td>{{ STEP_STATUS[step.status] ?? step.status }}</td>
                <td>{{ membersText(step) }}</td>
              </tr>
            </tbody>
          </NTable>
          <div class="mt-8px flex justify-end">
            <NButton
              size="small"
              type="primary"
              secondary
              @click="runtime.openApprovalDetail(item.approvalId)"
            >
              查看审批详情
            </NButton>
          </div>
        </div>
        <div v-if="frozen?.message" class="approval-progress__message">
          {{ frozen.message }}
        </div>
      </NSpin>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="runtime.closeApprovals()">关闭</NButton>
        </NSpace>
      </template>
    </NCard>
  </NModal>
</template>

<style scoped>
.approval-progress {
  width: 960px;
  max-width: calc(100vw - 100px);
}

.approval-progress__message {
  padding: 16px 0;
  color: #667085;
  text-align: center;
}
</style>
