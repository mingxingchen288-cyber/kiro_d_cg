<script setup lang="ts">
/**
 * 命令审查（C09 第 7a 节，FM-04）：开关、按用户和结果筛选、分页，展开一行查看这个命令执行的每条 SQL。
 * 关闭开关前确认，提示会清除全部记录。行为都在 command-review.ts。
 */
import { computed, h, onMounted, ref } from 'vue';
import { NButton, NDataTable, NInput, NSelect, NSwitch, NTable, NTag } from 'naive-ui';
import type { DataTableColumns, PaginationProps, SelectOption } from 'naive-ui';
import {
  COMMAND_RESULT,
  type CommandLog,
  type CommandOutcome,
  CommandReviewModel,
  REVIEW_PAGE_SIZE
} from '../command-review';
import type { AdminDeps } from '../shared';

defineOptions({ name: 'CommandReviewPanel' });

const props = defineProps<{ deps: AdminDeps }>();

const model = new CommandReviewModel(props.deps);
const state = model.state;
const user = ref('');
const result = ref<CommandOutcome | null>(null);

const resultOptions: SelectOption[] = (Object.keys(COMMAND_RESULT) as CommandOutcome[]).map(r => ({
  label: COMMAND_RESULT[r],
  value: r
}));

const resultTag: Record<CommandOutcome, 'success' | 'warning' | 'error'> = {
  saved: 'success',
  rejected: 'warning',
  failed: 'error'
};

const text = (value: unknown) => (typeof value === 'string' ? value : JSON.stringify(value));

/** 展开后的 SQL 列表：文本、绑定值、耗时、影响行数、错误 */
function renderSql(row: CommandLog) {
  if (!row.sql.length) return h('div', { class: 'text-12px text-#999' }, '没有记录到 SQL');
  return h(NTable, { size: 'small', bordered: true, singleLine: false }, () => [
    h('thead', [
      h('tr', [
        h('th', { style: 'width:40px' }, '#'),
        h('th', 'SQL'),
        h('th', { style: 'width:220px' }, '绑定值'),
        h('th', { style: 'width:80px' }, '耗时(ms)'),
        h('th', { style: 'width:70px' }, '行数'),
        h('th', { style: 'width:200px' }, '错误')
      ])
    ]),
    h(
      'tbody',
      row.sql.map((sql, index) =>
        h('tr', { key: index }, [
          h('td', String(index + 1)),
          h('td', [h('pre', { class: 'command-review__sql' }, sql.text)]),
          h('td', [h('pre', { class: 'command-review__sql' }, text(sql.binds))]),
          h('td', String(sql.ms)),
          h('td', sql.rows === null ? '' : String(sql.rows)),
          h('td', { class: sql.error ? 'text-error' : '' }, sql.error ?? '')
        ])
      )
    )
  ]);
}

const columns: DataTableColumns<CommandLog> = [
  { type: 'expand', renderExpand: renderSql },
  { title: '开始时间', key: 'startedAt', width: 170, render: row => row.startedAt.replace('T', ' ') },
  { title: '用户', key: 'user', width: 110 },
  { title: '页面', key: 'page', width: 150, render: row => row.page ?? '' },
  { title: '操作', key: 'operation', width: 200 },
  {
    title: '结果',
    key: 'result',
    width: 90,
    render: row => h(NTag, { size: 'small', type: resultTag[row.result] }, { default: () => COMMAND_RESULT[row.result] })
  },
  { title: '错误码', key: 'errorCode', width: 160, render: row => row.errorCode ?? '' },
  { title: '提示', key: 'message', ellipsis: { tooltip: true }, render: row => row.message ?? '' },
  { title: '总耗时(ms)', key: 'durationMs', width: 100 },
  { title: 'SQL 条数', key: 'sqlCount', width: 90 },
  { title: 'SQL 耗时(ms)', key: 'sqlMs', width: 110 }
];

const pagination = computed<PaginationProps>(() => ({
  page: state.page,
  pageSize: REVIEW_PAGE_SIZE,
  itemCount: state.total,
  prefix: ({ itemCount }) => `共 ${itemCount ?? 0} 条`
}));

function search() {
  void model.filter(user.value, result.value);
}

onMounted(() => {
  void model.load();
});
</script>

<template>
  <div class="admin-panel h-full flex-col">
    <div class="admin-panel__toolbar flex-y-center gap-8px">
      <span class="text-13px">命令审查</span>
      <NSwitch
        :value="state.enabled"
        :loading="state.toggling"
        :disabled="state.loading"
        @update:value="(v: boolean) => model.setEnabled(v)"
      />
      <span class="text-12px text-#999">开启后记录每个命令的结果和执行的 SQL，关闭时清除全部记录</span>
      <NInput v-model:value="user" size="small" clearable placeholder="用户（账号名）" class="w-160px" @keyup.enter="search" />
      <NSelect v-model:value="result" size="small" clearable placeholder="全部结果" class="w-120px" :options="resultOptions" />
      <NButton size="small" :loading="state.loading" @click="search">查询</NButton>
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
      :row-key="(row: CommandLog) => `${row.requestKey}@${row.startedAt}`"
      :pagination="pagination"
      @update:page="(p: number) => model.setPage(p)"
    />
  </div>
</template>

<style scoped>
.admin-panel__toolbar {
  padding: 4px 0 6px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

:deep(.command-review__sql) {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: Consolas, monospace;
  font-size: 12px;
}
</style>
