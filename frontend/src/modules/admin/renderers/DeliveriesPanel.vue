<script setup lang="ts">
/** 投递记录（C09 第 7 节）：按状态筛选、分页；只有已放弃的记录显示"重新排队"（FM-03）。行为都在 deliveries.ts */
import { computed, h, onMounted } from 'vue';
import { NButton, NDataTable, NSelect, NTag } from 'naive-ui';
import type { DataTableColumns, PaginationProps, SelectOption } from 'naive-ui';
import {
  DELIVERY_PAGE_SIZE,
  DELIVERY_STATUS,
  type DeliveryRow,
  type DeliveryStatus,
  DeliveriesModel,
  canRequeue
} from '../deliveries';
import type { AdminDeps } from '../shared';

defineOptions({ name: 'DeliveriesPanel' });

const props = defineProps<{ deps: AdminDeps }>();

const model = new DeliveriesModel(props.deps);
const state = model.state;

const ALL = '__all';
const statusOptions: SelectOption[] = [
  { label: '全部状态', value: ALL },
  ...(Object.keys(DELIVERY_STATUS) as DeliveryStatus[]).map(s => ({ label: DELIVERY_STATUS[s], value: s }))
];

const tagType: Record<DeliveryStatus, 'default' | 'success' | 'warning' | 'error'> = {
  pending: 'default',
  sent: 'success',
  failed: 'warning',
  abandoned: 'error'
};

const columns: DataTableColumns<DeliveryRow> = [
  { title: '投递编号', key: 'deliveryId', width: 300 },
  { title: '接收人（账号编号）', key: 'recipient', width: 140 },
  {
    title: '状态',
    key: 'status',
    width: 160,
    render: row => h(NTag, { size: 'small', type: tagType[row.status] }, { default: () => DELIVERY_STATUS[row.status] })
  },
  { title: '尝试次数', key: 'attempts', width: 90 },
  { title: '下次重试时间', key: 'nextRetryAt', width: 170, render: row => row.nextRetryAt?.replace('T', ' ') ?? '' },
  { title: '最后错误', key: 'lastError', ellipsis: { tooltip: true } },
  {
    title: '操作',
    key: 'action',
    width: 100,
    render: row =>
      canRequeue(row)
        ? h(
            NButton,
            {
              text: true,
              type: 'primary',
              size: 'small',
              loading: state.requeuing === row.deliveryId,
              onClick: () => model.requeue(row)
            },
            { default: () => '重新排队' }
          )
        : null
  }
];

const pagination = computed<PaginationProps>(() => ({
  page: state.page,
  pageSize: DELIVERY_PAGE_SIZE,
  itemCount: state.total,
  prefix: ({ itemCount }) => `共 ${itemCount ?? 0} 条`
}));

onMounted(() => {
  void model.load();
});
</script>

<template>
  <div class="admin-panel h-full flex-col">
    <div class="admin-panel__toolbar flex-y-center gap-8px">
      <NSelect
        size="small"
        class="w-160px"
        :options="statusOptions"
        :value="state.status ?? ALL"
        @update:value="(v: string) => model.setStatus(v === ALL ? null : (v as DeliveryStatus))"
      />
      <NButton size="small" :loading="state.loading" @click="model.load()">刷新</NButton>
      <span v-if="state.error" class="text-12px text-error">{{ state.error }}</span>
    </div>
    <NDataTable
      class="min-h-0 flex-1"
      flex-height
      remote
      size="small"
      :columns="columns"
      :data="state.rows"
      :loading="state.loading"
      :row-key="(row: DeliveryRow) => row.deliveryId"
      :pagination="pagination"
      @update:page="(p: number) => model.setPage(p)"
    />
  </div>
</template>

<style scoped>
.admin-panel__toolbar {
  padding: 4px 0 6px;
  flex-shrink: 0;
}
</style>
