<script setup lang="ts">
/**
 * `/approval/:approvalId` 的路由组件（FA-05）：审批编号来自路由参数，在创建时取一次。
 * 外壳按页签直接挂载组件，非活动页签中的当前路由会变，所以不随路由变化（同 frontend-page 的 PageRoute）。
 */
import { useRoute } from 'vue-router';
import { useApprovalShell } from '../index';
import ApprovalDetailPage from './ApprovalDetailPage.vue';

defineOptions({ name: 'ApprovalDetailRoute' });

const props = defineProps<{ approvalId?: string }>();
const route = useRoute();
const approvalId = props.approvalId || String(route.params.approvalId ?? '');
const shell = useApprovalShell();
</script>

<template>
  <ApprovalDetailPage v-if="approvalId" :key="approvalId" :approval-id="approvalId" :shell="shell" />
  <div v-else class="h-full flex-center text-#999">缺少审批编号</div>
</template>
