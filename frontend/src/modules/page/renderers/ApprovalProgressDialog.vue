<script setup lang="ts">
/**
 * 审批进度弹窗（FP-16）：用户修改被审批锁定的单据时直接弹出，内容来自 GET /api/approvals/{approvalId}（C09 第 6 节）。
 * 显示来源页面、来源单据号、提交人、提交时间、当前级别和各级节点的处理情况；不显示修改内容，不能在这里通过或驳回。
 */
import { computed } from 'vue';
import type { ApprovalDetail } from '../../../contracts/http';
import type { PageRuntime } from '../page-runtime';

defineOptions({ name: 'ApprovalProgressDialog' });

const props = defineProps<{ runtime: PageRuntime }>();
const runtime = props.runtime;
const frozen = computed(() => runtime.ui.frozen.value);

const STEP_STATUS: Record<string, string> = {
  passed: '已通过',
  pending: '待处理',
  rejected: '已驳回',
  upcoming: '未到'
};
const MEMBER_STATUS: Record<string, string> = { passed: '已通过', pending: '待处理', rejected: '已驳回' };
const MODE: Record<string, string> = { or: '或签', and: '会签' };

function members(step: ApprovalDetail['steps'][number]) {
  return step.members
    .map(m => {
      const by = m.processedBy ? `，${m.processedBy.displayName} ${m.processedAt?.replace('T', ' ') ?? ''}` : '';
      const comment = m.comment ? `，意见：${m.comment}` : '';
      return `${m.name}（${MEMBER_STATUS[m.status] ?? m.status}${by}${comment}）`;
    })
    .join('；');
}
</script>

<template>
  <NModal :show="Boolean(frozen)" @update:show="(v: boolean) => !v && runtime.closeApprovals()">
    <NCard
      class="approval-progress"
      title="单据在审批中，不能修改"
      :bordered="false"
      size="small"
      closable
      @close="runtime.closeApprovals()"
    >
      <NSpin :show="Boolean(frozen?.loading)">
        <div v-for="item in frozen?.items ?? []" :key="item.approvalId" class="mb-16px">
          <NDescriptions :column="3" size="small" bordered label-placement="left">
            <NDescriptionsItem label="审批编号">{{ item.approvalId }}</NDescriptionsItem>
            <NDescriptionsItem label="来源页面">{{ item.pageTitle }}（{{ item.operationLabel }}）</NDescriptionsItem>
            <NDescriptionsItem label="来源单据号">
              {{ item.source.recordKey }}
              <span v-if="item.source.label">（{{ item.source.label }}）</span>
            </NDescriptionsItem>
            <NDescriptionsItem label="提交人">{{ item.applicant.displayName }}</NDescriptionsItem>
            <NDescriptionsItem label="提交时间">{{ item.submittedAt.replace('T', ' ') }}</NDescriptionsItem>
            <NDescriptionsItem label="当前级别">第 {{ item.currentLevel }} 级</NDescriptionsItem>
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
                <td>{{ members(step) }}</td>
              </tr>
            </tbody>
          </NTable>
        </div>
        <div v-if="frozen?.message" class="text-error">{{ frozen.message }}</div>
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
</style>
